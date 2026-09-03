"""The DP must count exactly what simulate/route_find_fixed.py enumerates.

``simulate.route_find_fixed`` + ``simulate.booking_cap`` are the reference: the DFS enumerates every
route, the filter applies the booking rule.  The DP must reproduce those counts for every mode, gap
window, flight limit and cap mode - that is what makes "count instead of enumerate" trustworthy.
"""
from __future__ import annotations

import sys

from explorer.dp import FlightNetwork, RouteCounter, Settings, cap_advance, cap_state_of
from explorer.tests import fixtures
from simulate import booking_cap, datasets, route_find_fixed

sys.setrecursionlimit(20000)

START = 'Dortmund'
RETURN_CITIES = frozenset({START})


def _enumerate(graph, mode, min_gap, max_gap, max_flights, cap, cap_mode):
    """Reference count: enumerate with the fixed search, then apply the booking cap."""
    ends = set(RETURN_CITIES) if mode == 'rt' else set(graph.nodes)
    routes = route_find_fixed.find_one_way_routes(
        graph, [START], ends, min_gap, max_gap, flex_km=0,
        distances_file=datasets.DISTANCES_FILE, max_flights=max_flights)
    return len(booking_cap.filter_daily_cap(routes, cap, cap_mode))


def _counter(graph, min_gap, max_gap, max_flights, cap, cap_mode, required=frozenset(), groups=()):
    settings = Settings(frozenset({START}), RETURN_CITIES, min_gap, max_gap, max_flights, cap, cap_mode,
                        frozenset(required), tuple(frozenset(g) for g in groups))
    return RouteCounter(FlightNetwork.from_graph(graph), settings)


def _cities_of(route) -> set:
    return {route[0][0]} | {leg[1] for leg in route}


def _check_against_enumeration(graph, cases, label):
    for min_gap, max_gap, max_flights, cap, cap_mode in cases:
        totals = _counter(graph, min_gap, max_gap, max_flights, cap, cap_mode).totals()
        expected_ow = _enumerate(graph, 'ow', min_gap, max_gap, max_flights, cap, cap_mode)
        expected_rt = _enumerate(graph, 'rt', min_gap, max_gap, max_flights, cap, cap_mode)
        where = f"{label} gap {min_gap}-{max_gap} max {max_flights} cap {cap} {cap_mode}"
        assert totals.one_way == expected_ow, f"{where}: one way DP {totals.one_way} != enum {expected_ow}"
        assert totals.round_trip == expected_rt, f"{where}: round trip DP {totals.round_trip} != enum {expected_rt}"


def test_dp_matches_enumeration_on_synth_net():
    graph = fixtures.small_synth_graph(0)
    cases = [(mn, mx, mf, 3, mode)
             for mn, mx in ((1, 12), (1, 24))
             for mf in (2, 3, 4)
             for mode in ('none', 'calendar', 'rolling24')]
    _check_against_enumeration(graph, cases, 'synth-0')


def test_dp_matches_enumeration_on_real_scan():
    graph = fixtures.real_graph('pkl')
    cases = [(1, 24, 4, 3, 'none'), (1, 24, 4, 3, 'calendar'), (1, 24, 4, 3, 'rolling24'),
             (1, 24, 5, 3, 'calendar'), (1, 24, 5, 3, 'rolling24'),
             (2, 30, 4, 3, 'rolling24'), (1, 24, 5, 2, 'calendar'), (1, 24, 4, 1, 'rolling24')]
    _check_against_enumeration(graph, cases, 'pkl')


def test_dp_matches_enumeration_without_flight_limit():
    """Without a limit the DFS still terminates on this small net, so the two can be compared."""
    graph = fixtures.small_synth_graph(0)
    _check_against_enumeration(graph, [(1, 24, None, 3, 'none'), (1, 24, None, 3, 'calendar'),
                                       (1, 24, None, 3, 'rolling24')], 'synth-0 unlimited')


