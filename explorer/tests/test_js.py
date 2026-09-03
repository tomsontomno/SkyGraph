"""The browser DP (static/dp.js) must produce the same numbers as the Python reference (dp.py).

Both read the same bundle, so a flight index means the same flight on both sides.  Without node the
check reports itself as skipped instead of failing - the Python reference is still covered by
test_dp.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from explorer import build as build_mod, coords
from explorer.dp import Flight, FlightNetwork, RouteCounter, Settings
from explorer.tests import fixtures

sys.setrecursionlimit(20000)

NODE_CHECK = Path(__file__).resolve().parent / 'dp_node_check.js'
CASES = [
    {'maxFlights': None, 'capMode': 'none'},
    {'maxFlights': None, 'capMode': 'calendar'},
    {'maxFlights': None, 'capMode': 'rolling24'},
    {'maxFlights': 5, 'capMode': 'calendar'},
    {'maxFlights': 3, 'capMode': 'rolling24'},
    {'maxFlights': 6, 'capMode': 'calendar', 'required': ['Abu Dhabi']},
    {'maxFlights': 6, 'capMode': 'none', 'required': ['Budapest', 'Abu Dhabi']},
]


def node_binary() -> Optional[str]:
    return shutil.which('node')


def network_from_bundle(bundle: dict) -> FlightNetwork:
    """Rebuild the Python network from a bundle so both sides see identical flight indices."""
    names = [city['name'] for city in bundle['cities']]
    flights = [Flight(0, names[row[0]], names[row[1]], float(row[2]), float(row[3]),
                      bundle['days'][row[4]], row[5], row[6]) for row in bundle['flights']]
    network = FlightNetwork(flights)
    for i, row in enumerate(bundle['flights']):
        assert network.flights[i].origin == names[row[0]] and network.flights[i].dep == float(row[2]), \
            f"flight {i} differs between bundle and FlightNetwork - the orders must match"
    return network


def run_node(bundle: Optional[dict], settings: dict, path, radius_center: Optional[str] = None,
             radius: Optional[float] = None, manifest: Optional[dict] = None,
             days: Optional[list] = None, first_flight_only: bool = False) -> dict:
    """Run the browser DP under node.  Either pass a ready ``bundle`` or a ``manifest`` plus ``days``
    for the archive path, in which case dp.js assembles the window itself."""
    node = node_binary()
    if node is None:
        raise RuntimeError('node not available')
    if bundle is None and (manifest is None or days is None):
        raise ValueError("pass either a bundle or a manifest with its day files")
    payload = {'bundle': bundle, 'settings': settings, 'path': list(path),
               'radiusCenter': radius_center, 'radius': radius,
               'manifest': manifest, 'days': days, 'firstFlightOnly': first_flight_only}
    with tempfile.TemporaryDirectory() as tmp:
        request = Path(tmp) / 'request.json'
        request.write_text(json.dumps(payload), encoding='utf-8')
        done = subprocess.run([node, str(NODE_CHECK), str(request)], capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"node check failed ({done.returncode}): {done.stderr.strip()}")
    return json.loads(done.stdout)


def _compare(bundle: dict, path, case: dict, label: str) -> None:
    required = frozenset(case.get('required', ()))
    network = network_from_bundle(bundle)
    settings = Settings(frozenset({'Dortmund'}), frozenset({'Dortmund'}), 1, 24, case['maxFlights'], 3,
                        case['capMode'], required)
    counter = RouteCounter(network, settings)
    python_totals = counter.totals(path)
    python_shares = counter.city_shares(path)
    js = run_node(bundle, {'startCities': ['Dortmund'], 'returnCities': ['Dortmund'], 'minGapHours': 1,
                           'maxGapHours': 24, 'maxFlights': case['maxFlights'], 'dailyCap': 3,
                           'capMode': case['capMode'], 'requiredCities': sorted(required)}, path)
    where = (f"{label} {case['capMode']} max={case['maxFlights']} hops={len(path)} "
             f"required={sorted(required)}")
    assert js['oneWay'] == python_totals.one_way, f"{where}: one way js {js['oneWay']} != py {python_totals.one_way}"
    assert js['roundTrip'] == python_totals.round_trip, \
        f"{where}: round trip js {js['roundTrip']} != py {python_totals.round_trip}"
    assert len(js['cities']) == len(python_shares), \
        f"{where}: js lists {len(js['cities'])} cities, py {len(python_shares)}"
    for entry in js['cities']:
        reference = python_shares[entry['city']]
        assert entry['oneWay'] == reference['one_way'] and entry['roundTrip'] == reference['round_trip'], \
            f"{where}: counts differ for {entry['city']}"
        assert abs(entry['shareOneWay'] - reference['share_one_way']) < 1e-12, \
            f"{where}: one way share differs for {entry['city']}"
        assert abs(entry['shareRoundTrip'] - reference['share_round_trip']) < 1e-12, \
            f"{where}: round trip share differs for {entry['city']}"
        assert sorted(entry['flights']) == sorted(f.index for f in reference['flights']), \
            f"{where}: flight indices differ for {entry['city']}"
    assert js['exact'] is True, f"{where}: js reports counts beyond 2^53"


def test_js_matches_python_on_real_scan():
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('pkl'), 'test-pkl', 'test',
                                         build_mod.PROJECT_ROOT / 'data' / 'current' / 'graph.pkl')
    network = network_from_bundle(bundle)
    first_hop = [RouteCounter(network, Settings(frozenset({'Dortmund'}), frozenset({'Dortmund'}), 1, 24, None, 3,
                                                'calendar')).candidate_indices([])[0]]
    for case in CASES:
        _compare(bundle, [], case, 'pkl')
        _compare(bundle, first_hop, case, 'pkl')


def test_js_matches_python_across_midnight():
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.midnight_graph(), 'test-midnight', 'test',
                                         build_mod.PROJECT_ROOT / 'midnight')
    for case in CASES:
        _compare(bundle, [], case, 'midnight')


def test_js_radius_matches_python():
    """"One city plus a radius" must resolve to the same set of cities in both implementations."""
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('json'), 'test-json', 'test',
                                         build_mod.PROJECT_ROOT / 'data' / 'current' / 'flight_graph.json')
    names = [city['name'] for city in bundle['cities']]
    for center, radius in (('Frankfurt', 150.0), ('Frankfurt', 200.0), ('Dortmund', 0.0),
                           ('Dortmund', 300.0), ('Abu Dhabi', 400.0)):
        expected = coords.cities_within(center, radius, names)
        js = run_node(bundle, {'startCities': [center], 'returnCities': [center], 'minGapHours': 1,
                               'maxGapHours': 24, 'maxFlights': 2, 'dailyCap': 3, 'capMode': 'calendar'},
                      [], radius_center=center, radius=radius)
        got = [hit['city'] for hit in js['within']]
        assert got == expected, f"{center} +{radius} km: js {got} != py {expected}"
        for hit in js['within']:
            reference = coords.distance_km(center, hit['city'])
            assert abs(hit['km'] - reference) < 1e-6, f"{center} -> {hit['city']}: js {hit['km']} != py {reference}"
    assert coords.cities_within('Frankfurt', 150.0, names) == ['Frankfurt', 'Cologne', 'Karlsruhe/Baden-Baden'], \
        'the documented Frankfurt example must hold'


def test_node_is_available():
    """Reports whether the JavaScript checks above actually ran."""
    assert node_binary() is not None, ("node is not installed, so static/dp.js was not verified "
                                       "against explorer/dp.py in this run")
