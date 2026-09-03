"""Coordinates, bundle integrity and the static assets the server ships."""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from explorer import build as build_mod, coords, server
from explorer.dp import FlightNetwork
from explorer.tests import fixtures
from simulate import datasets


def test_every_scanned_city_has_coordinates():
    for which, path in (('pkl', datasets.GRAPH_PKL), ('json', datasets.FLIGHT_GRAPH_JSON)):
        graph = fixtures.real_graph(which)
        unknown = coords.missing(graph.nodes)
        assert not unknown, f"{path}: no coordinates for {unknown}"


def test_coordinates_are_plausible():
    for city, (lat, lon) in coords.CITY_COORDS.items():
        assert -90 <= lat <= 90 and -180 <= lon <= 180, f"{city}: {lat}/{lon} is off the globe"
    # the scans cover Europe, North Africa, the Middle East, the Gulf, Central Asia and the Maldives
    for city in ('Dortmund', 'Budapest', 'Abu Dhabi', 'Reykjavik', 'Male', 'Tenerife'):
        lat, lon = coords.coords_of(city)
        assert -30 <= lat <= 75 and -30 <= lon <= 80, f"{city}: {lat}/{lon} outside the scanned region"
    known = {'Dortmund': (51.5, 7.6), 'Budapest': (47.4, 19.3), 'Abu Dhabi': (24.4, 54.7),
             'Reykjavik': (64.0, -22.6), 'Larnaca': (34.9, 33.6)}
    for city, (lat, lon) in known.items():
        have = coords.coords_of(city)
        assert abs(have[0] - lat) < 0.5 and abs(have[1] - lon) < 0.5, f"{city} sits at {have}, expected {lat}/{lon}"


def test_duplicate_spellings_share_a_location():
    pairs = [('Warsaw', 'Warsaw Chopin'), ('Tel Aviv', 'Tel-Aviv'), ('Oslo', 'Oslo Gardermoen'),
             ('Oslo Sandefjord', 'Oslo Sandefjord Torp'), ('Sevilla', 'Seville'),
             ('Marrakech', 'Marrakesh'), ('Medina', 'Madinah'), ('Pristina', 'Prishtina'),
             ('Funchal', 'Funchal (Madeira)'), ('Tirgu Mures', 'Tirgu-Mures')]
    for a, b in pairs:
        assert coords.coords_of(a) == coords.coords_of(b), f"{a} and {b} are the same airport"


def test_bundle_is_consistent_with_the_scan():
    graph = fixtures.real_graph('pkl')
    bundle = build_mod.bundle_from_graph(graph, 'test-name', 'test-label', datasets.GRAPH_PKL)
    network = FlightNetwork.from_graph(graph)
    names = [city['name'] for city in bundle['cities']]

    assert bundle['scan'] == 'test-name' and bundle['label'] == 'test-label', \
        "the bundle must carry the name it was built with"
    assert len(bundle['flights']) == len(network.flights) == bundle['stats']['flights']
    assert names == sorted(names), "cities must be sorted so indices are stable"
    assert bundle['defaultStart'] in names

    departures = [row[2] for row in bundle['flights']]
    assert departures == sorted(departures), "flights must be sorted by departure"

    for row, flight in zip(bundle['flights'], network.flights):
        assert names[row[0]] == flight.origin and names[row[1]] == flight.dest
        assert row[2] == int(flight.dep) and row[3] == int(flight.arr)
        assert bundle['days'][row[4]] == flight.dep_day, "day index must point at the local departure date"
        assert row[5] == flight.dep_label and row[6] == flight.arr_label
        assert row[3] > row[2], "a flight cannot arrive before it departs"

    # labels carry local time: the day/month in the label must be the local departure date, which for
    # a flight leaving late in an eastern timezone differs from the UTC date
    for flight in network.flights:
        local = date.fromisoformat(flight.dep_day)
        assert flight.dep_label[4:9] == f"{local:%d/%m}", \
            f"label {flight.dep_label!r} does not match local departure date {flight.dep_day}"


def test_bundle_marks_new_countries():
    bundle = build_mod.bundle_from_graph(fixtures.real_graph('pkl'), 'test', 'test', datasets.GRAPH_PKL)
    by_name = {city['name']: city for city in bundle['cities']}
    assert by_name['Istanbul']['countryNew'] is True, "Türkiye is not visited in preferences.json"
    assert by_name['Budapest']['countryNew'] is False, "Magyarország is visited in preferences.json"
    unknown = [c['name'] for c in bundle['cities'] if c['countryNew'] is None]
    assert 'Dortmund' not in unknown
    assert all(isinstance(c['lat'], float) and isinstance(c['lon'], float) for c in bundle['cities'])


