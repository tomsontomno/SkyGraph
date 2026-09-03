"""Behavioural checks: search nesting, depth-cap equivalence, booking cap, generator invariants, formatting."""
from __future__ import annotations

import contextlib
import io
from datetime import datetime, date

from simulate import analyze, booking_cap, datasets, synth
from simulate import route_find_fixed, route_find_original
from simulate.routefmt import format_route_light

SMALL = synth.SynthParams(n_spokes=20, target_edges=110)


def _graph(seed: int = 0, params: synth.SynthParams = None):
    return synth.to_graph(synth.generate_network(seed, params or synth.SynthParams(), None))


def _params(max_flights):
    return analyze.SearchParams(start='Dortmund', max_flights=max_flights, flex_km=0, transfer_speed_kmh=50,
                                distances_file=datasets.DISTANCES_FILE)


def test_original_routes_are_subset_of_fixed():
    graph = _graph(0)
    for scenario in (analyze.Scenario('rt', 1, 24), analyze.Scenario('ow', 1, 24)):
        orig = {analyze.route_key(r) for r in analyze.run_search(route_find_original, graph, scenario, _params(4))}
        fixed = {analyze.route_key(r) for r in analyze.run_search(route_find_fixed, graph, scenario, _params(4))}
        assert orig <= fixed, f"{scenario.key}: {len(orig - fixed)} original routes missing in fixed"
        assert len(fixed) > len(orig), f"{scenario.key}: fix finds nothing new on synth seed 0"


def test_depth_cap_equals_post_filter():
    graph = _graph(0, SMALL)
    scenario = analyze.Scenario('ow', 1, 24)
    for module in (route_find_original, route_find_fixed):
        uncapped = module.find_one_way_routes(graph, ['Dortmund'], set(graph.nodes), 1, 24, flex_km=0,
                                              distances_file=datasets.DISTANCES_FILE, max_flights=None)
        filtered = module.filter_routes_by_flights(uncapped, max_flights=3)
        capped = analyze.run_search(module, graph, scenario, _params(3))
        assert [analyze.route_key(r) for r in filtered] == [analyze.route_key(r) for r in capped], \
            f"{module.__name__}: depth cap is not equivalent to filter_routes_by_flights"
        assert len(uncapped) > len(capped), "test graph too small: cap never triggered"


def test_missed_routes_contain_invisible_flight_and_positions_are_right():
    graph = _graph(2)
    scenario = analyze.Scenario('ow', 1, 24)
    stats = synth.network_stats(graph)
    day0 = date.fromisoformat(stats['day0'])
    orig = analyze.prepare(analyze.run_search(route_find_original, graph, scenario, _params(4)), day0, {}, {})
    fixed = analyze.prepare(analyze.run_search(route_find_fixed, graph, scenario, _params(4)), day0, {}, {})
    comparison = analyze.compare(graph, orig, fixed, day0=day0, n_days=4, max_flights=4,
                                 invisible_share=stats['invisible_share'], cap=3, cap_mode='none',
                                 distances={}, city_data={})
    s = comparison.stats
    assert s['n_orig_not_in_fixed'] == 0
    assert s['n_missed'] == s['n_fixed'] - s['n_orig']
    assert s['missed_class']['with_invisible'] == s['missed_class']['n'] > 0
    visible = analyze.first_flights(graph)
    for route, info in zip(comparison.missed_routes, comparison.missed_info):
        positions = [i + 1 for i, leg in enumerate(route) if not analyze.leg_visible(leg, visible)]
        assert positions == info['invisible_positions']
        assert info['later_day_legs'] + info['same_day_legs'] + info['earlier_legs'] == len(positions)
    assert s['missed_class']['earlier_any'] == 0, "flights are sorted per edge, so no invisible flight is earlier"
    assert all(v['orig'] + v['missed'] == v['fixed'] for v in s['by_flights'].values())
    assert sum(v['fixed'] for v in s['by_day'].values()) == s['n_fixed']