def test_first_flight_view_equals_the_original_search():
    """The "-original" bundle must show exactly what core/route_find.py found.

    ``graph[a][b].values()`` hands the buggy search the whole flights list as one value, so it only
    ever uses ``flights[0]``.  Counting on the graph reduced to those first flights must therefore
    equal enumerating with the unfixed search on the full graph.
    """
    from explorer.build import reduce_to_first_flight
    from simulate import route_find_original

    for which in ('pkl', 'json'):
        graph = fixtures.real_graph(which)
        reduced = reduce_to_first_flight(graph)
        assert reduced.number_of_edges() == graph.number_of_edges()
        assert sum(len(a['flights']) for _, _, a in reduced.edges(data=True)) == reduced.number_of_edges()
        for max_flights in (3, 5):
            for cap_mode in ('none', 'calendar', 'rolling24'):
                counted = _counter(reduced, 1, 24, max_flights, 3, cap_mode).totals()
                for mode, expected_attr in (('ow', 'one_way'), ('rt', 'round_trip')):
                    ends = set(RETURN_CITIES) if mode == 'rt' else set(graph.nodes)
                    routes = route_find_original.find_one_way_routes(
                        graph, [START], ends, 1, 24, flex_km=0,
                        distances_file=datasets.DISTANCES_FILE, max_flights=max_flights)
                    expected = len(booking_cap.filter_daily_cap(routes, 3, cap_mode))
                    got = getattr(counted, expected_attr)
                    assert got == expected, (f"{which} {mode} max {max_flights} {cap_mode}: "
                                             f"first-flight view {got} != original search {expected}")


def test_required_cities_match_enumeration():
    """Pflichtstädte: only routes touching every required city may be counted."""
    graph = fixtures.real_graph('json')
    cases = [
        (frozenset({'Istanbul'}), 5, 'none'),
        (frozenset({'Abu Dhabi'}), 5, 'calendar'),
        (frozenset({'Budapest', 'Abu Dhabi'}), 5, 'calendar'),
        (frozenset({'Istanbul', 'Male'}), 6, 'none'),
        (frozenset({'Dortmund'}), 4, 'calendar'),                      # the start itself, trivially met
        (frozenset({'Reykjavik', 'Male', 'Cairo'}), 5, 'none'),        # impossible together
    ]
    for required, max_flights, cap_mode in cases:
        for mode in ('ow', 'rt'):
            ends = set(RETURN_CITIES) if mode == 'rt' else set(graph.nodes)
            routes = route_find_fixed.find_one_way_routes(
                graph, [START], ends, 1, 24, flex_km=0,
                distances_file=datasets.DISTANCES_FILE, max_flights=max_flights)
            capped = booking_cap.filter_daily_cap(routes, 3, cap_mode)
            expected = sum(1 for route in capped if required <= _cities_of(route))
            totals = _counter(graph, 1, 24, max_flights, 3, cap_mode, required).totals()
            got = totals.one_way if mode == 'ow' else totals.round_trip
            assert got == expected, (f"{sorted(required)} max {max_flights} {cap_mode} {mode}: "
                                     f"DP {got} != enum {expected}")


def test_required_country_is_any_of_its_airports():
    """A required country counts as visited as soon as any one of its airports is on the route."""
    graph = fixtures.real_graph('json')
    turkey = ['Istanbul', 'Antalya', 'Dalaman']
    assert all(city in graph for city in turkey)

    country = _counter(graph, 1, 24, 5, 3, 'calendar', groups=(turkey,)).totals()
    singles = {city: _counter(graph, 1, 24, 5, 3, 'calendar', frozenset({city})).totals().one_way
               for city in turkey}
    plain = _counter(graph, 1, 24, 5, 3, 'calendar').totals()

    # the union is at least as permissive as any single airport, and never more than everything
    assert country.one_way >= max(singles.values()), (country.one_way, singles)
    assert country.one_way <= plain.one_way

    # and it is exactly the routes that touch at least one of the three
    routes = booking_cap.filter_daily_cap(
        route_find_fixed.find_one_way_routes(graph, [START], set(graph.nodes), 1, 24, flex_km=0,
                                             distances_file=datasets.DISTANCES_FILE, max_flights=5),
        3, 'calendar')
    expected = sum(1 for route in routes if _cities_of(route) & set(turkey))
    assert country.one_way == expected, f"country DP {country.one_way} != enum {expected}"

    # a country nobody flies to can never be satisfied
    assert _counter(graph, 1, 24, 5, 3, 'calendar', groups=(['Atlantis', 'El Dorado'],)).totals().one_way == 0


def test_required_city_and_its_country_are_the_same_requirement():
    """Requiring a country plus one of its cities must equal requiring that city alone."""
    graph = fixtures.real_graph('json')
    only_city = _counter(graph, 1, 24, 5, 3, 'calendar', frozenset({'Istanbul'})).totals()
    both = _counter(graph, 1, 24, 5, 3, 'calendar', frozenset({'Istanbul'}),
                    groups=(['Istanbul', 'Antalya', 'Dalaman'],)).totals()
    assert both.one_way == only_city.one_way, (both, only_city)
    assert both.round_trip == only_city.round_trip


