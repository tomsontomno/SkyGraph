"""Merge the archived scans in data/archives/flight_graph/ into denser flight graphs.

Every scan is a snapshot of the same real timetable taken at one moment; different runs caught
different flights because fetches fail.  Taking the union of all snapshots that cover a flight day
therefore yields a more complete picture of that day than any single scan.

What the union is and is not
  * It is the set of flights that were offered on that day at some point during the scanning period.
  * It is not one consistent timetable: a flight that was cancelled between two scans stays in the
    union, and a rescheduled flight can appear at both times.  For exploring what was reachable this
    is what you want; for booking it is not.

Data hygiene: 232 entries arrive at or before their departure (overnight flights whose arrival date
was not advanced).  All of them sit in the very first scan, 2024_09_30_T11_14_10; every later scan is
clean.  ``load_days`` drops such entries and counts them, so the merge never produces a flight that
travels backwards in time.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import networkx as nx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = PROJECT_ROOT / 'data' / 'archives' / 'flight_graph'

#: A file with fewer entries than this is a failed run, not a scan.
MIN_FLIGHTS_PER_SCAN = 50
#: Flights of one day, as ``(origin, destination, departure_iso, arrival_iso)``.
Flight = Tuple[str, str, str, str]


@dataclass
class ArchiveIndex:
    """Everything the archive holds, grouped by the local departure date."""
    days: Dict[str, Set[Flight]] = field(default_factory=dict)
    scans_per_day: Counter = field(default_factory=Counter)
    files_used: int = 0
    files_skipped: int = 0
    entries_read: int = 0
    entries_dropped: int = 0
    dropped_files: Counter = field(default_factory=Counter)

    @property
    def sorted_days(self) -> List[str]:
        return sorted(self.days)

    @property
    def cities(self) -> Set[str]:
        return {city for flights in self.days.values() for flight in flights for city in flight[:2]}

    def flights_on(self, days: Sequence[str]) -> Set[Flight]:
        merged: Set[Flight] = set()
        for day in days:
            merged |= self.days.get(day, set())
        return merged


def load_days(archive_dir: Path = ARCHIVE_DIR, min_flights: int = MIN_FLIGHTS_PER_SCAN) -> ArchiveIndex:
    """Read every archived scan and group its flights by local departure date.

    Precondition: ``archive_dir`` exists and holds ``*_flight_graph.json`` files in the
    ``{origin: {destination: [[dep, arr], ...]}}`` layout.  Postcondition: the index contains only
    flights that arrive strictly after they depart; the counters report what was skipped and why.
    Raises FileNotFoundError when the directory is missing.
    """
    archive_dir = Path(archive_dir)
    if not archive_dir.is_dir():
        raise FileNotFoundError(f"archive directory not found: {archive_dir}")
    index = ArchiveIndex(days=defaultdict(set))
    for path in sorted(archive_dir.glob('*.json')):
        try:
            with path.open('r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            index.files_skipped += 1
            index.dropped_files[f"{path.name}: unlesbar ({exc.__class__.__name__})"] += 1
            continue
        if not isinstance(data, dict):
            index.files_skipped += 1
            continue
        entries = [(origin, dest, flight[0], flight[1])
                   for origin, destinations in data.items()
                   for dest, flights in destinations.items()
                   for flight in flights
                   if isinstance(flight, list) and len(flight) == 2]
        if len(entries) < min_flights:
            index.files_skipped += 1
            continue
        index.files_used += 1
        touched: Set[str] = set()
        for origin, dest, dep, arr in entries:
            index.entries_read += 1
            try:
                departure, arrival = datetime.fromisoformat(dep), datetime.fromisoformat(arr)
            except ValueError:
                index.entries_dropped += 1
                index.dropped_files[path.name] += 1
                continue
            if arrival <= departure:
                # overnight flight whose arrival date was never advanced - drop, do not guess
                index.entries_dropped += 1
                index.dropped_files[path.name] += 1
                continue
            day = dep[:10]
            index.days[day].add((origin, dest, dep, arr))
            touched.add(day)
        for day in touched:
            index.scans_per_day[day] += 1
    index.days = dict(index.days)
    return index


def graph_from_flights(flights: Iterable[Flight]) -> nx.DiGraph:
    """Build the core/converter.py graph shape from flight tuples, flights sorted per edge."""
    graph = nx.DiGraph()
    for origin, dest, dep, arr in sorted(flights):
        if not graph.has_edge(origin, dest):
            graph.add_edge(origin, dest, flights=[])
        graph[origin][dest]['flights'].append([dep, arr])
    for _, _, attrs in graph.edges(data=True):
        attrs['flights'].sort(key=lambda f: f[0])
    if graph.number_of_edges() == 0:
        raise ValueError("no flights in this window")
    return graph


def windows(index: ArchiveIndex, length: int = 4) -> List[Tuple[List[str], int]]:
    """All consecutive ``length``-day windows with their merged flight count, densest first.

    Precondition: ``length >= 1``.  Postcondition: only windows whose days are calendar-consecutive
    and all present in the archive are returned.
    """
    if length < 1:
        raise ValueError(f"window length must be >= 1, got {length}")
    days = index.sorted_days
    available = set(days)
    found = []
    for start in days:
        first = date.fromisoformat(start)
        window = [(first + timedelta(days=offset)).isoformat() for offset in range(length)]
        if not all(day in available for day in window):
            continue
        found.append((window, sum(len(index.days[day]) for day in window)))
    found.sort(key=lambda item: (-item[1], item[0][0]))
    return found


def window_graph(index: ArchiveIndex, start_day: str, length: int = 4) -> nx.DiGraph:
    """Merged graph for the ``length`` days beginning at ``start_day``.

    Raises KeyError naming the missing day when the window is not fully covered.
    """
    first = date.fromisoformat(start_day)
    days = [(first + timedelta(days=offset)).isoformat() for offset in range(length)]
    missing = [day for day in days if day not in index.days]
    if missing:
        raise KeyError(f"archive has no flights for {', '.join(missing)}")
    return graph_from_flights(index.flights_on(days))


def summary(index: ArchiveIndex) -> dict:
    """Descriptive numbers for the CLI."""
    days = index.sorted_days
    per_day = {day: len(flights) for day, flights in index.days.items()}
    unique = sum(per_day.values())
    return {
        'files_used': index.files_used,
        'files_skipped': index.files_skipped,
        'entries_read': index.entries_read,
        'entries_dropped': index.entries_dropped,
        'dropped_files': dict(index.dropped_files),
        'flight_days': len(days),
        'first_day': days[0] if days else None,
        'last_day': days[-1] if days else None,
        'unique_flights': unique,
        'cities': len(index.cities),
        'routes': len({(f[0], f[1]) for flights in index.days.values() for f in flights}),
        'max_scans_per_day': max(index.scans_per_day.values(), default=0),
        'median_scans_per_day': sorted(index.scans_per_day.values())[len(index.scans_per_day) // 2]
        if index.scans_per_day else 0,
        'flights_per_day': per_day,
    }