def test_booking_cap_calendar_and_rolling24():
    def leg(dep, arr='2025-03-14T23:00:00+01:00'):
        return ('A', 'B', [dep, arr])

    three_same_day = [leg('2025-03-13T06:00:00+01:00'), leg('2025-03-13T12:00:00+01:00'), leg('2025-03-13T20:00:00+01:00')]
    assert booking_cap.passes_daily_cap(three_same_day, 3, 'calendar')
    assert booking_cap.passes_daily_cap(three_same_day, 3, 'rolling24')
    four_same_day = three_same_day + [leg('2025-03-13T22:00:00+01:00')]
    assert not booking_cap.passes_daily_cap(four_same_day, 3, 'calendar')
    assert not booking_cap.passes_daily_cap(four_same_day, 3, 'rolling24')
    # four departures on two calendar days but inside 24 h (offsets matter: 01:00+02:00 == 00:00+01:00)
    across_midnight = [leg('2025-03-13T10:00:00+01:00'), leg('2025-03-13T16:00:00+01:00'),
                       leg('2025-03-13T22:00:00+01:00'), leg('2025-03-14T01:00:00+02:00')]
    assert booking_cap.passes_daily_cap(across_midnight, 3, 'calendar')
    assert not booking_cap.passes_daily_cap(across_midnight, 3, 'rolling24')
    # exactly 24 h between first and fourth departure -> allowed in rolling24
    exactly_24h = [leg('2025-03-13T10:00:00+01:00'), leg('2025-03-13T16:00:00+01:00'),
                   leg('2025-03-13T22:00:00+01:00'), leg('2025-03-14T11:00:00+02:00')]
    assert booking_cap.passes_daily_cap(exactly_24h, 3, 'rolling24')
    assert booking_cap.filter_daily_cap([four_same_day, three_same_day], 3, 'none') == [four_same_day, three_same_day]
    try:
        booking_cap.passes_daily_cap(three_same_day, 3, 'weekly')
    except ValueError:
        pass
    else:
        raise AssertionError("unknown cap mode must raise")


def test_synth_invariants_and_sizes():
    for seed in range(3):
        params = synth.SynthParams()
        data = synth.generate_network(seed, params, None)
        assert data == synth.generate_network(seed, params, None), "generator is not reproducible"
        graph = synth.to_graph(data)
        stats = synth.network_stats(graph, params.hub_weights)
        assert stats['n_cities'] == len(params.hub_weights) + params.n_spokes, stats['n_cities']
        assert 800 <= stats['n_edges'] <= 900, stats['n_edges']
        assert 1000 <= stats['n_flights'] <= 1600, stats['n_flights']
        assert stats['day0'] == params.base_date, stats['day0']
        assert len(stats['flights_by_day']) == params.n_days, stats['flights_by_day']
        assert stats['visible_share_by_day'][0] == 1.0, stats['visible_share_by_day']
        assert stats['hub_weight_spearman'] > 0.7, stats['hub_weight_spearman']
        for a, b, attrs in graph.edges(data=True):
            assert a != b, f"self loop {a}"
            flights = attrs['flights']
            deps = [datetime.fromisoformat(f[0]) for f in flights]
            assert deps == sorted(deps), f"{a}->{b} flights not sorted"
            assert len(set(f[0] for f in flights)) == len(flights), f"{a}->{b} duplicate departures"
            for dep_iso, arr_iso in flights:
                dep, arr = datetime.fromisoformat(dep_iso), datetime.fromisoformat(arr_iso)
                assert (5, 30) <= (dep.hour, dep.minute) <= (22, 30), dep_iso
                hours = (arr - dep).total_seconds() / 3600
                lo, hi = (4.0, 7.0) if (a in synth.LONG_HAUL_CITIES or b in synth.LONG_HAUL_CITIES) else (1.0, 5.5)
                assert lo <= hours <= hi, (a, b, dep_iso, arr_iso)
                assert dep_iso.endswith(synth.OFFSETS.get(a, synth.DEFAULT_OFFSET))
                assert arr_iso.endswith(synth.OFFSETS.get(b, synth.DEFAULT_OFFSET))


def test_light_format_matches_print_routes():
    graph = _graph(0, SMALL)
    routes = analyze.run_search(route_find_fixed, graph, analyze.Scenario('ow', 1, 24), _params(3))[:40]
    assert routes, "no routes to format"
    distances = datasets.load_distances()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        route_find_original.print_routes(routes, "light", distances_file=datasets.DISTANCES_FILE)
    printed = [line for line in buffer.getvalue().splitlines() if line and 'ROUTES FOUND' not in line]
    assert printed == [format_route_light(r, distances) for r in routes]
