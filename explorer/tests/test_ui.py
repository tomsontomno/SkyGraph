"""The page itself: static/app.js is driven headlessly under node against a DOM stub.

What the browser renders has to agree with the Python side: the breadcrumb must be the light format
of core/route_find.py (via simulate.routefmt) and the totals must be the DP counts for the same
route.  Without node the check reports itself as skipped.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from explorer import build as build_mod, coords
from explorer.dp import FlightNetwork, RouteCounter, Settings, parse_label
from explorer.tests import fixtures
from explorer.tests.test_js import network_from_bundle, node_binary
from simulate import datasets
from simulate.routefmt import format_route_light

sys.setrecursionlimit(20000)

UI_SMOKE = Path(__file__).resolve().parent / 'ui_smoke.js'
START = 'Dortmund'

# the defaults index.html ships with; test_ui_defaults_are_the_agreed_ones pins them there
DEFAULT_RADIUS_KM = 180.0
DEFAULT_MIN_GAP = 1.0
DEFAULT_MAX_GAP = 18.0
DEFAULT_DAILY_CAP = 3
DEFAULT_CAP_MODE = 'rolling24'


def default_settings(bundle: dict, required=frozenset()) -> Settings:
    """The Settings the page starts with, so Python and browser can be compared."""
    names = [city['name'] for city in bundle['cities']]
    within = frozenset(coords.cities_within(START, DEFAULT_RADIUS_KM, names))
    return Settings(within, within, DEFAULT_MIN_GAP, DEFAULT_MAX_GAP, None,
                    DEFAULT_DAILY_CAP, DEFAULT_CAP_MODE, frozenset(required))


def _run_ui(bundle: dict, archive_dir: Optional[Path] = None) -> dict:
    node = node_binary()
    if node is None:
        raise RuntimeError('node not available')
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / 'bundle.json'
        target.write_text(json.dumps(bundle), encoding='utf-8')
        command = [node, str(UI_SMOKE), str(target)]
        if archive_dir is not None:
            command.append(str(archive_dir))
        done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"the UI threw under node: {done.stderr.strip()[-800:]}")
    return json.loads(done.stdout)


def _step(result: dict, label: str) -> dict:
    matches = [s for s in result['steps'] if s.get('label') == label]
    assert matches, f"the UI never reached step {label!r}"
    return matches[0]


def _resolve_path(network: FlightNetwork, chosen: List[dict], origins=None) -> List[int]:
    """Turn the clicked rows (destination + labels) into flight indices.

    The first hop may leave from any start city, so ``origins`` (default: the radius set) is
    searched for it; every later hop must continue from the previous destination.
    """
    path: List[int] = []
    allowed = set(origins) if origins else {START}
    for pick in chosen:
        options = [f for f in network.flights
                   if f.origin in allowed and f.dest == pick['city']
                   and f.dep_label == pick['depLabel'] and f.arr_label == pick['arrLabel']]
        assert len(options) == 1, \
            f"expected one flight {sorted(allowed)} -> {pick['city']} {pick['depLabel']}, got {len(options)}"
        path.append(options[0].index)
        allowed = {pick['city']}
    return path


def test_ui_renders_and_navigates():
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('pkl'), 'test-pkl', 'test', datasets.GRAPH_PKL)
    result = _run_ui(bundle)
    assert not result['errors'], f"the page reported errors: {result['errors']}"
    assert result['mapKind'] == 'svg', 'without Leaflet the page must fall back to the SVG map'

    start = _step(result, 'start')
    assert start['breadcrumb'].startswith(START), start['breadcrumb']
    assert start['backDisabled'] is True, 'Zurück must be disabled on the start city'
    assert start['cities'], 'no reachable cities listed at the start'
    assert start['svgNodes'] == 1, 'the map container must hold exactly the rendered map'

    hop1 = _step(result, 'after-hop1')
    hop2 = _step(result, 'after-hop2')
    assert hop1['backDisabled'] is False and hop2['backDisabled'] is False
    assert hop1['breadcrumb'] != start['breadcrumb'] and hop2['breadcrumb'] != hop1['breadcrumb']
    assert _step(result, 'after-back')['breadcrumb'] == hop1['breadcrumb'], 'Zurück must undo one hop'
    assert _step(result, 'after-reset')['breadcrumb'] == start['breadcrumb'], \
        'Zurücksetzen must return to the start'
    assert _step(result, 'after-svg-map')['cities'] == start['cities'], 'switching the map must keep the state'
    assert f"Umkreis von {int(DEFAULT_RADIUS_KM)} km" in start['startResolved'], start['startResolved']

    # a wider radius must pull in more start cities and reach at least as many destinations
    radius = _step(result, 'after-radius')
    assert 'Umkreis von 400 km' in radius['startResolved'], radius['startResolved']
    assert '+' in radius['breadcrumb'], f"breadcrumb should name the extra start cities: {radius['breadcrumb']}"
    assert len(radius['cities']) >= len(start['cities']), \
        f"a wider radius must not lose cities: {len(radius['cities'])} vs {len(start['cities'])}"


def _iso_route(graph, network: FlightNetwork, path: List[int]) -> list:
    """The route in the ``(from, to, [dep_iso, arr_iso])`` shape route_find produces, with the
    original ISO strings taken straight from the scan."""
    lookup = {}
    for origin, dest, attrs in graph.edges(data=True):
        for dep_iso, arr_iso in attrs['flights']:
            lookup[(origin, dest, parse_label(dep_iso), parse_label(arr_iso))] = [dep_iso, arr_iso]
    route = []
    for index in path:
        flight = network.flights[index]
        key = (flight.origin, flight.dest, flight.dep_label, flight.arr_label)
        assert key in lookup, f"flight {key} is not in the scan"
        route.append((flight.origin, flight.dest, lookup[key]))
    return route


def test_ui_breadcrumb_is_the_light_format():
    if node_binary() is None:
        return
    graph = fixtures.real_graph('pkl')
    bundle = build_mod.bundle_from_graph(graph, 'test-pkl', 'test', datasets.GRAPH_PKL)
    result = _run_ui(bundle)
    network = network_from_bundle(bundle)
    path = _resolve_path(network, result['chosen'], default_settings(bundle).start_cities)
    assert len(path) == 2, 'the smoke test should have taken two hops'
    distances = datasets.load_distances()
    for hops in (1, 2):
        expected = format_route_light(_iso_route(graph, network, path[:hops]), distances)
        shown = _step(result, f'after-hop{hops}')['breadcrumb']
        assert shown == expected, f"breadcrumb after {hops} hops:\n  UI: {shown}\n  ref: {expected}"


def test_ui_totals_match_the_python_dp():
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('pkl'), 'test-pkl', 'test', datasets.GRAPH_PKL)
    result = _run_ui(bundle)
    network = network_from_bundle(bundle)
    settings = default_settings(bundle)
    path = _resolve_path(network, result['chosen'], settings.start_cities)
    counter = RouteCounter(network, settings)
    for hops, label in ((0, 'start'), (1, 'after-hop1'), (2, 'after-hop2')):
        totals = counter.totals(path[:hops])
        shares = counter.city_shares(path[:hops])
        # the page starts in round-trip mode, where cities without a way home are hidden
        visible = sum(1 for entry in shares.values() if entry['round_trip'] > 0)
        text = _step(result, label)['totals']
        numbers = [int(n.replace('.', '')) for n in re.findall(r'([\d.]+) (?:One-way|Rundreisen|Städte)', text)]
        assert numbers == [round(totals.one_way), round(totals.round_trip), visible], \
            f"{label}: UI shows {numbers}, DP says {[totals.one_way, totals.round_trip, visible]}"
    tooltip = result['tooltip']
    assert 'Anteil Rundreise' in tooltip and 'Anteil One-way' in tooltip and 'offene Rückwege' in tooltip \
        and 'neues Land' in tooltip and 'Flüge' in tooltip, f"tooltip is missing fields: {tooltip}"


def test_ui_required_cities_filter_and_chip_removal():
    """Adding a Pflichtstadt must shrink the counts and the chip's × must undo it exactly."""
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('json'), 'test-json', 'test',
                                         datasets.FLIGHT_GRAPH_JSON)
    result = _run_ui(bundle)
    assert not result['errors'], result['errors']
    before = _step(result, 'before-required')
    after = _step(result, 'with-required')
    removed = _step(result, 'after-required-removed')

    assert any('Abu Dhabi' in chip for chip in after['chips']), after['chips']

    def numbers(step):
        return [int(n.replace('.', '')) for n in re.findall(r'([\d.]+) (?:One-way|Rundreisen|Städte)',
                                                            step['totals'])]

    plain, filtered = numbers(before), numbers(after)
    assert filtered[0] < plain[0], f"Pflichtstadt must reduce the one-way count: {plain} -> {filtered}"
    assert filtered[0] > 0, 'Abu Dhabi must still be reachable in the October scan'
    assert numbers(removed) == plain, f"removing the chip must restore the counts: {numbers(removed)} != {plain}"

    # the Python DP must agree with what the page showed
    network = network_from_bundle(bundle)
    counter = RouteCounter(network, default_settings(bundle, {'Abu Dhabi'}))
    totals = counter.totals([])
    assert filtered[0] == round(totals.one_way), f"UI {filtered[0]} != DP {totals.one_way}"


