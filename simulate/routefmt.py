"""Route formatting that mirrors ``core/route_find.py::print_routes(..., "light")`` but returns strings."""
from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence


def _stamp(moment: datetime) -> str:
    return moment.strftime('%a %d/%m %H:%M')


def self_transfer_info(distances: Mapping, arrival_city: str, next_departure_city: str,
                       arrival_time: datetime, next_departure_time: datetime) -> str:
    """Same text as print_routes' inner ``calculate_self_transfer_info``."""
    transfer_duration_hours = round((next_departure_time - arrival_time).total_seconds() / 3600, 1)
    distance = distances.get(arrival_city, {}).get(next_departure_city, None)
    distance_str = f"{distance:.1f}km" if distance else "unknown distance"
    return f"({_stamp(arrival_time)}) -- SELF ({transfer_duration_hours}h, {distance_str}) ->"


def format_route_light(route: Sequence, distances: Mapping) -> str:
    """``A (Thu 13/03 08:35) -> B (13/03 14:20) -> ...`` exactly like the light output mode.

    Precondition: ``route`` is a non-empty list of ``(from, to, [dep_iso, arr_iso])`` legs.
    Postcondition: one line, no trailing newline; intermediate stops show the *next departure* time,
    the final stop shows the arrival time (that is what print_routes does).
    """
    if not route:
        raise ValueError("cannot format an empty route")
    city_sequence = []
    for i, flight in enumerate(route):
        departure_city, arrival_city = flight[0], flight[1]
        departure_time = datetime.fromisoformat(flight[2][0])
        arrival_time = datetime.fromisoformat(flight[2][1])
        if i == 0:
            city_sequence.append(f"{departure_city} ({_stamp(departure_time)})")
        if i < len(route) - 1:
            next_departure_city = route[i + 1][0]
            next_departure_time = datetime.fromisoformat(route[i + 1][2][0])
            if arrival_city != next_departure_city:
                info = self_transfer_info(distances, arrival_city, next_departure_city, arrival_time, next_departure_time)
                city_sequence.append(
                    f"{arrival_city} (Arrival: {_stamp(arrival_time)}) {info} {next_departure_city} "
                    f"({_stamp(next_departure_time)})")
            else:
                city_sequence.append(f"{arrival_city} ({_stamp(next_departure_time)})")
        else:
            city_sequence.append(f"{arrival_city} ({_stamp(arrival_time)})")
    return " -> ".join(city_sequence)
