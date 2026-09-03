"""Merging archived snapshots: what the union may and may not contain."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from explorer import archive
from explorer.dp import FlightNetwork, RouteCounter, Settings
from explorer.tests import fixtures

sys.setrecursionlimit(20000)

# two snapshots of the same day that each miss what the other caught, plus one broken overnight
# flight (arrival before departure) and one file too small to be a scan
SNAPSHOT_A = {
    'Dortmund': {'Budapest': [['2025-03-13T08:00:00+01:00', '2025-03-13T10:00:00+01:00']],
                 'Sofia': [['2025-03-13T09:00:00+01:00', '2025-03-13T12:30:00+02:00']]},
    'Budapest': {'Dortmund': [['2025-03-14T07:00:00+01:00', '2025-03-14T09:00:00+01:00']]},
}
SNAPSHOT_B = {
    'Dortmund': {'Budapest': [['2025-03-13T08:00:00+01:00', '2025-03-13T10:00:00+01:00'],
                              ['2025-03-13T18:00:00+01:00', '2025-03-13T20:00:00+01:00']]},
    'Budapest': {'Sofia': [['2025-03-13T22:00:00+01:00', '2025-03-14T01:00:00+02:00']],
                 # broken: lands before it takes off (the overnight date was never advanced)
                 'Vienna': [['2025-03-13T23:30:00+01:00', '2025-03-13T00:40:00+01:00']]},
}
TOO_SMALL = {'Dortmund': {'Sofia': [['2025-03-13T06:00:00+01:00', '2025-03-13T09:30:00+02:00']]}}


def _archive_dir(tmp: str) -> Path:
    directory = Path(tmp)
    for name, payload in (('2025_03_13_T08_00_00_flight_graph.json', SNAPSHOT_A),
                          ('2025_03_13_T20_00_00_flight_graph.json', SNAPSHOT_B),
                          ('2025_03_13_T21_00_00_flight_graph.json', TOO_SMALL)):
        (directory / name).write_text(json.dumps(payload), encoding='utf-8')
    return directory


def test_merge_unions_snapshots_and_drops_broken_flights():
    with tempfile.TemporaryDirectory() as tmp:
        index = archive.load_days(_archive_dir(tmp), min_flights=3)
        assert index.files_used == 2, 'the file below the threshold must be skipped'
        assert index.files_skipped == 1
        assert index.entries_dropped == 1, 'the backwards overnight flight must be dropped'
        assert sum(index.dropped_files.values()) == 1

        day = index.days['2025-03-13']
        # snapshot A had 2 departures that day, B had 3 of which 1 was broken; the shared one counts once
        assert len(day) == 4, sorted(day)
        assert ('Dortmund', 'Budapest', '2025-03-13T08:00:00+01:00', '2025-03-13T10:00:00+01:00') in day
        assert ('Dortmund', 'Sofia', '2025-03-13T09:00:00+01:00', '2025-03-13T12:30:00+02:00') in day
        assert ('Dortmund', 'Budapest', '2025-03-13T18:00:00+01:00', '2025-03-13T20:00:00+01:00') in day
        assert not any(f[1] == 'Vienna' for f in day), 'the broken flight must not survive the merge'
        assert index.scans_per_day['2025-03-13'] == 2
        assert index.days['2025-03-14'] == {
            ('Budapest', 'Dortmund', '2025-03-14T07:00:00+01:00', '2025-03-14T09:00:00+01:00')}


def test_merged_graph_is_usable_and_sorted():
    with tempfile.TemporaryDirectory() as tmp:
        index = archive.load_days(_archive_dir(tmp), min_flights=3)
        graph = archive.window_graph(index, '2025-03-13', 2)
        network = FlightNetwork.from_graph(graph)      # raises if a flight arrives before it departs
        assert len(network.flights) == 5
        assert [f[0] for f in graph['Dortmund']['Budapest']['flights']] == \
            ['2025-03-13T08:00:00+01:00', '2025-03-13T18:00:00+01:00'], 'flights must be sorted per edge'
        counter = RouteCounter(network, Settings(frozenset({'Dortmund'}), frozenset({'Dortmund'}),
                                                 1, 24, None, 3, 'none'))
        assert counter.totals().round_trip >= 1, 'the merged window must contain the round trip'


def test_windows_are_consecutive_and_ranked():
    with tempfile.TemporaryDirectory() as tmp:
        index = archive.load_days(_archive_dir(tmp), min_flights=3)
        found = archive.windows(index, 2)
        assert found == [(['2025-03-13', '2025-03-14'], 5)], found
        assert archive.windows(index, 3) == [], 'a window that runs past the archive is not offered'
        try:
            archive.window_graph(index, '2025-03-13', 3)
        except KeyError as exc:
            assert '2025-03-15' in str(exc)
        else:
            raise AssertionError('a window with a missing day must raise')


def test_browser_assembles_the_same_window_as_python():
    """The day files plus the browser's bundleFromDays must equal Python's merged window graph."""
    from explorer import build as build_mod
    from explorer.tests.test_js import node_binary, run_node

    if node_binary() is None or not archive.ARCHIVE_DIR.is_dir():
        return
    index = archive.load_days()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        manifest = build_mod.build_archive_day_bundles(index, out)
        start = archive.windows(index, 4)[0][0][0]          # densest window
        days = sorted(d['date'] for d in manifest['days'])
        window = days[days.index(start):days.index(start) + 4]
        payloads = [json.loads((out / f"arch-day-{day}.json").read_text(encoding='utf-8')) for day in window]

        for first_only in (False, True):
            graph = archive.window_graph(index, start, 4)
            if first_only:
                graph = build_mod.reduce_to_first_flight(graph)
            network = FlightNetwork.from_graph(graph)
            settings = Settings(frozenset({'Dortmund'}), frozenset({'Dortmund'}), 1, 24, 4, 3, 'calendar')
            expected = RouteCounter(network, settings).totals()
            js = run_node(None, {'startCities': ['Dortmund'], 'returnCities': ['Dortmund'],
                                 'minGapHours': 1, 'maxGapHours': 24, 'maxFlights': 4,
                                 'dailyCap': 3, 'capMode': 'calendar'}, [],
                          manifest=manifest, days=payloads, first_flight_only=first_only)
            where = f"{start} +4d first_only={first_only}"
            assert js['assembled']['days'] == window, f"{where}: window is {js['assembled']['days']}"
            assert js['assembled']['flights'] == len(network.flights), \
                f"{where}: js assembled {js['assembled']['flights']} flights, py has {len(network.flights)}"
            assert js['assembled']['edges'] == graph.number_of_edges(), \
                f"{where}: js has {js['assembled']['edges']} routes, py has {graph.number_of_edges()}"
            assert js['oneWay'] == expected.one_way and js['roundTrip'] == expected.round_trip, \
                f"{where}: js {js['oneWay']}/{js['roundTrip']} != py {expected.one_way}/{expected.round_trip}"


def test_real_archive_is_consistent():
    """The archive on disk must load, and its merge must beat the single scan it overlaps."""
    if not archive.ARCHIVE_DIR.is_dir():
        return
    index = archive.load_days()
    info = archive.summary(index)
    assert info['files_used'] > 100, info['files_used']
    assert info['flight_days'] > 100 and info['first_day'] < info['last_day']
    assert info['unique_flights'] > 50000, info['unique_flights']
    # every dropped entry sits in the first scan, which is the only one with the overnight-date bug
    assert set(index.dropped_files) <= {'2024_09_30_T11_14_10_flight_graph.json'}, dict(index.dropped_files)

    # the days of data/current/graph.pkl merged from the archive must contain at least that scan's flights
    scan = fixtures.real_graph('pkl')
    scan_flights = {(a, b, f[0], f[1]) for a, b, at in scan.edges(data=True) for f in at['flights']}
    days = sorted({f[2][:10] for f in scan_flights})
    if all(day in index.days for day in days):
        merged = index.flights_on(days)
        missing = scan_flights - merged
        assert not missing, f"{len(missing)} flights of graph.pkl are not in the archive merge"
        assert len(merged) > len(scan_flights), 'merging several snapshots must add flights'