def test_ui_archive_slider_assembles_windows():
    """Selecting the archive must build a window from the day files and react to the slider."""
    from explorer import archive

    if node_binary() is None or not archive.ARCHIVE_DIR.is_dir():
        return
    index = archive.load_days()
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('pkl'), 'test-pkl', 'test', datasets.GRAPH_PKL)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        manifest = build_mod.build_archive_day_bundles(index, out)
        result = _run_ui(bundle, out)
    assert not result['errors'], result['errors']
    assert result['archiveOffered'] is True, 'the archive must appear in the scan list'

    window = _step(result, 'archive-window')
    assert window['barHidden'] is False, 'the date slider must appear for the archive'
    assert ' Flüge · ' in window['archiveLabel'], window['archiveLabel']
    assert window['cities'], 'the assembled window must reach cities'
    assert window['breadcrumb'] == START

    # the same window through the original code must be a subset, so never more reachable cities
    original = _step(result, 'archive-original')
    assert len(original['cities']) <= len(window['cities']), \
        f"original view reaches more cities than the fix: {original['cities']} vs {window['cities']}"

    # moving the slider to the first day must load a different window
    first = _step(result, 'archive-first-day')
    assert first['archiveLabel'].startswith(manifest['days'][0]['date']), first['archiveLabel']
    assert first['archiveLabel'] != window['archiveLabel']


