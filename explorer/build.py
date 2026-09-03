"""Turn a scan in data/current/ into the JSON bundle the browser explorer loads.

data/current/ is read-only here; bundles are written to data/explorer/ (git-ignored).

Bundle layout (compact on purpose - the browser holds it in memory and recomputes the DAG on every
settings change)::

    {
      "scan": "pkl-2025-03", "label": "...", "source": "data/current/graph.pkl",
      "day0": "2025-03-12", "days": ["2025-03-12", ...],
      "cities":  [{"name","lat","lon","country","countryNew","cityNew"}, ...],
      "flights": [[originIdx, destIdx, depEpoch, arrEpoch, dayIdx, "Thu 13/03 08:35", "Thu 13/03 11:20"], ...],
      "stats":   {"cities","edges","flights","invisibleFlights"}
    }

``depEpoch``/``arrEpoch`` are absolute seconds, ``dayIdx`` is the local calendar day at the departure
airport counted from ``day0``.  The labels are pre-rendered from the ISO offsets so the browser never
does timezone maths of its own.  Flights are in the order of ``dp.FlightNetwork``, so a flight index
means the same flight in Python and in JavaScript.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import networkx as nx

from explorer import coords
from explorer.dp import FlightNetwork, parse_label
from simulate import datasets

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = PROJECT_ROOT / 'data' / 'explorer'
DEFAULT_SCANS = (datasets.GRAPH_PKL, datasets.FLIGHT_GRAPH_JSON)
DEFAULT_START = 'Dortmund'

MONTHS_DE = ('Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September',
             'Oktober', 'November', 'Dezember')


class MissingCoordinates(RuntimeError):
    """Raised when a scan contains a city that explorer/coords.py does not know."""

    def __init__(self, cities: Sequence[str], source: str):
        self.cities = list(cities)
        self.source = source
        listing = '\n'.join(f"    '{c}': (lat, lon)," for c in cities)
        super().__init__(f"{len(cities)} cities in {source} have no coordinates. "
                         f"Add them to explorer/coords.py:\n{listing}")


def scan_name(path: Path, day0: date) -> str:
    """Stable id: ``<suffix>-<YYYY-MM>`` of the first scan day, e.g. ``pkl-2025-03``."""
    return f"{path.suffix.lstrip('.')}-{day0:%Y-%m}"


def scan_label(path: Path, day0: date) -> str:
    return f"{MONTHS_DE[day0.month - 1]} {day0.year} ({path.name})"


def reduce_to_first_flight(graph):
    """The scan as the buggy ``core/route_find.py`` sees it: only ``flights[0]`` per edge.

    ``graph[a][b].values()`` yields the whole flights list as its single value, so the original
    search only ever uses the earliest flight of an edge.  Running the fixed search on this reduced
    graph therefore produces exactly the original's route set - checked in
    ``explorer/tests/test_dp.py::test_first_flight_view_equals_the_original_search``.

    Precondition: ``graph`` has the core/converter.py shape.  Postcondition: a new DiGraph with the
    same nodes and edges, one flight each; the input is not modified.
    """
    reduced = nx.DiGraph()
    reduced.add_nodes_from(graph.nodes)
    for origin, dest, attrs in graph.edges(data=True):
        flights = attrs['flights']
        if not flights:
            raise ValueError(f"edge {origin} -> {dest} has no flights")
        earliest = min(flights, key=lambda f: f[0])
        reduced.add_edge(origin, dest, flights=[list(earliest)])
    return reduced


def build_bundle(path: Path, preferences: Optional[dict] = None) -> dict:
    """Read one scan file and return its bundle.

    Precondition: ``path`` is a .pkl (pickled DiGraph) or .json (flight_graph layout) scan.
    Postcondition: see ``bundle_from_graph``.
    """
    graph = datasets.load_real_graph(path)
    day0 = min(date.fromisoformat(f[0][:10]) for _, _, attrs in graph.edges(data=True) for f in attrs['flights'])
    return bundle_from_graph(graph, scan_name(path, day0), scan_label(path, day0), path, preferences)



def country_records(cities: Sequence[str], index_of: Dict[str, int], preferences: dict) -> List[dict]:
    """Countries of these cities, each with its German name and the city indices it covers.

    Precondition: ``index_of`` maps every name in ``cities`` to its bundle index.  Postcondition:
    sorted by German name; cities whose country is unknown to preferences.json are left out, so a
    country requirement can never be satisfied by a city we cannot attribute.
    """
    city_data, country_data = preferences['city'], preferences['country']
    grouped: Dict[str, List[int]] = {}
    for city in cities:
        country = city_data.get(city, {}).get('country')
        if country:
            grouped.setdefault(country, []).append(index_of[city])
    records = []
    for country, members in grouped.items():
        info = country_data.get(country, {})
        records.append({
            'name': country,
            'de': info.get('german_name') or country,
            'new': not info.get('visited', True),
            'cities': sorted(members),
        })
    records.sort(key=lambda record: record['de'])
    return records


def bundle_from_graph(graph, name: str, label: str, source: Path, preferences: Optional[dict] = None) -> dict:
    """Turn a flight graph into the browser bundle.

    Preconditions: ``graph`` has the core/converter.py shape; every city has coordinates.
    Postconditions: ``MissingCoordinates`` is raised with the full list when a city is unknown;
    flights are ordered exactly as in ``dp.FlightNetwork``, so flight indices are shared between the
    Python reference and the browser.
    """
    network = FlightNetwork.from_graph(graph)
    cities = network.cities
    unknown = coords.missing(cities)
    if unknown:
        raise MissingCoordinates(unknown, str(source))

    preferences = preferences if preferences is not None else datasets.load_preferences()
    city_data, country_data = preferences['city'], preferences['country']
    day0 = min(date.fromisoformat(f.dep_day) for f in network.flights)
    last_day = max(date.fromisoformat(f.dep_day) for f in network.flights)
    n_days = (last_day - day0).days + 1

    index_of: Dict[str, int] = {city: i for i, city in enumerate(cities)}
    city_records = []
    for city in cities:
        lat, lon = coords.coords_of(city)
        country = city_data.get(city, {}).get('country')
        country_new = None if country is None else not country_data.get(country, {}).get('visited', True)
        city_new = city_data.get(city, {}).get('visited')
        city_records.append({
            'name': city, 'lat': lat, 'lon': lon, 'country': country,
            'countryNew': country_new, 'cityNew': None if city_new is None else not city_new,
        })

    flight_records: List[list] = []
    for f in network.flights:
        day_index = (date.fromisoformat(f.dep_day) - day0).days
        flight_records.append([index_of[f.origin], index_of[f.dest], int(f.dep), int(f.arr),
                               day_index, f.dep_label, f.arr_label])

    invisible = sum(len(attrs['flights']) - 1 for _, _, attrs in graph.edges(data=True))
    source = Path(source)
    countries = country_records(cities, index_of, preferences)
    return {
        'scan': name,
        'label': label,
        'source': str(source.relative_to(PROJECT_ROOT)) if source.is_relative_to(PROJECT_ROOT) else str(source),
        'day0': day0.isoformat(),
        'days': [(date.fromordinal(day0.toordinal() + i)).isoformat() for i in range(n_days)],
        'cities': city_records,
        'countries': countries,
        'flights': flight_records,
        'stats': {'cities': graph.number_of_nodes(), 'edges': graph.number_of_edges(),
                  'flights': len(network.flights), 'invisibleFlights': invisible},
        'defaultStart': DEFAULT_START if DEFAULT_START in index_of else cities[0],
    }


def write_bundle(bundle: dict, out_dir: Path = BUNDLE_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{bundle['scan']}.json"
    with target.open('w', encoding='utf-8') as handle:
        json.dump(bundle, handle, ensure_ascii=False, separators=(',', ':'))
    return target


def build_archive_windows(starts: Sequence[str], length: int = 4, out_dir: Path = BUNDLE_DIR,
                          with_original: bool = True, index=None,
                          preferences: Optional[dict] = None) -> List[dict]:
    """Bundles for merged archive windows: all snapshots of those flight days taken together.

    Preconditions: ``starts`` are ISO dates present in the archive; ``length >= 1``.
    Postconditions: one bundle per window (plus its ``-original`` twin when asked), named
    ``arch-<start>-<length>d``; returns one info dict per bundle.
    """
    from explorer import archive

    index = index if index is not None else archive.load_days()
    preferences = preferences if preferences is not None else datasets.load_preferences()
    built = []
    for start in starts:
        graph = archive.window_graph(index, start, length)
        day0 = date.fromisoformat(start)
        scans = sum(index.scans_per_day.get((day0 + timedelta(days=i)).isoformat(), 0) for i in range(length))
        name = f"arch-{start}-{length}d"
        pretty = f"{day0:%d.%m.%Y} + {length - 1} Tage (Archiv, {scans} Scans zusammengelegt)"
        variants = [(graph, name, f"{pretty} – Fix (alle Flüge)")]
        if with_original:
            variants.append((reduce_to_first_flight(graph), f"{name}-original",
                             f"{pretty} – Originalcode (nur je erster Flug)"))
        for variant_graph, variant_name, label in variants:
            bundle = bundle_from_graph(variant_graph, variant_name, label, archive.ARCHIVE_DIR, preferences)
            target = write_bundle(bundle, out_dir)
            built.append({'scan': bundle['scan'], 'label': bundle['label'], 'source': bundle['source'],
                          'path': target, 'stats': bundle['stats'], 'day0': bundle['day0'],
                          'days': len(bundle['days']), 'bytes': target.stat().st_size,
                          'defaultStart': bundle['defaultStart']})
    return built


ARCHIVE_MANIFEST = 'archive-days.json'
STATIC_DIR = Path(__file__).resolve().parent / 'static'

#: Vercel serves the folder as-is; the JSON payloads may be cached hard because a redeploy
#: replaces them wholesale, index.html must not be cached so a redeploy is picked up.
VERCEL_CONFIG = {
    "$schema": "https://openapi.vercel.sh/vercel.json",
    "cleanUrls": True,
    "headers": [
        {"source": "/bundles/(.*)",
         "headers": [{"key": "Cache-Control", "value": "public, max-age=86400, must-revalidate"}]},
        {"source": "/(.*)\\.(js|css)",
         "headers": [{"key": "Cache-Control", "value": "public, max-age=3600, must-revalidate"}]},
        {"source": "/",
         "headers": [{"key": "Cache-Control", "value": "no-store"}]},
    ],
}


def export_site(out_dir: Path, bundle_dir: Path = BUNDLE_DIR) -> dict:
    """Copy the UI and the built bundles into one self-contained folder for any static host.

    Preconditions: ``bundle_dir`` holds ``index.json`` and its bundles (run a build first).
    Postconditions: ``out_dir`` contains index.html, the assets, ``bundles/`` and a ``vercel.json``;
    it needs no server-side code at all.  Returns a summary with file counts and total size.
    """
    import shutil

    bundle_dir = Path(bundle_dir)
    if not (bundle_dir / 'index.json').is_file():
        raise FileNotFoundError(f"no bundles in {bundle_dir}; run 'python -m explorer build' first")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    assets = []
    for asset in sorted(STATIC_DIR.iterdir()):
        if asset.is_file():
            shutil.copy2(asset, out_dir / asset.name)
            assets.append(asset.name)

    target_bundles = out_dir / 'bundles'
    if target_bundles.exists():
        shutil.rmtree(target_bundles)
    target_bundles.mkdir(parents=True)
    payloads = []
    for payload in sorted(bundle_dir.glob('*.json')):
        shutil.copy2(payload, target_bundles / payload.name)
        payloads.append(payload.name)

    with (out_dir / 'vercel.json').open('w', encoding='utf-8') as handle:
        json.dump(VERCEL_CONFIG, handle, ensure_ascii=False, indent=2)

    total = sum(path.stat().st_size for path in out_dir.rglob('*') if path.is_file())
    return {'dir': out_dir, 'assets': assets, 'bundles': payloads, 'bytes': total}


def build_archive_day_bundles(index=None, out_dir: Path = BUNDLE_DIR,
                              preferences: Optional[dict] = None) -> dict:
    """One small bundle per archived flight day plus a manifest, so the browser can assemble any
    window itself.

    All day files share the manifest's city table, therefore a city index means the same city in
    every day file and merging days is just concatenating their flights.  A flight row is
    ``[originIdx, destIdx, depEpoch, arrEpoch, depDateISO, depLabel, arrLabel]``; the day index the
    DP needs is derived from ``depDateISO`` once a window is chosen.

    Preconditions: the archive is readable and every city in it has coordinates.
    Postconditions: ``out_dir/archive-days.json`` plus ``out_dir/arch-day-<date>.json`` per day;
    returns the manifest.
    """
    from explorer import archive

    index = index if index is not None else archive.load_days()
    preferences = preferences if preferences is not None else datasets.load_preferences()
    cities = sorted(index.cities)
    unknown = coords.missing(cities)
    if unknown:
        raise MissingCoordinates(unknown, str(archive.ARCHIVE_DIR))

    city_data, country_data = preferences['city'], preferences['country']
    index_of = {city: i for i, city in enumerate(cities)}
    city_records = []
    for city in cities:
        lat, lon = coords.coords_of(city)
        country = city_data.get(city, {}).get('country')
        country_new = None if country is None else not country_data.get(country, {}).get('visited', True)
        city_new = city_data.get(city, {}).get('visited')
        city_records.append({'name': city, 'lat': lat, 'lon': lon, 'country': country,
                             'countryNew': country_new,
                             'cityNew': None if city_new is None else not city_new})

    out_dir.mkdir(parents=True, exist_ok=True)
    days_info = []
    for day in index.sorted_days:
        rows = []
        for origin, dest, dep_iso, arr_iso in index.days[day]:
            dep, arr = datetime.fromisoformat(dep_iso), datetime.fromisoformat(arr_iso)
            rows.append([index_of[origin], index_of[dest], int(dep.timestamp()), int(arr.timestamp()),
                         dep_iso[:10], parse_label(dep_iso), parse_label(arr_iso)])
        rows.sort(key=lambda row: (row[2], row[0], row[1]))
        target = out_dir / f"arch-day-{day}.json"
        with target.open('w', encoding='utf-8') as handle:
            json.dump({'date': day, 'flights': rows}, handle, ensure_ascii=False, separators=(',', ':'))
        days_info.append({'date': day, 'flights': len(rows), 'scans': index.scans_per_day.get(day, 0),
                          'file': target.name, 'bytes': target.stat().st_size})

    manifest = {
        'kind': 'archive-days',
        'cities': city_records,
        'countries': country_records(cities, index_of, preferences),
        'days': days_info,
        'defaultStart': DEFAULT_START if DEFAULT_START in index_of else cities[0],
        'source': str(archive.ARCHIVE_DIR.relative_to(PROJECT_ROOT)),
        'stats': {'flightDays': len(days_info), 'uniqueFlights': sum(d['flights'] for d in days_info),
                  'cities': len(cities), 'filesUsed': index.files_used,
                  'entriesDropped': index.entries_dropped},
    }
    with (out_dir / ARCHIVE_MANIFEST).open('w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, separators=(',', ':'))
    return manifest


def write_index(built: Sequence[dict], out_dir: Path = BUNDLE_DIR) -> Path:
    """Write index.json listing every bundle, in the order given."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {'scans': [{k: (str(v) if isinstance(v, Path) else v) for k, v in info.items()}
                       for info in built]}
    target = out_dir / 'index.json'
    with target.open('w', encoding='utf-8') as handle:
        json.dump(index, handle, ensure_ascii=False, indent=1)
    return target


