"""The two search copies must be core/route_find.py plus exactly the documented edits.

The edits are spelled out below as literal old/new snippets and applied to the current
core/route_find.py; the result must equal the copy byte for byte.  If core/route_find.py changes,
this test tells you the copies are stale.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'core' / 'route_find.py'
COPY_ORIGINAL = ROOT / 'simulate' / 'route_find_original.py'
COPY_FIXED = ROOT / 'simulate' / 'route_find_fixed.py'

HEADER_ORIGINAL = '''"""Verbatim copy of core/route_find.py (the ORIGINAL, buggy search) for the bug-impact simulation.

Differences to core/route_find.py, and nothing else (checked by simulate/tests/test_copies.py):
  * find_round_trip_routes / find_one_way_routes accept ``max_flights=None``; the DFS returns once
    ``len(route) >= max_flights``.  Every valid prefix is stored before that check, so the cap is
    semantically identical to ``filter_routes_by_flights(routes, max_flights=max_flights)``.
  * The settings-driven ``main()`` entry point is dropped.

The bug is kept on purpose: ``graph[a][b].values()`` yields the whole ``flights`` list as its single
value, so only ``flights[0]`` (the earliest flight of the edge) is ever used.
"""
'''

HEADER_FIXED = '''"""Copy of core/route_find.py WITH the flight-iteration fix, for the bug-impact simulation.

Differences to core/route_find.py, and nothing else (checked by simulate/tests/test_copies.py):
  * Fix (DFS and start loop): iterate over ``graph[a][b]['flights']`` so every flight of an edge
    is a candidate; ``flight_times`` is then one ``[departure, arrival]`` pair and is appended to
    the route as-is.
  * find_round_trip_routes / find_one_way_routes accept ``max_flights=None``; the DFS returns once
    ``len(route) >= max_flights``.  Every valid prefix is stored before that check, so the cap is
    semantically identical to ``filter_routes_by_flights(routes, max_flights=max_flights)``.
  * The settings-driven ``main()`` entry point is dropped.
"""
'''

# (old, new) snippets; each old snippet must occur exactly once in core/route_find.py
COMMON_EDITS = [
    (
        "def find_round_trip_routes(graph, cities, min_time_gap_hours, max_time_gap_hours, flex_km=0, transfer_speed_kmh=50,\n"
        "                           distances_file=distances_json_file):",
        "def find_round_trip_routes(graph, cities, min_time_gap_hours, max_time_gap_hours, flex_km=0, transfer_speed_kmh=50,\n"
        "                           distances_file=distances_json_file, max_flights=None):",
    ),
    (
        "        flex_km, transfer_speed_kmh, distances_file=distances_file\n    )",
        "        flex_km, transfer_speed_kmh, distances_file=distances_file, max_flights=max_flights\n    )",
    ),
    (
        "def find_one_way_routes(graph, start_cities, end_cities, min_time_gap_hours, max_time_gap_hours, flex_km=0,\n"
        "                        transfer_speed_kmh=50, reverse=False, distances_file=distances_json_file):",
        "def find_one_way_routes(graph, start_cities, end_cities, min_time_gap_hours, max_time_gap_hours, flex_km=0,\n"
        "                        transfer_speed_kmh=50, reverse=False, distances_file=distances_json_file, max_flights=None):",
    ),
    (
        "                valid_routes.append(route[:])  # Save the current partial route\n"
        "\n"
        "        # Explore all outgoing flights from the current city and nearby cities\n",
        "                valid_routes.append(route[:])  # Save the current partial route\n"
        "\n"
        "        # Depth cap (simulation only): every valid prefix was saved above, so returning here is\n"
        "        # semantically identical to filter_routes_by_flights(routes, max_flights=max_flights).\n"
        "        if max_flights is not None and len(route) >= max_flights:\n"
        "            return\n"
        "\n"
        "        # Explore all outgoing flights from the current city and nearby cities\n",
    ),
]

FIX_EDITS = [
    (
        "                    neighbor_values = graph[nearby_city][neighbor].values()\n"
        "                    for flight_times in neighbor_values:\n"
        "                        if isinstance(flight_times, list) and isinstance(flight_times[0], list):\n"
        "                            # Unpack the flight times\n"
        "                            departure_time_str = flight_times[0][0]\n"
        "                            arrival_time_str = flight_times[0][1]\n",
        "                    neighbor_values = graph[nearby_city][neighbor]['flights']\n"
        "                    for flight_times in neighbor_values:\n"
        "                        if isinstance(flight_times, list) and isinstance(flight_times[0], str):\n"
        "                            # Unpack the flight times\n"
        "                            departure_time_str = flight_times[0]\n"
        "                            arrival_time_str = flight_times[1]\n",
    ),
    (
        "                                route.append((nearby_city, neighbor, flight_times[0]))\n",
        "                                route.append((nearby_city, neighbor, flight_times))\n",
    ),
    (
        "                for flight_times in graph[start_city][neighbor].values():\n"
        "                    if isinstance(flight_times, list) and isinstance(flight_times[0], list):\n"
        "                        # Unpack the flight times\n"
        "                        departure_time_str = flight_times[0][0]\n"
        "                        arrival_time_str = flight_times[0][1]\n",
        "                for flight_times in graph[start_city][neighbor]['flights']:\n"
        "                    if isinstance(flight_times, list) and isinstance(flight_times[0], str):\n"
        "                        # Unpack the flight times\n"
        "                        departure_time_str = flight_times[0]\n"
        "                        arrival_time_str = flight_times[1]\n",
    ),
    (
        "                        dfs(neighbor, [(start_city, neighbor, flight_times[0])], arrival_time)\n",
        "                        dfs(neighbor, [(start_city, neighbor, flight_times)], arrival_time)\n",
    ),
]

MAIN_MARKER = "\n\ndef main():\n"


def _apply(text: str, edits) -> str:
    for old, new in edits:
        count = text.count(old)
        if count != 1:
            raise AssertionError(f"expected the snippet exactly once in core/route_find.py, found {count}:\n{old}")
        text = text.replace(old, new)
    return text


def expected_original_copy(core_source: str) -> str:
    body = core_source[:core_source.index(MAIN_MARKER)] + "\n"
    return HEADER_ORIGINAL + _apply(body, COMMON_EDITS)


def expected_fixed_copy(core_source: str) -> str:
    body = core_source[:core_source.index(MAIN_MARKER)] + "\n"
    return HEADER_FIXED + _apply(_apply(body, COMMON_EDITS), FIX_EDITS)


def test_original_copy_is_core_plus_depth_cap():
    core = CORE.read_text(encoding='utf-8')
    assert MAIN_MARKER in core, "core/route_find.py has no main() - the copy rules need updating"
    assert COPY_ORIGINAL.read_text(encoding='utf-8') == expected_original_copy(core), \
        "simulate/route_find_original.py differs from core/route_find.py + documented edits"


def test_fixed_copy_is_core_plus_depth_cap_plus_fix():
    core = CORE.read_text(encoding='utf-8')
    assert COPY_FIXED.read_text(encoding='utf-8') == expected_fixed_copy(core), \
        "simulate/route_find_fixed.py differs from core/route_find.py + documented edits + fix"


def test_bug_is_present_in_core():
    core = CORE.read_text(encoding='utf-8')
    assert core.count("graph[nearby_city][neighbor].values()") == 1
    assert core.count("graph[start_city][neighbor].values()") == 1