def test_ui_defaults_are_the_agreed_ones():
    """The page must open with Dortmund + 180 km, gaps 1 to 18 h, rolling24 and new countries on."""
    html = (build_mod.STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    expected = [
        ('id="start-radius"', 'value="180"'),
        ('id="return-radius"', 'value="180"'),
        ('id="min-gap"', 'value="1"'),
        ('id="max-gap"', 'value="18"'),
        ('id="daily-cap"', 'value="3"'),
    ]
    for element, value in expected:
        line = next((l for l in html.splitlines() if element in l), None)
        assert line is not None, f"{element} missing from index.html"
        assert value in line, f"{element} should default to {value}: {line.strip()}"
    assert '<option value="rolling24" selected>' in html, 'rolling24 must be the preselected cap mode'
    assert 'id="highlight-new" checked' in html, 'new countries must be highlighted by default'
    assert 'name="mode" value="rt" checked' in html, 'round trip must be the default mode'
    # the smoke test's stub has to mirror those defaults or its results mean nothing
    stub = (Path(__file__).resolve().parent / 'ui_smoke.js').read_text(encoding='utf-8')
    for key, value in (("'max-gap'", "'18'"), ("'cap-mode'", "'rolling24'"),
                       ("'start-radius'", "'180'"), ("'return-radius'", "'180'")):
        assert f"{key}: {value}" in stub, f"ui_smoke.js default for {key} is out of sync"


def test_ui_round_trip_hides_cities_without_a_way_home():
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('json'), 'test-json', 'test',
                                         datasets.FLIGHT_GRAPH_JSON)
    result = _run_ui(bundle)
    assert not result['errors'], result['errors']
    round_trip = _step(result, 'round-trip')
    one_way = _step(result, 'one-way')

    assert len(one_way['cities']) > len(round_trip['cities']), \
        f"one way must show more cities: {len(one_way['cities'])} vs {len(round_trip['cities'])}"
    assert set(round_trip['cities']) <= set(one_way['cities']), 'round trip cities must be a subset'
    assert 'ohne Rückweg sind ausgeblendet' in round_trip['hint'], round_trip['hint']

    # every city the round-trip view still shows must really have a way home, per the Python DP
    network = network_from_bundle(bundle)
    counter = RouteCounter(network, default_settings(bundle))
    shares = counter.city_shares([])
    with_way_home = {name for name, entry in shares.items() if entry['round_trip'] > 0}
    assert set(round_trip['cities']) == with_way_home, \
        f"UI shows {sorted(round_trip['cities'])}, DP says {sorted(with_way_home)}"


def test_ui_smoke_needs_node():
    """Reports whether the UI checks above actually ran."""
    assert node_binary() is not None, 'node is not installed, so static/app.js was not executed in this run'
