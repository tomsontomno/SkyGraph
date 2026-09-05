"""How risky is improvising the way home?

The Multipass horizon is "today plus three days": you can never book further ahead, so a trip that
flies out one-way has to find its return leg while already travelling.  This module answers, from
the archive, how often that would have failed.

For every landing in a scan it computes two things by a single backward pass over the flight DAG,
in descending departure order (successors always depart later, so that order is topological):

  * ``earliest_home`` - the earliest moment you could be standing in a home city again,
  * ``flights_home``  - the fewest flights needed to get there.

A landing counts as **stranded** when no way home exists at all, and as **late** when the fastest
way home takes longer than the booking horizon.

Two honest caveats, both stated in the report:
  * Landings near the end of the data look stranded only because the scan stops.  They are excluded:
    a landing is only judged when at least ``horizon_hours`` of scanned time remain after it.
  * The three-flights-per-day booking cap is ignored here.  It can only matter when the way home
    needs four or more flights on one day, which the report counts separately.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from explorer.dp import FlightNetwork


@dataclass
class StrandReport:
    """Outcome of one scan.  Times are hours, shares are fractions of judged landings."""
    landings_total: int
    landings_judged: int
    stranded: int
    late: int
    hours: List[float]
    flights: List[int]
    worst_cities: List[Tuple[str, int, int]]      # city, judged landings, stranded + late
    horizon_hours: float
    needs_four_flights: int

    @property
    def risk(self) -> float:
        return (self.stranded + self.late) / self.landings_judged if self.landings_judged else 0.0

    def percentile(self, p: float) -> float:
        if not self.hours:
            return float('nan')
        ordered = sorted(self.hours)
        position = min(len(ordered) - 1, max(0, int(round(p / 100 * (len(ordered) - 1)))))
        return ordered[position]


def analyse(network: FlightNetwork, home: FrozenSet[str], min_gap_hours: float = 1.0,
            max_gap_hours: float = 18.0, horizon_hours: float = 72.0) -> StrandReport:
    """Judge every landing in ``network``.

    Preconditions: ``home`` non-empty; ``0 <= min_gap < max_gap``; ``horizon_hours > 0``.
    Postcondition: only landings with ``horizon_hours`` of scanned time left are judged, so the end
    of the data cannot masquerade as a stranding.
    """
    if not home:
        raise ValueError("home must not be empty")
    if min_gap_hours < 0 or max_gap_hours <= min_gap_hours:
        raise ValueError(f"need 0 <= min_gap < max_gap, got {min_gap_hours}/{max_gap_hours}")
    if horizon_hours <= 0:
        raise ValueError(f"horizon_hours must be positive, got {horizon_hours}")

    flights = network.flights
    successors = network.successors(min_gap_hours, max_gap_hours)
    order = sorted(range(len(flights)), key=lambda i: flights[i].dep, reverse=True)
    last_departure = max(f.dep for f in flights)

    earliest = [math.inf] * len(flights)
    hops = [0] * len(flights)
    for i in order:
        flight = flights[i]
        if flight.dest in home:
            earliest[i] = flight.arr
            hops[i] = 0
            continue
        best, best_hops = math.inf, 0
        for j in successors[i]:
            if earliest[j] < best:
                best, best_hops = earliest[j], hops[j] + 1
        earliest[i], hops[i] = best, best_hops

    judged_hours: List[float] = []
    judged_flights: List[int] = []
    stranded = late = four_plus = 0
    per_city: Dict[str, List[int]] = {}
    judged = 0
    for i, flight in enumerate(flights):
        if flight.dest in home:
            continue                                    # already home, nothing to improvise
        if flight.arr + horizon_hours * 3600 > last_departure:
            continue                                    # the scan ends too soon to judge this one
        judged += 1
        bucket = per_city.setdefault(flight.dest, [0, 0])
        bucket[0] += 1
        if earliest[i] == math.inf:
            stranded += 1
            bucket[1] += 1
            continue
        hours = (earliest[i] - flight.arr) / 3600.0
        judged_hours.append(hours)
        judged_flights.append(hops[i])
        if hops[i] >= 4:
            four_plus += 1
        if hours > horizon_hours:
            late += 1
            bucket[1] += 1

    worst = sorted(((city, seen, bad) for city, (seen, bad) in per_city.items() if bad),
                   key=lambda row: (-row[2], row[0]))
    return StrandReport(
        landings_total=sum(1 for f in flights if f.dest not in home),
        landings_judged=judged, stranded=stranded, late=late,
        hours=judged_hours, flights=judged_flights, worst_cities=worst[:12],
        horizon_hours=horizon_hours, needs_four_flights=four_plus)


def format_report(report: StrandReport, label: str) -> List[str]:
    """A handful of lines for the terminal."""
    if not report.landings_judged:
        return [f"{label}: keine Landung liegt weit genug vor dem Ende der Daten"]
    share = 100 * report.risk
    lines = [
        f"{label}",
        f"  beurteilte Landungen : {report.landings_judged:,} von {report.landings_total:,} "
        f"(der Rest liegt zu nah am Ende der Daten)",
        f"  ohne Weg nach Hause  : {report.stranded}",
        f"  Heimweg > {report.horizon_hours:.0f} h      : {report.late}",
        f"  Risiko gesamt        : {share:.3f} %",
        f"  Stunden bis zu Hause : Median {statistics.median(report.hours):.1f}, "
        f"90 % unter {report.percentile(90):.1f}, 99 % unter {report.percentile(99):.1f}, "
        f"schlimmster Fall {max(report.hours):.1f}",
        f"  Flüge bis zu Hause   : Median {statistics.median(report.flights):.0f}, "
        f"höchstens {max(report.flights)}; vier oder mehr in {report.needs_four_flights} Fällen",
    ]
    if report.worst_cities:
        worst = ', '.join(f"{city} ({bad}/{seen})" for city, seen, bad in report.worst_cities[:6])
        lines.append(f"  heikelste Orte       : {worst}")
    return lines
