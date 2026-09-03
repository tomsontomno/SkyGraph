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

from explorer import build as build_mod
from explorer.dp import FlightNetwork, RouteCounter, Settings, parse_label
from explorer.tests import fixtures
from explorer.tests.test_js import network_from_bundle, node_binary
from simulate import datasets
from simulate.routefmt import format_route_light

sys.setrecursionlimit(20000)

UI_SMOKE = Path(__file__).resolve().parent / 'ui_smoke.js'
START = 'Dortmund'


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


def _resolve_path(network: FlightNetwork, chosen: List[dict]) -> List[int]:
    """Turn the clicked rows (destination + labels) into flight indices."""
    path: List[int] = []
    city = START
    for pick in chosen:
        options = [f for f in network.flights
                   if f.origin == city and f.dest == pick['city']
                   and f.dep_label == pick['depLabel'] and f.arr_label == pick['arrLabel']]
        assert len(options) == 1, f"expected one flight {city} -> {pick['city']} {pick['depLabel']}, got {len(options)}"
        path.append(options[0].index)
        city = pick['city']
    return path


def test_ui_renders_and_navigates():
    if node_binary() is None:
        return
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('pkl'), 'test-pkl', 'test', datasets.GRAPH_PKL)
    result = _run_ui(bundle)
    assert not result['errors'], f"the page reported errors: {result['errors']}"
    assert result['mapKind'] == 'svg', 'without Leaflet the page must fall back to the SVG map'

    start = _step(result, 'start')
    assert start['breadcrumb'] == START
    assert start['backDisabled'] is True, 'Zurück must be disabled on the start city'
    assert start['cities'], 'no reachable cities listed at the start'
    assert start['svgNodes'] == 1, 'the map container must hold exactly the rendered map'

    hop1 = _step(result, 'after-hop1')
    hop2 = _step(result, 'after-hop2')
    assert hop1['backDisabled'] is False and hop2['backDisabled'] is False
    assert hop1['breadcrumb'] != start['breadcrumb'] and hop2['breadcrumb'] != hop1['breadcrumb']
    assert _step(result, 'after-back')['breadcrumb'] == hop1['breadcrumb'], 'Zurück must undo one hop'
    assert _step(result, 'after-reset')['breadcrumb'] == START, 'Zurücksetzen must return to the start'
    assert _step(result, 'after-svg-map')['cities'] == start['cities'], 'switching the map must keep the state'
    assert start['startResolved'].startswith('Dortmund allein'), start['startResolved']

    # a 200 km radius around Dortmund must pull in more start cities and more reachable cities
    radius = _step(result, 'after-radius')
    assert 'Umkreis von 200 km' in radius['startResolved'], radius['startResolved']
    assert '+' in radius['breadcrumb'], f"breadcrumb should name the extra start cities: {radius['breadcrumb']}"
    assert len(radius['cities']) > len(start['cities']), \
        f"radius should reach more cities: {len(radius['cities'])} vs {len(start['cities'])}"


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
    path = _resolve_path(network, result['chosen'])
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
    path = _resolve_path(network, result['chosen'])
    counter = RouteCounter(network, Settings(frozenset({START}), frozenset({START}), 1, 24, None, 3, 'calendar'))
    for hops, label in ((0, 'start'), (1, 'after-hop1'), (2, 'after-hop2')):
        totals = counter.totals(path[:hops])
        shares = counter.city_shares(path[:hops])
        text = _step(result, label)['totals']
        numbers = [int(n.replace('.', '')) for n in re.findall(r'([\d.]+) (?:One-way|Rundreisen|Städte)', text)]
        assert numbers == [round(totals.one_way), round(totals.round_trip), len(shares)], \
            f"{label}: UI shows {numbers}, DP says {[totals.one_way, totals.round_trip, len(shares)]}"
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
    counter = RouteCounter(network, Settings(frozenset({START}), frozenset({START}), 1, 24, None, 3,
                                             'calendar', frozenset({'Abu Dhabi'})))
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


def test_ui_smoke_needs_node():
    """Reports whether the UI checks above actually ran."""
    assert node_binary() is not None, 'node is not installed, so static/app.js was not executed in this run'
