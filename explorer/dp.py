"""Time-ordered flight DAG and the backward dynamic program behind the explorer.

Nodes are concrete flights, an edge f -> g means "g is a legal connection after f":
``g`` departs from the city ``f`` arrives in, and ``arr(f) + min_gap <= dep(g) <= arr(f) + max_gap``.
That is exactly the successor rule of ``simulate/route_find_fixed.py`` with ``flex_km = 0`` (no city
clustering, so transfer time is zero and the connecting flight must leave the arrival city).

Because a flight always arrives after it departs, departures increase strictly along any path, so
sorting flights by departure gives a topological order and the DAG is acyclic.

Counting instead of enumerating
-------------------------------
``route_find`` stores **every valid prefix** whose last city is an end city.  So for a prefix P:

    routes_one_way(P)   = 1 + sum over legal next flights g of routes_one_way(P + g)
    routes_round_trip(P) = [last city of P is a return city] + sum over g of routes_round_trip(P + g)

Both only depend on the last flight of P plus whatever the booking cap still needs to know, so the
recursion is memoised over ``(flight, cap state, remaining flights)`` and no flight limit is needed
for the search to terminate - the DAG is finite and acyclic.

Booking cap (same rule as ``simulate/booking_cap.py``, applied incrementally)
  * ``calendar``: at most ``cap`` departures per local calendar day of the departure airport.
    State: ``(day, count on that day)``.
  * ``rolling24``: never ``cap + 1`` departures inside a window shorter than 24 h, i.e. for every
    departure d at most ``cap`` departures lie in ``(d - 24h, d]``.  State: the departure times still
    inside the trailing 24 h window.  At most ``cap - 1`` of them can exist (a route that had more
    would have been rejected when the offending flight was added), so the state stays small.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

SECONDS_PER_DAY = 86400.0
CAP_MODES = ('none', 'calendar', 'rolling24')


@dataclass(frozen=True)
class Flight:
    """One scanned flight.  ``dep``/``arr`` are absolute epoch seconds (the ISO offsets are already
    applied), ``dep_day`` is the local calendar date at the departure airport."""
    index: int
    origin: str
    dest: str
    dep: float
    arr: float
    dep_day: str
    dep_label: str
    arr_label: str


@dataclass(frozen=True)
class Settings:
    """Search settings; ``max_flights=None`` means no flight limit.

    ``start_cities`` and ``return_cities`` are sets, so a city plus a radius can be expressed as the
    set of cities inside it (see ``coords.cities_within``).  A route may start in any start city -
    that is what ``find_one_way_routes`` does with a list of start cities.
    """
    start_cities: FrozenSet[str]
    return_cities: FrozenSet[str]
    min_gap_hours: float
    max_gap_hours: float
    max_flights: Optional[int] = None
    daily_cap: int = 3
    cap_mode: str = 'calendar'
    #: Cities the route must touch.  A route counts only once all of them have been visited; the
    #: start city of the route counts as visited.  Empty means no requirement.
    required_cities: FrozenSet[str] = frozenset()
    #: Groups of cities of which **any one** must be visited - that is how a required country works:
    #: one group holding every airport of that country.  Each group is one requirement.
    required_groups: Tuple[FrozenSet[str], ...] = ()

    def validate(self) -> None:
        if not self.start_cities:
            raise ValueError("start_cities must not be empty")
        if self.min_gap_hours < 0 or self.max_gap_hours <= self.min_gap_hours:
            raise ValueError(f"need 0 <= min_gap < max_gap, got {self.min_gap_hours}/{self.max_gap_hours}")
        if self.max_flights is not None and self.max_flights < 1:
            raise ValueError(f"max_flights must be >= 1 or None, got {self.max_flights}")
        if self.cap_mode not in CAP_MODES:
            raise ValueError(f"unknown cap_mode {self.cap_mode!r}, expected one of {CAP_MODES}")
        if self.cap_mode != 'none' and self.daily_cap < 1:
            raise ValueError(f"daily_cap must be >= 1, got {self.daily_cap}")


def parse_label(moment_iso: str) -> str:
    """``'Thu 13/03 08:35'`` - the stamp format of ``print_routes`` / ``simulate.routefmt``."""
    return datetime.fromisoformat(moment_iso).strftime('%a %d/%m %H:%M')


class FlightNetwork:
    """All flights of one scan, sorted by departure, with a per-origin index.

    Invariant: ``flights[i].index == i`` and ``flights`` is sorted by ``dep`` ascending.
    """

    def __init__(self, flights: Sequence[Flight]):
        if not flights:
            raise ValueError("flight network is empty")
        ordered = sorted(flights, key=lambda f: (f.dep, f.origin, f.dest))
        self.flights: List[Flight] = [
            Flight(i, f.origin, f.dest, f.dep, f.arr, f.dep_day, f.dep_label, f.arr_label)
            for i, f in enumerate(ordered)
        ]
        self.by_origin: Dict[str, List[int]] = {}
        for f in self.flights:
            self.by_origin.setdefault(f.origin, []).append(f.index)
        self._dep_by_origin = {city: [self.flights[i].dep for i in idx] for city, idx in self.by_origin.items()}

    @classmethod
    def from_graph(cls, graph) -> 'FlightNetwork':
        """Build from the ``nx.DiGraph`` shape of core/converter.py (edge attribute ``flights``)."""
        flights = []
        for origin, dest, attrs in graph.edges(data=True):
            for dep_iso, arr_iso in attrs['flights']:
                dep, arr = datetime.fromisoformat(dep_iso), datetime.fromisoformat(arr_iso)
                if arr <= dep:
                    raise ValueError(f"flight {origin} -> {dest} arrives before it departs: {dep_iso} {arr_iso}")
                flights.append(Flight(0, origin, dest, dep.timestamp(), arr.timestamp(), dep_iso[:10],
                                      parse_label(dep_iso), parse_label(arr_iso)))
        return cls(flights)

    @property
    def cities(self) -> List[str]:
        names = {f.origin for f in self.flights} | {f.dest for f in self.flights}
        return sorted(names)

    def departures_from(self, city: str, lo: float, hi: float) -> List[int]:
        """Flights leaving ``city`` with ``lo <= dep <= hi``, in departure order."""
        deps = self._dep_by_origin.get(city)
        if not deps:
            return []
        idx = self.by_origin[city]
        start = bisect.bisect_left(deps, lo)
        end = bisect.bisect_right(deps, hi)
        return idx[start:end]

    def successors(self, min_gap_hours: float, max_gap_hours: float) -> List[List[int]]:
        """DAG adjacency: ``out[i]`` are the flights that may follow flight ``i``."""
        lo_off, hi_off = min_gap_hours * 3600.0, max_gap_hours * 3600.0
        return [self.departures_from(f.dest, f.arr + lo_off, f.arr + hi_off) for f in self.flights]


# --- booking cap as an incremental state ---------------------------------------------------------

def cap_advance(state, flight: Flight, cap: int, cap_mode: str):
    """State after appending ``flight``, or ``None`` when the booking rule forbids it.

    ``state`` is the state of the flights already taken (``()`` before the first one).
    """
    if cap_mode == 'none':
        return ()
    if cap_mode == 'calendar':
        if state and state[0] == flight.dep_day:
            count = state[1] + 1
            return None if count > cap else (flight.dep_day, count)
        return (flight.dep_day, 1) if cap >= 1 else None
    if cap_mode == 'rolling24':
        # State invariant: exactly the departures of the prefix inside (dep(last) - 24h, dep(last)],
        # at most `cap` of them.  A later flight's window is contained in the current one, so
        # filtering the state is lossless - nothing older can come back into range.
        cutoff = flight.dep - SECONDS_PER_DAY
        window = tuple(t for t in state if t > cutoff)
        if len(window) >= cap:          # this flight would be the (cap+1)-th inside 24 h
            return None
        return window + (flight.dep,)
    raise ValueError(f"unknown cap_mode {cap_mode!r}, expected one of {CAP_MODES}")


def cap_state_of(path: Sequence[Flight], cap: int, cap_mode: str):
    """Cap state after taking ``path`` in order.  Raises if the path itself breaks the rule."""
    state = ()
    for flight in path:
        state = cap_advance(state, flight, cap, cap_mode)
        if state is None:
            raise ValueError(f"path violates the {cap_mode} cap of {cap} at flight {flight.index}")
    return state


# --- the dynamic program -------------------------------------------------------------------------

@dataclass(frozen=True)
class Counts:
    """Continuations of a prefix: routes that end anywhere (one way) and that end in a return city."""
    one_way: float
    round_trip: float


ZERO = Counts(0.0, 0.0)


@dataclass(frozen=True)
class Hop:
    """One candidate next flight with the number of full routes running through it."""
    flight: Flight
    counts: Counts


class RouteCounter:
    """Backward DP over the flight DAG for one ``Settings``.

    Preconditions: ``network`` non-empty, ``settings`` valid.  The counter is immutable apart from
    its memo, so the same instance can answer many prefixes.
    """

    def __init__(self, network: FlightNetwork, settings: Settings):
        settings.validate()
        self.network = network
        self.settings = settings
        self.succ = network.successors(settings.min_gap_hours, settings.max_gap_hours)
        self._memo: Dict[Tuple[int, tuple, Optional[int], int], Counts] = {}
        self._order = sorted(range(len(network.flights)), key=lambda i: network.flights[i].dep, reverse=True)

        # every requirement is a group of cities of which one must be visited; a required city is a
        # group of size one.  A city can belong to several groups (its own and its country's).
        self.groups = ([frozenset({city}) for city in sorted(settings.required_cities)]
                       + [frozenset(group) for group in settings.required_groups])
        self.required = self.groups                      # kept for the "is anything required" checks
        self._bit: Dict[str, int] = {}
        for position, group in enumerate(self.groups):
            for city in group:
                self._bit[city] = self._bit.get(city, 0) | (1 << position)
        self._full = (1 << len(self.groups)) - 1
        self._reach = [0] * len(network.flights)
        if self.required:
            # successors always depart later, so descending departure order is a topological order
            for i in self._order:
                mask = self._bit.get(network.flights[i].dest, 0)
                for j in self.succ[i]:
                    mask |= self._reach[j]
                self._reach[i] = mask

    def bit_of(self, city: str) -> int:
        return self._bit.get(city, 0)

    def mask_of(self, path: Sequence[int]) -> int:
        """Required cities already visited by ``path`` (its start city counts as visited)."""
        if not self.required or not path:
            return 0
        mask = self._bit.get(self.network.flights[path[0]].origin, 0)
        for index in path:
            mask |= self._bit.get(self.network.flights[index].dest, 0)
        return mask

    # -- core recursion -----------------------------------------------------------------------
    def value(self, index: int, cap_state, remaining: Optional[int], mask: int = 0) -> Counts:
        """Routes that start with a prefix whose last flight is ``index``.

        ``cap_state`` covers the whole prefix including ``index``; ``remaining`` is how many further
        flights may still be added (``None`` = unlimited); ``mask`` are the required cities the
        prefix has already visited.  Counts include the prefix itself, but only when every required
        city has been visited.
        """
        key = (index, cap_state, remaining, mask)
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        # nothing below this flight can complete the requirement -> the whole subtree is worthless
        if self.required and (mask | self._reach[index]) != self._full:
            self._memo[key] = ZERO
            return ZERO
        flight = self.network.flights[index]
        complete = mask == self._full
        one_way = 1.0 if complete else 0.0
        round_trip = 1.0 if complete and flight.dest in self.settings.return_cities else 0.0
        if remaining is None or remaining > 0:
            nxt = None if remaining is None else remaining - 1
            for j in self.succ[index]:
                state = cap_advance(cap_state, self.network.flights[j], self.settings.daily_cap,
                                    self.settings.cap_mode)
                if state is None:
                    continue
                sub = self.value(j, state, nxt, mask | self._bit.get(self.network.flights[j].dest, 0))
                one_way += sub.one_way
                round_trip += sub.round_trip
        result = Counts(one_way, round_trip)
        self._memo[key] = result
        return result

    # -- prefix driven API --------------------------------------------------------------------
    def candidate_indices(self, path: Sequence[int]) -> List[int]:
        """Flights that may extend ``path``.

        With an empty path these are all flights out of the start city with no time constraint,
        exactly like the start loop of ``find_one_way_routes``.
        """
        if self.settings.max_flights is not None and len(path) >= self.settings.max_flights:
            return []
        if not path:
            merged = [i for city in self.settings.start_cities for i in self.network.by_origin.get(city, [])]
            return sorted(merged, key=lambda i: (self.network.flights[i].dep, i))
        last = self.network.flights[path[-1]]
        lo = last.arr + self.settings.min_gap_hours * 3600.0
        hi = last.arr + self.settings.max_gap_hours * 3600.0
        return self.network.departures_from(last.dest, lo, hi)

    def hops(self, path: Sequence[int]) -> List[Hop]:
        """Legal next flights with their route counts, in departure order."""
        state = cap_state_of([self.network.flights[i] for i in path], self.settings.daily_cap,
                             self.settings.cap_mode)
        remaining = None if self.settings.max_flights is None else self.settings.max_flights - len(path) - 1
        base_mask = self.mask_of(path)
        out: List[Hop] = []
        for j in self.candidate_indices(path):
            flight = self.network.flights[j]
            nxt_state = cap_advance(state, flight, self.settings.daily_cap, self.settings.cap_mode)
            if nxt_state is None:
                continue
            mask = base_mask | self._bit.get(flight.dest, 0)
            if not path:                       # the route's own start city counts as visited
                mask |= self._bit.get(flight.origin, 0)
            out.append(Hop(flight, self.value(j, nxt_state, remaining, mask)))
        return out

    def totals(self, path: Sequence[int] = ()) -> Counts:
        """Sum over all legal next flights - the denominator of the per-hop shares."""
        hops = self.hops(path)
        return Counts(sum(h.counts.one_way for h in hops), sum(h.counts.round_trip for h in hops))

    def city_shares(self, path: Sequence[int] = ()) -> Dict[str, dict]:
        """Per destination city of the next hop: flights, counts and shares of the continuations.

        Postcondition: the shares over all cities sum to 1 for each mode whose total is positive.
        """
        hops = self.hops(path)
        totals = Counts(sum(h.counts.one_way for h in hops), sum(h.counts.round_trip for h in hops))
        grouped: Dict[str, dict] = {}
        for hop in hops:
            entry = grouped.setdefault(hop.flight.dest, {'city': hop.flight.dest, 'flights': [],
                                                         'one_way': 0.0, 'round_trip': 0.0})
            entry['flights'].append(hop.flight)
            entry['one_way'] += hop.counts.one_way
            entry['round_trip'] += hop.counts.round_trip
        for entry in grouped.values():
            entry['share_one_way'] = entry['one_way'] / totals.one_way if totals.one_way else 0.0
            entry['share_round_trip'] = entry['round_trip'] / totals.round_trip if totals.round_trip else 0.0
        return grouped