def test_build_all_writes_one_file_per_variant():
    """Each scan yields a Fix bundle and an -original bundle, in distinct files."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        built = build_mod.build_all([datasets.GRAPH_PKL], out, with_original=True)
        assert len(built) == 2, f"expected two variants, got {[b['scan'] for b in built]}"
        names = [b['scan'] for b in built]
        assert names == ['pkl-2025-03', 'pkl-2025-03-original'], names
        paths = {b['path'] for b in built}
        assert len(paths) == 2, 'the two variants must not overwrite each other'
        for info in built:
            assert Path(info['path']).is_file()
        fixed, original = built
        assert fixed['stats']['flights'] > original['stats']['flights']
        assert original['stats']['flights'] == original['stats']['edges'], \
            'the original view keeps exactly one flight per route'
        assert (out / 'index.json').is_file()
        listed = [scan['scan'] for scan in json.loads((out / 'index.json').read_text(encoding='utf-8'))['scans']]
        assert listed == names


def test_missing_coordinates_are_reported():
    graph = fixtures.graph_from([('Dortmund', 'Atlantis', '2025-03-13T08:00:00+01:00',
                                 '2025-03-13T10:00:00+01:00')])
    try:
        build_mod.bundle_from_graph(graph, 'test', 'test', Path('fixture'))
    except build_mod.MissingCoordinates as exc:
        assert exc.cities == ['Atlantis'] and 'Atlantis' in str(exc)
    else:
        raise AssertionError("a city without coordinates must abort the build")


def test_static_assets_exist():
    for name in ('index.html', 'style.css', 'app.js', 'dp.js', 'map.js'):
        path = server.STATIC_DIR / name
        assert path.is_file() and path.stat().st_size > 0, f"missing static asset {name}"
    html = (server.STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    for script in ('dp.js', 'map.js', 'app.js'):
        assert script in html, f"index.html does not load {script}"


def test_export_site_is_self_contained():
    """The exported folder must run on a plain static host: assets, bundles, no server code."""
    with tempfile.TemporaryDirectory() as tmp:
        bundles = Path(tmp) / 'bundles-src'
        built = build_mod.build_all([datasets.GRAPH_PKL], bundles, with_original=True)
        site = Path(tmp) / 'site'
        info = build_mod.export_site(site, bundles)

        for name in ('index.html', 'style.css', 'app.js', 'dp.js', 'map.js', 'vercel.json'):
            assert (site / name).is_file(), f"{name} missing from the export"
        for entry in built:
            assert (site / 'bundles' / Path(entry['path']).name).is_file()
        assert (site / 'bundles' / 'index.json').is_file()
        assert info['bytes'] > 0 and len(info['bundles']) == len(built) + 1

        html = (site / 'index.html').read_text(encoding='utf-8')
        assert 'name="viewport"' in html, 'the page must declare a viewport for phones'
        css = (site / 'style.css').read_text(encoding='utf-8')
        assert '@media (max-width: 900px)' in css, 'the mobile layout must ship with the export'
        config = json.loads((site / 'vercel.json').read_text(encoding='utf-8'))
        assert config['cleanUrls'] is True and config['headers']

        # a second export into the same folder must not leave stale bundles behind
        again = build_mod.export_site(site, bundles)
        assert sorted(again['bundles']) == sorted(info['bundles'])


def test_server_path_translation_stays_inside_its_roots():
    handler = type('Bound', (server.ExplorerHandler,),
                   {'static_dir': server.STATIC_DIR, 'bundle_dir': build_mod.BUNDLE_DIR})
    translate = handler.translate_path
    fake = object.__new__(handler)
    assert translate(fake, '/') == str(server.STATIC_DIR / 'index.html')
    assert translate(fake, '/app.js') == str(server.STATIC_DIR / 'app.js')
    assert translate(fake, '/bundles/pkl-2025-03.json') == str(build_mod.BUNDLE_DIR / 'pkl-2025-03.json')
    for attack in ('/../../etc/passwd', '/bundles/../../etc/passwd', '/..%2f..%2fetc/passwd'):
        resolved = Path(translate(fake, attack)).resolve()
        assert resolved.is_relative_to(server.STATIC_DIR.resolve()) or \
               resolved.is_relative_to(build_mod.BUNDLE_DIR.resolve()), f"{attack} escaped to {resolved}"
