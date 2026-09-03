"""Seedable generator for synthetic Wizz-style flight networks.

The output has exactly the layout of data/current/flight_graph.json::

    {origin: {destination: [[departure_iso, arrival_iso], ...], ...}, ...}

with ISO-8601 local times carrying a UTC offset (``2025-03-13T15:35:00+01:00``), flights of an edge
sorted by departure.  ``to_graph`` converts it into the ``nx.DiGraph`` shape produced by
core/converter.py (edge attribute ``flights`` = list of ``[dep, arr]`` lists), which is what
core/route_find.py consumes.

Calibration tables (hub weights, day distribution, departure-hour histogram, UTC offsets,
flights-per-edge distribution) are taken from the real scan data/current/graph.pkl
(2025-03-12 .. 2025-03-15, 146 cities, 631 edges, 1019 flights).

Invariants of a generated network:
  * no self-loops, no duplicate edges, every city has at least one edge;
  * every flight departs between 05:30 and 22:30 local time (day 0 only from 19:00, the real
    scan ran in the evening), arrival = departure + duration, duration inside the configured range;
  * flights of an edge have pairwise distinct departure strings and are sorted by departure.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import networkx as nx

FlightJson = Dict[str, Dict[str, List[List[str]]]]

# --- calibration tables --------------------------------------------------------------------------

#: Flights in + out per hub in the real scan (relative weights).
HUB_WEIGHTS: Dict[str, int] = {
    'Budapest': 157, 'London Luton': 113, 'Abu Dhabi': 107, 'Rome Fiumicino': 102, 'Milan Malpensa': 83,
    'Bucharest': 82, 'London Gatwick': 78, 'Gdansk': 62, 'Tel-Aviv': 53, 'Warsaw Chopin': 51, 'Vienna': 50,
    'Larnaca': 45, 'Katowice': 39, 'Tirana': 38, 'Kutaisi': 36, 'Sofia': 35, 'Yerevan': 34, 'Barcelona': 30,
    'Dortmund': 27, 'Krakow': 26, 'Belgrade': 25, 'Prague': 22, 'Malaga': 22, 'Tenerife': 22, 'Istanbul': 21,
}

#: The 121 non-hub cities of the real scan, in a fixed order (sorted) so seeds stay reproducible.
SPOKE_POOL: List[str] = [
    'Aberdeen', 'Agadir', 'Alesund', 'Alexandria', 'Alicante', 'Almaty', 'Amman', 'Antalya', 'Astana', 'Athens',
    'Bacau', 'Baku', 'Banja Luka', 'Bari', 'Basel (BSL)', 'Basel (MLH)', 'Bergen', 'Berlin', 'Bilbao', 'Billund',
    'Birmingham', 'Bishkek', 'Bologna', 'Brasov', 'Bratislava', 'Brussels Charleroi', 'Cairo', 'Catania',
    'Chisinau', 'Cluj-Napoca', 'Copenhagen', 'Craiova', 'Dammam', 'Debrecen', 'Dubai', 'Eindhoven', 'Frankfurt',
    'Fuerteventura', 'Funchal', 'Glasgow', 'Gothenburg', 'Gran Canaria', 'Grenoble', 'Hamburg', 'Haugesund',
    'Hurghada', 'Iasi', 'Jeddah', 'Karlsruhe/Baden-Baden', 'Kaunas', 'Kosice', 'Leeds', 'Leipzig', 'Lisbon',
    'Liverpool', 'Ljubljana', 'Lublin', 'Lyon', 'Madinah', 'Madrid', 'Male', 'Malmo', 'Malta', 'Marrakesh',
    'Marsa Alam', 'Memmingen', 'Milan Bergamo', 'Naples', 'Nice', 'Nis', 'Nuremberg', 'Ohrid', 'Oslo Gardermoen',
    'Oslo Sandefjord Torp', 'Paris Beauvais', 'Paris Orly', 'Perugia', 'Pescara', 'Podgorica', 'Poprad-Tatry',
    'Poznan', 'Prishtina', 'Reykjavik', 'Riga', 'Rimini', 'Riyadh', 'Rome Ciampino', 'Rzeszow', 'Salerno',
    'Salzburg', 'Samarkand', 'Sarajevo', 'Seville', 'Sharm El Sheikh', 'Sibiu', 'Skopje', 'Sohag', 'Stavanger',
    'Stockholm Arlanda', 'Stockholm Skavsta', 'Stuttgart', 'Suceava', 'Szczecin', 'Tallinn', 'Tashkent',
    'Thessaloniki', 'Timisoara', 'Tirgu Mures', 'Trieste', 'Tromso', 'Turin', 'Turkistan', 'Turku', 'Tuzla',
    'Valencia', 'Varna', 'Venice Marco Polo', 'Venice Treviso', 'Verona', 'Vilnius', 'Wroclaw',
]

#: UTC offset per city as observed in the real scan (mid-March 2025, i.e. before the DST switch).
OFFSETS: Dict[str, str] = {
    'Aberdeen': '+00:00', 'Abu Dhabi': '+04:00', 'Agadir': '+00:00', 'Alesund': '+01:00', 'Alexandria': '+02:00',
    'Alicante': '+01:00', 'Almaty': '+05:00', 'Amman': '+03:00', 'Antalya': '+03:00', 'Astana': '+05:00',
    'Athens': '+02:00', 'Bacau': '+02:00', 'Baku': '+04:00', 'Banja Luka': '+01:00', 'Barcelona': '+01:00',
    'Bari': '+01:00', 'Basel (BSL)': '+01:00', 'Basel (MLH)': '+01:00', 'Belgrade': '+01:00', 'Bergen': '+01:00',
    'Berlin': '+01:00', 'Bilbao': '+01:00', 'Billund': '+01:00', 'Birmingham': '+00:00', 'Bishkek': '+06:00',
    'Bologna': '+01:00', 'Brasov': '+02:00', 'Bratislava': '+01:00', 'Brussels Charleroi': '+01:00',
    'Bucharest': '+02:00', 'Budapest': '+01:00', 'Cairo': '+02:00', 'Catania': '+01:00', 'Chisinau': '+02:00',
    'Cluj-Napoca': '+02:00', 'Copenhagen': '+01:00', 'Craiova': '+02:00', 'Dammam': '+03:00', 'Debrecen': '+01:00',
    'Dortmund': '+01:00', 'Dubai': '+04:00', 'Eindhoven': '+01:00', 'Frankfurt': '+01:00', 'Fuerteventura': '+00:00',
    'Funchal': '+00:00', 'Gdansk': '+01:00', 'Glasgow': '+00:00', 'Gothenburg': '+01:00', 'Gran Canaria': '+00:00',
    'Grenoble': '+01:00', 'Hamburg': '+01:00', 'Haugesund': '+01:00', 'Hurghada': '+02:00', 'Iasi': '+02:00',
    'Istanbul': '+03:00', 'Jeddah': '+03:00', 'Karlsruhe/Baden-Baden': '+01:00', 'Katowice': '+01:00',
    'Kaunas': '+02:00', 'Kosice': '+01:00', 'Krakow': '+01:00', 'Kutaisi': '+04:00', 'Larnaca': '+02:00',
    'Leeds': '+00:00', 'Leipzig': '+01:00', 'Lisbon': '+00:00', 'Liverpool': '+00:00', 'Ljubljana': '+01:00',
    'London Gatwick': '+00:00', 'London Luton': '+00:00', 'Lublin': '+01:00', 'Lyon': '+01:00', 'Madinah': '+03:00',
    'Madrid': '+01:00', 'Malaga': '+01:00', 'Male': '+05:00', 'Malmo': '+01:00', 'Malta': '+01:00',
    'Marrakesh': '+00:00', 'Marsa Alam': '+02:00', 'Memmingen': '+01:00', 'Milan Bergamo': '+01:00',
    'Milan Malpensa': '+01:00', 'Naples': '+01:00', 'Nice': '+01:00', 'Nis': '+01:00', 'Nuremberg': '+01:00',
    'Ohrid': '+01:00', 'Oslo Gardermoen': '+01:00', 'Oslo Sandefjord Torp': '+01:00', 'Paris Beauvais': '+01:00',
    'Paris Orly': '+01:00', 'Perugia': '+01:00', 'Pescara': '+01:00', 'Podgorica': '+01:00', 'Poprad-Tatry': '+01:00',
    'Poznan': '+01:00', 'Prague': '+01:00', 'Prishtina': '+01:00', 'Reykjavik': '+00:00', 'Riga': '+02:00',
    'Rimini': '+01:00', 'Riyadh': '+03:00', 'Rome Ciampino': '+01:00', 'Rome Fiumicino': '+01:00',
    'Rzeszow': '+01:00', 'Salerno': '+01:00', 'Salzburg': '+01:00', 'Samarkand': '+05:00', 'Sarajevo': '+01:00',
    'Seville': '+01:00', 'Sharm El Sheikh': '+02:00', 'Sibiu': '+02:00', 'Skopje': '+01:00', 'Sofia': '+02:00',
    'Sohag': '+02:00', 'Stavanger': '+01:00', 'Stockholm Arlanda': '+01:00', 'Stockholm Skavsta': '+01:00',
    'Stuttgart': '+01:00', 'Suceava': '+02:00', 'Szczecin': '+01:00', 'Tallinn': '+02:00', 'Tashkent': '+05:00',
    'Tel-Aviv': '+02:00', 'Tenerife': '+00:00', 'Thessaloniki': '+02:00', 'Timisoara': '+02:00', 'Tirana': '+01:00',
    'Tirgu Mures': '+02:00', 'Trieste': '+01:00', 'Tromso': '+01:00', 'Turin': '+01:00', 'Turkistan': '+05:00',
    'Turku': '+02:00', 'Tuzla': '+01:00', 'Valencia': '+01:00', 'Varna': '+02:00', 'Venice Marco Polo': '+01:00',
    'Venice Treviso': '+01:00', 'Verona': '+01:00', 'Vienna': '+01:00', 'Vilnius': '+02:00',
    'Warsaw Chopin': '+01:00', 'Wroclaw': '+01:00', 'Yerevan': '+04:00',
}
DEFAULT_OFFSET = '+01:00'

#: Cities whose flights are long-haul (4-7 h) instead of intra-European (1-5.5 h).
LONG_HAUL_CITIES = frozenset({'Abu Dhabi', 'Dubai'})

#: Departure-hour histogram of the real scan restricted to the allowed 05:30-22:30 window.
DEP_HOUR_WEIGHTS: Dict[int, int] = {
    5: 28, 6: 146, 7: 31, 8: 56, 9: 63, 10: 46, 11: 59, 12: 39, 13: 62, 14: 33, 15: 44, 16: 63, 17: 36,
    18: 44, 19: 62, 20: 63, 21: 55, 22: 41,
}
#: Day 0 of the real scan only had evening departures (the scan ran in the evening).
DAY0_HOUR_WEIGHTS: Dict[int, int] = {19: 1, 20: 8, 21: 7, 22: 11}

#: Flights per scan day in the real scan (day 0 .. day 3).
DAY_WEIGHTS: Tuple[int, ...] = (31, 373, 291, 324)

#: How many hubs a spoke is connected to (1..5) in percent.
HUB_COUNT_WEIGHTS: Dict[int, int] = {1: 35, 2: 35, 3: 18, 4: 8, 5: 4}

#: Flights per edge by edge class.  'hub_spoke' is the scan-wide distribution the task specifies
#: (60 % one flight, 27 % two, 8 % three, 5 % four to nine); hub-hub edges get more (real scan:
#: 2.07 flights per hub-hub edge vs 1.46 hub-spoke vs 1.09 spoke-spoke).
FLIGHTS_PER_EDGE: Dict[str, Dict[int, float]] = {
    'spoke_spoke': {1: 0.92, 2: 0.07, 3: 0.01},
    'hub_spoke': {1: 0.60, 2: 0.27, 3: 0.08, 4: 0.02, 5: 0.01, 6: 0.01, 7: 0.005, 8: 0.003, 9: 0.002},
    'hub_hub': {1: 0.55, 2: 0.27, 3: 0.10, 4: 0.04, 5: 0.02, 6: 0.01, 7: 0.005, 8: 0.003, 9: 0.002},
}

#: Real scan: flights of one edge fall on distinct days almost always (2-flight edges: 98 %); only
#: trunk routes with 3+ flights show two departures on the same day (15-21 % of multi-flight edges).
SAME_DAY_DUPLICATE_PROB = 0.3

#: Linear fit of flight duration against great-circle distance in the real scan
#: (duration_h = 0.68 + km / 754, residual sd 0.22 h).
DURATION_INTERCEPT_H = 0.68
DURATION_KMH = 754.0
DURATION_JITTER_SD_H = 0.15

EUROPE_DURATION_H = (1.0, 5.5)
LONG_HAUL_DURATION_H = (4.0, 7.0)


@dataclass
class SynthParams:
    """Tunable knobs of the generator.  All defaults reproduce the task's target sizes:
    ~146 cities, 800-900 directed edges, 1000-1500 flights over 4 days."""
    n_spokes: int = len(SPOKE_POOL)
    target_edges: int = 840
    spoke_spoke_share: float = 0.06          # share of all edges that connect two spokes
    both_directions_hub_spoke: float = 0.52  # P(both directions) for a spoke-hub link (-> ~68 % reciprocity)
    both_directions_hub_hub: float = 0.60
    both_directions_spoke_spoke: float = 0.30
    base_date: str = '2025-03-12'            # local calendar day 0
    n_days: int = len(DAY_WEIGHTS)
    hub_weights: Dict[str, int] = field(default_factory=lambda: dict(HUB_WEIGHTS))

    def validate(self) -> None:
        if self.n_spokes < 1:
            raise ValueError("n_spokes must be >= 1")
        if self.target_edges < len(self.hub_weights) + self.n_spokes:
            raise ValueError("target_edges too small to connect every city")
        if not 0 <= self.spoke_spoke_share < 1:
            raise ValueError("spoke_spoke_share must be in [0, 1)")
        for name in ('both_directions_hub_spoke', 'both_directions_hub_hub', 'both_directions_spoke_spoke'):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.n_days < 1 or self.n_days > len(DAY_WEIGHTS):
            raise ValueError(f"n_days must be in 1..{len(DAY_WEIGHTS)}")
        date.fromisoformat(self.base_date)
        if len(self.hub_weights) < 2 or any(w <= 0 for w in self.hub_weights.values()):
            raise ValueError("hub_weights needs >= 2 hubs with positive weights")


DistanceLookup = Callable[[str, str], Optional[float]]


# --- helpers ---------------------------------------------------------------------------------------

def _weighted_choice(rng: random.Random, weights: Dict, ) -> object:
    """Pick a key of ``weights`` with probability proportional to its (positive) value."""
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _weighted_sample_without_replacement(rng: random.Random, weights: Dict[str, float], k: int) -> List[str]:
    """Draw ``k`` distinct keys, each draw proportional to weight among the remaining keys."""
    remaining = dict(weights)
    picked: List[str] = []
    while remaining and len(picked) < k:
        choice = _weighted_choice(rng, remaining)
        picked.append(choice)
        del remaining[choice]
    return picked


def _offset_tz(city: str) -> timezone:
    text = OFFSETS.get(city, DEFAULT_OFFSET)
    sign = 1 if text[0] == '+' else -1
    hours, minutes = int(text[1:3]), int(text[4:6])
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def iso_local(moment: datetime) -> str:
    """Format an aware datetime like the scanner does: ``2025-03-13T15:35:00+01:00``."""
    return moment.isoformat(timespec='seconds')


def _solve_scale(scores: Sequence[float], target_sum: float) -> float:
    """Find alpha >= 0 with sum(min(1, alpha * s)) == target_sum (bisection; scores > 0)."""
    if target_sum >= len(scores):
        return float('inf')
    if target_sum <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    while sum(min(1.0, hi * s) for s in scores) < target_sum:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if sum(min(1.0, mid * s) for s in scores) < target_sum:
            lo = mid
        else:
            hi = mid
    return hi


# --- generator --------------------------------------------------------------------------------------

def generate_network(seed: int, params: Optional[SynthParams] = None,
                     distance_lookup: Optional[DistanceLookup] = None) -> FlightJson:
    """Generate one synthetic network.

    Preconditions: ``seed`` is any int; ``params`` valid per ``SynthParams.validate``;
    ``distance_lookup(a, b)`` returns km or None (None -> uniform duration in range).
    Postconditions: returns the flight_graph.json layout described in the module docstring, honouring
    the invariants listed there; identical output for identical (seed, params, distances).
    """
    params = params or SynthParams()
    params.validate()
    rng = random.Random(seed)
    hubs = list(params.hub_weights)
    hub_set = set(hubs)
    spokes = _spoke_names(params.n_spokes, hub_set)
    edges: set = set()

    # 1. spokes attach to 1-5 hubs, hubs chosen proportional to their weight
    for spoke in spokes:
        n_hubs = _weighted_choice(rng, HUB_COUNT_WEIGHTS)
        for hub in _weighted_sample_without_replacement(rng, params.hub_weights, n_hubs):
            _add_link(rng, edges, spoke, hub, params.both_directions_hub_spoke)

    # 2. hub-hub edges, dense, probability rising with sqrt(w_i * w_j)
    n_ss_target = round(params.target_edges * params.spoke_spoke_share)
    n_hh_target = max(0, params.target_edges - len(edges) - n_ss_target)
    pairs = [(hubs[i], hubs[j]) for i in range(len(hubs)) for j in range(i + 1, len(hubs))]
    scores = [math.sqrt(params.hub_weights[a] * params.hub_weights[b]) for a, b in pairs]
    s_max = max(scores)
    scores = [s / s_max for s in scores]
    pairs_target = n_hh_target / (1 + params.both_directions_hub_hub)
    alpha = _solve_scale(scores, pairs_target)
    for (a, b), s in zip(pairs, scores):
        if rng.random() < min(1.0, alpha * s):
            _add_link(rng, edges, a, b, params.both_directions_hub_hub)

    # 3. a few spoke-spoke edges
    attempts = 0
    while n_ss_target > 0 and attempts < 50 * n_ss_target and len(spokes) >= 2:
        attempts += 1
        a, b = rng.sample(spokes, 2)
        if (a, b) in edges or (b, a) in edges:
            continue
        n_ss_target -= _add_link(rng, edges, a, b, params.both_directions_spoke_spoke)

    # 4. flights
    day0 = date.fromisoformat(params.base_date)
    day_weights = {d: DAY_WEIGHTS[d] for d in range(params.n_days)}
    network: FlightJson = {}
    for a, b in sorted(edges):
        edge_class = _edge_class(a, b, hub_set)
        n_flights = _weighted_choice(rng, FLIGHTS_PER_EDGE[edge_class])
        flights = _generate_flights(rng, a, b, n_flights, day0, day_weights, distance_lookup)
        network.setdefault(a, {})[b] = flights
    return network


def _spoke_names(n_spokes: int, hub_set: set) -> List[str]:
    pool = [c for c in SPOKE_POOL if c not in hub_set]
    if n_spokes <= len(pool):
        return pool[:n_spokes]
    extra = [f"Spoke-{i:03d}" for i in range(n_spokes - len(pool))]
    return pool + extra


def _edge_class(a: str, b: str, hub_set: set) -> str:
    n_hubs = (a in hub_set) + (b in hub_set)
    return ('spoke_spoke', 'hub_spoke', 'hub_hub')[n_hubs]


def _add_link(rng: random.Random, edges: set, a: str, b: str, p_both: float) -> int:
    """Add the a-b connection as both directions (prob p_both) or one random direction.
    Returns the number of directed edges that are new to ``edges`` (0 for a self-loop)."""
    if a == b:
        return 0
    before = len(edges)
    if rng.random() < p_both:
        edges.add((a, b))
        edges.add((b, a))
    elif rng.random() < 0.5:
        edges.add((a, b))
    else:
        edges.add((b, a))
    return len(edges) - before


def _duration_hours(rng: random.Random, a: str, b: str, distance_lookup: Optional[DistanceLookup]) -> float:
    lo, hi = LONG_HAUL_DURATION_H if (a in LONG_HAUL_CITIES or b in LONG_HAUL_CITIES) else EUROPE_DURATION_H
    km = distance_lookup(a, b) if distance_lookup is not None else None
    if km is None or km <= 0:
        hours = rng.uniform(lo, hi)
    else:
        hours = DURATION_INTERCEPT_H + km / DURATION_KMH + rng.gauss(0.0, DURATION_JITTER_SD_H)
        hours = min(hi, max(lo, hours))
    return round(hours * 12) / 12  # 5-minute steps


def _departure_local(rng: random.Random, day: int, day0: date, tz: timezone) -> datetime:
    weights = DAY0_HOUR_WEIGHTS if day == 0 else DEP_HOUR_WEIGHTS
    for _ in range(100):
        hour = _weighted_choice(rng, weights)
        minute = 5 * rng.randrange(12)
        if (hour, minute) < (5, 30) or (hour, minute) > (22, 30):
            continue
        return datetime.combine(day0 + timedelta(days=day), datetime.min.time(), tzinfo=tz).replace(
            hour=hour, minute=minute)
    raise RuntimeError("could not draw a departure time inside 05:30-22:30 after 100 tries")


def _flight_days(rng: random.Random, n_flights: int, day_weights: Dict[int, int]) -> List[int]:
    """Scan days for the flights of one edge: distinct days first (weighted, without replacement);
    only when the edge has more flights than days, or with SAME_DAY_DUPLICATE_PROB for 3+ flights,
    does a day repeat."""
    distinct = _weighted_sample_without_replacement(rng, day_weights, min(n_flights, len(day_weights)))
    days = list(distinct)
    # repeats never land on day 0: the real scan ran in the evening of day 0, so that day only holds
    # the tail of the schedule and every edge has at most one flight there
    repeat_weights = {d: w for d, w in day_weights.items() if d != 0} or day_weights
    if n_flights >= 3 and len(days) == n_flights and rng.random() < SAME_DAY_DUPLICATE_PROB:
        days[-1] = _weighted_choice(rng, repeat_weights)
    while len(days) < n_flights:
        days.append(_weighted_choice(rng, repeat_weights))
    return days


def _generate_flights(rng: random.Random, a: str, b: str, n_flights: int, day0: date,
                      day_weights: Dict[int, int], distance_lookup: Optional[DistanceLookup]) -> List[List[str]]:
    tz_a, tz_b = _offset_tz(a), _offset_tz(b)
    flights: Dict[str, List[str]] = {}
    days = _flight_days(rng, n_flights, day_weights)
    tries = 0
    while len(flights) < n_flights and tries < 50 * n_flights:
        tries += 1
        day = days[len(flights)]
        departure = _departure_local(rng, day, day0, tz_a)
        arrival = (departure + timedelta(hours=_duration_hours(rng, a, b, distance_lookup))).astimezone(tz_b)
        dep_str = iso_local(departure)
        if dep_str in flights:
            continue
        flights[dep_str] = [dep_str, iso_local(arrival)]
    if not flights:
        raise RuntimeError(f"no flight could be generated for edge {a} -> {b}")
    return sorted(flights.values(), key=lambda f: datetime.fromisoformat(f[0]))


# --- conversion & statistics ---------------------------------------------------------------------

def to_graph(flight_data: FlightJson) -> nx.DiGraph:
    """Build the DiGraph exactly like core/converter.py::create_directed_graph_from_json
    (edge attribute ``flights`` = list of ``[departure, arrival]`` lists), without its logging."""
    graph = nx.DiGraph()
    for origin, destinations in flight_data.items():
        for destination, flights in destinations.items():
            if not graph.has_edge(origin, destination):
                graph.add_edge(origin, destination, flights=[])
            for flight in flights:
                graph[origin][destination]['flights'].append([flight[0], flight[1]])
    return graph


def hub_set_of(graph: nx.DiGraph, n_hubs: int = len(HUB_WEIGHTS)) -> set:
    """The ``n_hubs`` cities with the most flights (in + out)."""
    return {city for city, _ in _flight_weights(graph).most_common(n_hubs)}


def _flight_weights(graph: nx.DiGraph) -> Counter:
    weights: Counter = Counter()
    for a, b, attrs in graph.edges(data=True):
        weights[a] += len(attrs['flights'])
        weights[b] += len(attrs['flights'])
    return weights


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation (average ranks for ties); None if fewer than 3 points."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None

    def ranks(values: Sequence[float]) -> List[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                result[order[k]] = avg
            i = j + 1
        return result

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    vx = sum((x - mx) ** 2 for x in rx)
    vy = sum((y - my) ** 2 for y in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def network_stats(graph: nx.DiGraph, hub_weights: Optional[Dict[str, int]] = None) -> dict:
    """Descriptive statistics of a flight graph, incl. what the bug hides.

    A flight is *invisible* to the original search when it is not ``flights[0]`` of its edge.
    ``day0`` is the earliest local departure date; ``day`` indices are relative to it.
    """
    n_flights = 0
    per_edge: Counter = Counter()
    by_day: Counter = Counter()
    invisible_by_day: Counter = Counter()
    dates = set()
    for _, _, attrs in graph.edges(data=True):
        flights = attrs['flights']
        n_flights += len(flights)
        per_edge[len(flights)] += 1
        for flight in flights:
            dates.add(datetime.fromisoformat(flight[0]).date())
    day0 = min(dates) if dates else None
    for _, _, attrs in graph.edges(data=True):
        for i, flight in enumerate(attrs['flights']):
            day = (datetime.fromisoformat(flight[0]).date() - day0).days
            by_day[day] += 1
            if i > 0:
                invisible_by_day[day] += 1
    hubs = hub_set_of(graph)
    classes: Counter = Counter()
    for a, b in graph.edges():
        classes[_edge_class(a, b, hubs)] += 1
    reciprocal = sum(1 for a, b in graph.edges() if graph.has_edge(b, a))
    n_edges = graph.number_of_edges()
    days = sorted(by_day)
    stats = {
        'n_cities': graph.number_of_nodes(),
        'n_edges': n_edges,
        'n_flights': n_flights,
        'day0': day0.isoformat() if day0 else None,
        'flights_by_day': [by_day[d] for d in days],
        'invisible_by_day': [invisible_by_day[d] for d in days],
        'visible_share_by_day': [round(1 - invisible_by_day[d] / by_day[d], 3) for d in days],
        'invisible_total': sum(invisible_by_day.values()),
        'invisible_share': round(sum(invisible_by_day.values()) / n_flights, 4) if n_flights else 0.0,
        'flights_per_edge': {str(k): per_edge[k] for k in sorted(per_edge)},
        'edges_hub_hub': classes['hub_hub'],
        'edges_hub_spoke': classes['hub_spoke'],
        'edges_spoke_spoke': classes['spoke_spoke'],
        'reciprocity': round(reciprocal / n_edges, 3) if n_edges else 0.0,
        'top_hubs': _flight_weights(graph).most_common(10),
    }
    if hub_weights:
        realized = _flight_weights(graph)
        names = [h for h in hub_weights if h in realized]
        stats['hub_weight_spearman'] = spearman([hub_weights[h] for h in names], [realized[h] for h in names])
    return stats


def params_to_dict(params: SynthParams) -> dict:
    return asdict(params)