def test_required_cities_only_shrink_the_result():
    """Adding a required city can never add routes, and an unreachable one empties the result."""
    graph = fixtures.real_graph('json')
    plain = _counter(graph, 1, 24, 5, 3, 'calendar').totals()
    one = _counter(graph, 1, 24, 5, 3, 'calendar', frozenset({'Abu Dhabi'})).totals()
    two = _counter(graph, 1, 24, 5, 3, 'calendar', frozenset({'Abu Dhabi', 'Male'})).totals()
    assert plain.one_way > one.one_way > 0, (plain.one_way, one.one_way)
    assert one.one_way >= two.one_way, (one.one_way, two.one_way)
    # a city that is not in the scan at all can never be visited
    assert _counter(graph, 1, 24, 5, 3, 'calendar', frozenset({'Atlantis'})).totals().one_way == 0


def test_required_cities_shares_still_sum_to_one():
    graph = fixtures.real_graph('json')
    counter = _counter(graph, 1, 24, 6, 3, 'calendar', frozenset({'Abu Dhabi'}))
    shares = counter.city_shares([])
    totals = counter.totals()
    assert totals.one_way > 0
    assert abs(sum(entry['share_one_way'] for entry in shares.values()) - 1.0) < 1e-9
    # cities from which Abu Dhabi can no longer be reached must carry zero weight
    zero = [name for name, entry in shares.items() if entry['one_way'] == 0]
    assert zero, 'with a required city some first hops must become dead ends'


def test_shares_sum_to_one_per_hop():
    graph = fixtures.real_graph('pkl')
    for cap_mode in ('none', 'calendar', 'rolling24'):
        counter = _counter(graph, 1, 24, None, 3, cap_mode)
        path = []
        for _ in range(4):
            shares = counter.city_shares(path)
            if not shares:
                break
            totals = counter.totals(path)
            for field, total in (('share_one_way', totals.one_way), ('share_round_trip', totals.round_trip)):
                summed = sum(entry[field] for entry in shares.values())
                expected = 1.0 if total > 0 else 0.0
                assert abs(summed - expected) < 1e-9, \
                    f"{cap_mode} hop {len(path)}: {field} sums to {summed}, expected {expected}"
            # per city the flight counts must add up to the city's count
            for entry in shares.values():
                per_flight = sum(counter.value(f.index,
                                               cap_advance(cap_state_of([counter.network.flights[i] for i in path], 3, cap_mode),
                                                           f, 3, cap_mode),
                                               None).one_way
                                 for f in entry['flights'])
                assert abs(per_flight - entry['one_way']) < 1e-6, \
                    f"{cap_mode}: flights of {entry['city']} sum to {per_flight}, city says {entry['one_way']}"
            path = path + [counter.hops(path)[0].flight.index]


def test_totals_equal_sum_over_next_hops():
    graph = fixtures.small_synth_graph(1)
    counter = _counter(graph, 1, 24, None, 3, 'calendar')
    hops = counter.hops([])
    totals = counter.totals()
    assert abs(sum(h.counts.one_way for h in hops) - totals.one_way) < 1e-9
    assert abs(sum(h.counts.round_trip for h in hops) - totals.round_trip) < 1e-9


def test_timezones_across_midnight():
    """Local calendar days and absolute 24 h windows must disagree exactly where they should."""
    graph = fixtures.midnight_graph()
    # the loop exists at all
    assert _counter(graph, 1, 24, None, 3, 'none').totals().round_trip == 1
    # four departures inside ten hours -> rolling24 with cap 3 kills it, calendar keeps it
    assert _counter(graph, 1, 24, None, 3, 'calendar').totals().round_trip == 1
    assert _counter(graph, 1, 24, None, 3, 'rolling24').totals().round_trip == 0
    # three of the four departures are on the same *local* day (they are not in UTC), so cap 2 on
    # calendar days must reject the loop as well
    assert _counter(graph, 1, 24, None, 2, 'calendar').totals().round_trip == 0
    # and all of it agrees with the booking_cap oracle
    _check_against_enumeration(graph, [(1, 24, n, cap, mode)
                                       for n in (4, None) for cap in (2, 3)
                                       for mode in ('none', 'calendar', 'rolling24')], 'midnight')


def test_cap_state_rejects_and_reports():
    graph = fixtures.midnight_graph()
    network = FlightNetwork.from_graph(graph)
    ordered = sorted(network.flights, key=lambda f: f.dep)
    state = cap_state_of(ordered[:3], 3, 'rolling24')
    assert cap_advance(state, ordered[3], 3, 'rolling24') is None, "fourth departure inside 24 h must be refused"
    try:
        cap_state_of(ordered, 3, 'rolling24')
    except ValueError as exc:
        assert 'rolling24' in str(exc)
    else:
        raise AssertionError("cap_state_of must raise on an illegal path")