def build_all(paths: Sequence[Path] = DEFAULT_SCANS, out_dir: Path = BUNDLE_DIR,
              with_original: bool = True) -> List[dict]:
    """Build every scan and write an index.json listing them.  Returns one info dict per bundle.

    With ``with_original`` each scan also yields a ``<scan>-original`` bundle reduced to the first
    flight per route - the view the buggy search had.
    """
    preferences = datasets.load_preferences()
    built = []
    for path in paths:
        path = Path(path)
        graph = datasets.load_real_graph(path)
        day0 = min(date.fromisoformat(f[0][:10]) for _, _, attrs in graph.edges(data=True)
                   for f in attrs['flights'])
        variants = [(graph, scan_name(path, day0), f"{scan_label(path, day0)} – Fix (alle Flüge)")]
        if with_original:
            variants.append((reduce_to_first_flight(graph), f"{scan_name(path, day0)}-original",
                             f"{scan_label(path, day0)} – Originalcode (nur je erster Flug)"))
        for variant_graph, name, label in variants:
            bundle = bundle_from_graph(variant_graph, name, label, path, preferences)
            target = write_bundle(bundle, out_dir)
            built.append({'scan': bundle['scan'], 'label': bundle['label'], 'source': bundle['source'],
                          'path': target, 'stats': bundle['stats'], 'day0': bundle['day0'],
                          'days': len(bundle['days']), 'bytes': target.stat().st_size,
                          'defaultStart': bundle['defaultStart']})
    write_index(built, out_dir)
    return built
