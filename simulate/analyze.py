"""Original-vs-fixed analyses for one dataset / scenario / booking-cap mode, plus aggregation.

Terminology
  * route: list of legs ``(from_city, to_city, [departure_iso, arrival_iso])`` (core/route_find.py).
  * visible flight: ``graph[a][b]['flights'][0]`` - the only flight of an edge the original search
    ever uses.  Every other flight of the edge is *invisible*.
  * missed route: found by the fixed search but not by the original.  Because the fixed search
    explores a superset of the original's candidates, the original's routes are always a subset
    of the fixed routes; the analysis verifies this (``n_orig_not_in_fixed`` must be 0).
  * day index: local calendar day of a departure relative to the dataset's first scan day.

Flow per dataset and scenario: ``run_search`` twice -> ``prepare`` both route lists once (keys,
shapes, metrics) -> ``compare`` once per cap mode (cheap masks over the prepared lists).
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import networkx as nx

from simulate import booking_cap
from simulate.routefmt import format_route_light

Route = List[Tuple[str, str, List[str]]]
RouteKey = Tuple[Tuple[str, str, str, str], ...]

_PARSE_CACHE: Dict[str, datetime] = {}


def parse_iso(text: str) -> datetime:
    """``datetime.fromisoformat`` with a per-process cache (route lists repeat the same flights)."""
    moment = _PARSE_CACHE.get(text)
    if moment is None:
        moment = datetime.fromisoformat(text)
        _PARSE_CACHE[text] = moment
    return moment


@dataclass(frozen=True)
class Scenario:
    mode: str            # 'rt' (round trip back to start) or 'ow' (one way to anywhere)
    min_gap_hours: float
    max_gap_hours: float

    @property
    def key(self) -> str:
        return f"{self.mode}_{_num(self.min_gap_hours)}-{_num(self.max_gap_hours)}"

    @property
    def label(self) -> str:
        kind = 'Rundreise' if self.mode == 'rt' else 'One-way'
        return f"{self.mode} {_num(self.min_gap_hours)}-{_num(self.max_gap_hours)}h ({kind})"


@dataclass(frozen=True)
class SearchParams:
    start: str
    max_flights: int
    flex_km: float
    transfer_speed_kmh: float
    distances_file: Path


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


# --- search ----------------------------------------------------------------------------------------

def run_search(module, graph: nx.DiGraph, scenario: Scenario, params: SearchParams) -> List[Route]:
    """Run ``module``'s search (original or fixed copy) with identical arguments.

    Precondition: ``module`` exposes find_round_trip_routes / find_one_way_routes with the
    ``max_flights`` keyword; ``params.start`` may be absent from the graph (then no routes).
    Postcondition: list of routes, every route has 1..max_flights legs.
    """
    common = dict(flex_km=params.flex_km, transfer_speed_kmh=params.transfer_speed_kmh,
                  distances_file=params.distances_file, max_flights=params.max_flights)
    if scenario.mode == 'rt':
        routes = module.find_round_trip_routes(graph, [params.start], scenario.min_gap_hours,
                                               scenario.max_gap_hours, **common)
    elif scenario.mode == 'ow':
        routes = module.find_one_way_routes(graph, [params.start], set(graph.nodes), scenario.min_gap_hours,
                                            scenario.max_gap_hours, **common)
    else:
        raise ValueError(f"unknown scenario mode {scenario.mode!r} (expected 'rt' or 'ow')")
    too_long = sum(1 for r in routes if len(r) > params.max_flights)
    if too_long:
        raise AssertionError(f"depth cap violated: {too_long} routes longer than {params.max_flights}")
    return routes


# --- route helpers -----------------------------------------------------------------------------------

def route_key(route: Route) -> RouteKey:
    return tuple((a, b, f[0], f[1]) for a, b, f in route)


def city_sequence(route: Route) -> Tuple[str, ...]:
    return (route[0][0],) + tuple(leg[1] for leg in route)


def first_flights(graph: nx.DiGraph) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """Edge -> the one flight the original search can see."""
    return {(a, b): (attrs['flights'][0][0], attrs['flights'][0][1]) for a, b, attrs in graph.edges(data=True)}


def leg_visible(leg, visible: Dict[Tuple[str, str], Tuple[str, str]]) -> bool:
    return visible.get((leg[0], leg[1])) == (leg[2][0], leg[2][1])


def local_day(dep_iso: str, day0: date) -> int:
    return (parse_iso(dep_iso).date() - day0).days


def route_metrics(route: Route, city_data: dict, country_data: dict) -> dict:
    """Numbers behind the extremes (same formulas as sort_routes / print_routes 'detailed')."""
    flight_time = sum((parse_iso(f[1]) - parse_iso(f[0]) for _, _, f in route), timedelta())
    trip = parse_iso(route[-1][2][1]) - parse_iso(route[0][2][0])
    cities = set(city_sequence(route))
    countries = set()
    unknown = 0
    for city in cities:
        country = city_data.get(city, {}).get('country')
        if country is None:
            unknown += 1
        else:
            countries.add(country)
    new_countries = {c for c in countries if not country_data.get(c, {}).get('visited', True)}
    trip_hours = trip.total_seconds() / 3600
    return {
        'flights': len(route),
        'cities': len(cities),
        'countries': len(countries),
        'unknown_cities': unknown,
        'new_countries': len(new_countries),
        'trip_hours': round(trip_hours, 2),
        'flight_hours': round(flight_time.total_seconds() / 3600, 2),
        'percent_in_air': round(100 * flight_time.total_seconds() / trip.total_seconds(), 2) if trip_hours > 0 else 100.0,
        'new_country_names': sorted(new_countries),
    }


@dataclass
class Prepared:
    """Per-route derived data, computed once per scenario and reused for every cap mode."""
    routes: List[Route]
    keys: List[RouteKey]
    sequences: List[Tuple[str, ...]]
    shapes: List[Tuple[int, int]]     # (flights, local day of the last departure)
    metrics: List[dict]


def prepare(routes: List[Route], day0: date, city_data: dict, country_data: dict) -> Prepared:
    return Prepared(
        routes=routes,
        keys=[route_key(r) for r in routes],
        sequences=[city_sequence(r) for r in routes],
        shapes=[(len(r), local_day(r[-1][2][0], day0)) for r in routes],
        metrics=[route_metrics(r, city_data, country_data) for r in routes],
    )


# --- classification of missed routes ---------------------------------------------------------------

def invisible_legs(route: Route, visible: dict, graph: nx.DiGraph, day0: date) -> dict:
    """Cap-independent part of the classification: which legs the original could not see and
    whether each is a later-day / same-day / earlier flight than the visible one of its edge."""
    positions = [i + 1 for i, leg in enumerate(route) if not leg_visible(leg, visible)]
    later_day = same_day = earlier = 0
    for pos in positions:
        a, b, flight = route[pos - 1]
        delta = local_day(flight[0], day0) - local_day(graph[a][b]['flights'][0][0], day0)
        if delta > 0:
            later_day += 1
        elif delta == 0:
            same_day += 1
        else:
            earlier += 1
    return {
        'invisible_positions': positions,
        'n_invisible': len(positions),
        'first_invisible_pos': positions[0] if positions else None,
        'later_day_legs': later_day,
        'same_day_legs': same_day,
        'earlier_legs': earlier,
        'only_last_leg_invisible': positions == [len(route)],
    }


def classify_missed(route: Route, visible: dict, graph: nx.DiGraph, day0: date, orig_keys: set,
                    orig_sequences: set, legs: Optional[dict] = None) -> dict:
    """Why did the original miss this route?  ``legs`` may carry a cached ``invisible_legs`` result."""
    info = dict(legs if legs is not None else invisible_legs(route, visible, graph, day0))
    info['prefix_known'] = len(route) == 1 or route_key(route[:-1]) in orig_keys
    info['new_itinerary'] = city_sequence(route) not in orig_sequences
    return info


def missed_tag(info: dict) -> str:
    """Compact annotation for route files, e.g. ``inv_pos=2,3 later_day=2/2 new_itin=yes``."""
    return (f"inv_pos={','.join(map(str, info['invisible_positions'])) or '-'} "
            f"later_day={info['later_day_legs']}/{info['n_invisible']} "
            f"new_itin={'yes' if info['new_itinerary'] else 'no'} "
            f"prefix_known={'yes' if info['prefix_known'] else 'no'}")


# --- main comparison ---------------------------------------------------------------------------------

EXTREME_METRICS = (
    ('most_flights', 'meiste Flüge', 'flights', 'max', 1),
    ('most_cities', 'meiste unterschiedliche Städte', 'cities', 'max', 1),
    ('most_countries', 'meiste Länder', 'countries', 'max', 1),
    ('max_percent_in_air', 'höchster percent_in_air (2+ Flüge)', 'percent_in_air', 'max', 2),
    ('longest_trip', 'längste trip_duration (h)', 'trip_hours', 'max', 1),
    ('shortest_trip_4plus', 'kürzeste trip_duration (h) bei 4+ Flügen', 'trip_hours', 'min', 4),
    ('most_new_countries', 'meiste neue Länder (visited: false)', 'new_countries', 'max', 1),
)


def _best(metrics: Sequence[dict], field: str, direction: str, min_flights: int,
          prefer: Optional[Sequence[bool]] = None) -> Optional[int]:
    """Index of the route with the best value; ties go to a ``prefer``-flagged route (a missed one on
    the fixed side), then to the earlier index.  Deterministic; None if no route qualifies."""
    best_i, best_key = None, None
    for i, m in enumerate(metrics):
        if m['flights'] < min_flights:
            continue
        v = m[field] if direction == 'max' else -m[field]
        key = (v, bool(prefer[i]) if prefer is not None else False)
        if best_key is None or key > best_key:
            best_i, best_key = i, key
    return best_i


@dataclass
class Comparison:
    """Everything derived from one (dataset, scenario, cap) pair."""
    stats: dict
    orig_routes: List[Route]
    fixed_routes: List[Route]
    missed_routes: List[Route]
    missed_info: List[dict]


def compare(graph: nx.DiGraph, orig: Prepared, fixed: Prepared, *, day0: date, n_days: int, max_flights: int,
            invisible_share: float, cap: int, cap_mode: str, distances: dict, city_data: dict,
            leg_cache: Optional[Dict[int, dict]] = None) -> Comparison:
    """Compare original vs fixed routes after applying the booking cap.

    Preconditions: ``orig``/``fixed`` come from ``prepare`` on routes of ``run_search`` over ``graph``;
    ``cap_mode`` in {'none','calendar','rolling24'}; ``0 <= invisible_share <= 1``; ``day0`` is the
    dataset's first scan day; ``leg_cache`` (fixed index -> ``invisible_legs``) is private to one
    scenario.  Postcondition: ``Comparison.stats`` is JSON-serialisable; ``missed_routes`` are exactly
    the fixed routes whose key is not among the original's, in fixed-search order.
    """
    def kept(prepared: Prepared) -> List[int]:
        if cap_mode == booking_cap.NO_CAP:
            return list(range(len(prepared.routes)))
        return [i for i, r in enumerate(prepared.routes) if booking_cap.passes_daily_cap(r, cap, cap_mode)]

    orig_idx, fixed_idx = kept(orig), kept(fixed)
    orig_keys = {orig.keys[i] for i in orig_idx}
    fixed_keys = {fixed.keys[i] for i in fixed_idx}
    orig_sequences = {orig.sequences[i] for i in orig_idx}
    fixed_is_missed = {i: fixed.keys[i] not in orig_keys for i in fixed_idx}
    missed_idx = [i for i in fixed_idx if fixed_is_missed[i]]
    visible = first_flights(graph)
    leg_cache = leg_cache if leg_cache is not None else {}
    missed_info = []
    for i in missed_idx:
        legs = leg_cache.get(i)
        if legs is None:
            legs = leg_cache[i] = invisible_legs(fixed.routes[i], visible, graph, day0)
        missed_info.append(classify_missed(fixed.routes[i], visible, graph, day0, orig_keys, orig_sequences, legs))

    n_orig, n_fixed, n_missed = len(orig_idx), len(fixed_idx), len(missed_idx)
    stats: dict = {
        'cap_mode': cap_mode,
        'cap': cap if cap_mode != booking_cap.NO_CAP else None,
        'n_orig': n_orig,
        'n_fixed': n_fixed,
        'n_missed': n_missed,
        'n_orig_not_in_fixed': len(orig_keys - fixed_keys),
        'factor': round(n_fixed / n_orig, 3) if n_orig else None,
        'pct_missed': round(100 * n_missed / n_fixed, 2) if n_fixed else None,
    }

    # depth effect: by number of flights and by local day of the last departure
    orig_shapes = Counter(orig.shapes[i] for i in orig_idx)
    fixed_shapes = Counter(fixed.shapes[i] for i in fixed_idx)
    missed_shapes = Counter(fixed.shapes[i] for i in missed_idx)

    def bucket_table(keys: Iterable, index: int, expected: Optional[Callable] = None) -> dict:
        table = {}
        for k in keys:
            o = sum(v for s, v in orig_shapes.items() if s[index] == k)
            f = sum(v for s, v in fixed_shapes.items() if s[index] == k)
            m = sum(v for s, v in missed_shapes.items() if s[index] == k)
            entry = {'orig': o, 'fixed': f, 'missed': m, 'pct_missed': round(100 * m / f, 2) if f else None}
            if expected is not None:
                entry['expected_pct_missed'] = round(100 * expected(k), 2)
            table[str(k)] = entry
        return table

    stats['by_flights'] = bucket_table(range(1, max_flights + 1), 0,
                                       expected=lambda k: 1 - (1 - invisible_share) ** k)
    stats['by_day'] = bucket_table(range(n_days), 1)
    cross = {}
    for k in range(1, max_flights + 1):
        for d in range(n_days):
            f, m = fixed_shapes[(k, d)], missed_shapes[(k, d)]
            cross[f"{k}x{d}"] = {'fixed': f, 'missed': m, 'pct_missed': round(100 * m / f, 2) if f else None}
    stats['by_flights_day'] = cross
    stats['depth_test'] = depth_test(fixed_shapes, missed_shapes)

    # what kind of routes were missed
    missed_routes = [fixed.routes[i] for i in missed_idx]
    stats['missed_class'] = summarize_missed(missed_routes, missed_info, max_flights)

    # extremes
    orig_metrics = [orig.metrics[i] for i in orig_idx]
    fixed_metrics = [fixed.metrics[i] for i in fixed_idx]
    prefer = [fixed_is_missed[i] for i in fixed_idx]
    extremes = {}
    for key, label, field, direction, min_flights in EXTREME_METRICS:
        entry = {'label': label, 'field': field}
        for side, idx, metrics, pref in (('orig', orig_idx, orig_metrics, None),
                                         ('fixed', fixed_idx, fixed_metrics, prefer)):
            j = _best(metrics, field, direction, min_flights, pref)
            if j is None:
                entry[side] = None
            else:
                source = orig if side == 'orig' else fixed
                entry[side] = {'value': metrics[j][field], 'flights': metrics[j]['flights'],
                               'route': format_route_light(source.routes[idx[j]], distances),
                               'is_missed': side == 'fixed' and prefer[j],
                               'new_country_names': metrics[j]['new_country_names']}
        extremes[key] = entry
    stats['extremes'] = extremes
    stats['unknown_cities'] = sorted({c for i in fixed_idx for c in fixed.sequences[i] if c not in city_data})

    # reachability
    end_orig = {orig.sequences[i][-1] for i in orig_idx}
    end_fixed = {fixed.sequences[i][-1] for i in fixed_idx}
    seen_orig = {c for i in orig_idx for c in orig.sequences[i]}
    seen_fixed = {c for i in fixed_idx for c in fixed.sequences[i]}
    stats['reach'] = {
        'n_end_orig': len(end_orig), 'n_end_fixed': len(end_fixed),
        'end_only_fixed': sorted(end_fixed - end_orig), 'n_end_only_fixed': len(end_fixed - end_orig),
        'n_visited_orig': len(seen_orig), 'n_visited_fixed': len(seen_fixed),
        'visited_only_fixed': sorted(seen_fixed - seen_orig), 'n_visited_only_fixed': len(seen_fixed - seen_orig),
    }
    return Comparison(stats=stats, orig_routes=[orig.routes[i] for i in orig_idx],
                      fixed_routes=[fixed.routes[i] for i in fixed_idx], missed_routes=missed_routes,
                      missed_info=missed_info)


def depth_test(fixed_shapes: Counter, missed_shapes: Counter) -> dict:
    """Pooled missed shares: 3+ flights vs 1-2 flights, last departure on day >= 2 vs day <= 1.
    ``*_shapes`` count routes by ``(flights, last_departure_day)``."""
    def share(pred: Callable[[Tuple[int, int]], bool]) -> Optional[float]:
        f = sum(v for s, v in fixed_shapes.items() if pred(s))
        m = sum(v for s, v in missed_shapes.items() if pred(s))
        return round(100 * m / f, 2) if f else None

    deep, shallow = share(lambda s: s[0] >= 3), share(lambda s: s[0] <= 2)
    late, early = share(lambda s: s[1] >= 2), share(lambda s: s[1] <= 1)
    return {
        'pct_missed_3plus': deep, 'pct_missed_1to2': shallow,
        'ratio_depth': round(deep / shallow, 3) if deep is not None and shallow else None,
        'pct_missed_day2plus': late, 'pct_missed_day01': early,
        'ratio_day': round(late / early, 3) if late is not None and early else None,
    }


def summarize_missed(missed: List[Route], infos: List[dict], max_flights: int) -> dict:
    n = len(missed)

    def pct(count: int) -> Optional[float]:
        return round(100 * count / n, 2) if n else None

    n_invisible_hist = {str(k): sum(1 for i in infos if i['n_invisible'] == k) for k in range(0, max_flights + 1)}
    first_pos_hist = {str(k): sum(1 for i in infos if i['first_invisible_pos'] == k) for k in range(1, max_flights + 1)}
    first_pos_hist_pct = {k: pct(v) for k, v in first_pos_hist.items()}
    share_by_pos = {}
    for pos in range(1, max_flights + 1):
        eligible = [i for r, i in zip(missed, infos) if len(r) >= pos]
        hit = sum(1 for i in eligible if pos in i['invisible_positions'])
        share_by_pos[str(pos)] = {'eligible': len(eligible), 'invisible': hit,
                                  'pct': round(100 * hit / len(eligible), 2) if eligible else None}
    with_inv = sum(1 for i in infos if i['n_invisible'] > 0)
    later_any = sum(1 for i in infos if i['later_day_legs'] > 0)
    later_all = sum(1 for i in infos if i['n_invisible'] and i['later_day_legs'] == i['n_invisible'])
    same_only = sum(1 for i in infos if i['n_invisible'] and i['same_day_legs'] == i['n_invisible'])
    earlier_any = sum(1 for i in infos if i['earlier_legs'] > 0)
    only_last = sum(1 for i in infos if i['only_last_leg_invisible'])
    prefix_known = sum(1 for i in infos if i['prefix_known'])
    new_itinerary = sum(1 for i in infos if i['new_itinerary'])
    return {
        'n': n,
        'with_invisible': with_inv, 'pct_with_invisible': pct(with_inv),
        'n_invisible_hist': n_invisible_hist,
        'first_invisible_pos_hist': first_pos_hist,
        'first_invisible_pos_hist_pct': first_pos_hist_pct,
        'invisible_share_by_position': share_by_pos,
        'later_day_any': later_any, 'pct_later_day_any': pct(later_any),
        'later_day_all': later_all, 'pct_later_day_all': pct(later_all),
        'same_day_only': same_only, 'pct_same_day_only': pct(same_only),
        'earlier_any': earlier_any,
        'only_last_leg_invisible': only_last, 'pct_only_last_leg_invisible': pct(only_last),
        'prefix_known': prefix_known, 'pct_prefix_known': pct(prefix_known),
        'new_itinerary': new_itinerary, 'pct_new_itinerary': pct(new_itinerary),
    }


# --- aggregation over datasets -------------------------------------------------------------------------

def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and not (isinstance(value, float) and math.isnan(value))


def aggregate(dicts: Sequence[dict]) -> dict:
    """Walk parallel nested dicts; every numeric leaf becomes ``{'median','min','max','n'}``.

    ``None`` leaves are skipped (``n`` counts the datasets that had a value); non-numeric leaves
    (strings, lists, dicts of routes) are dropped.  Precondition: same key structure per dict.
    """
    keys: List = []
    for d in dicts:
        for k in d:
            if k not in keys:
                keys.append(k)
    result = {}
    for k in keys:
        values = [d[k] for d in dicts if k in d]
        if values and all(isinstance(v, dict) for v in values):
            sub = aggregate(values)
            if sub:
                result[k] = sub
        else:
            nums = [v for v in values if _is_number(v)]
            if nums:
                result[k] = {'median': round(statistics.median(nums), 3), 'min': min(nums), 'max': max(nums),
                             'n': len(nums)}
    return result
