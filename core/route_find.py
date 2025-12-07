import json
from datetime import datetime, timedelta
import pickle
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "current"
distances_json_file = DATA_DIR / "distances.json"


def get_graph(file_path):
    """
    Deserializes the flight graph from a pickle file.

    Args:
        file_path (Path): Path to the pickle file.

    Returns:
        nx.DiGraph: The loaded flight graph.
    """
    with open(file_path, 'rb') as f:
        graph = pickle.load(f)
    return graph


def parse_time(time_str):
    """
    Parse a time string in the format 'YYYY-MM-DDTHH:MM:SS+02:00' and return a datetime object.
    """
    try:
        return datetime.fromisoformat(time_str)
    except TypeError:
        raise ValueError(f"Expected a string for time parsing, but got: {type(time_str)}")


def find_round_trip_routes(graph, cities, min_time_gap_hours, max_time_gap_hours, flex_km=0, transfer_speed_kmh=50,
                           distances_file=distances_json_file):
    """
    Identifies valid round-trip itineraries based on time constraints.
    Wraps find_one_way_routes by setting start_cities as end_cities.

    Args:
        graph (nx.DiGraph): The flight graph.
        cities (list): List of allowed start/end cities.
        min_time_gap_hours (float): Minimum layover/stay duration.
        max_time_gap_hours (float): Maximum layover/stay duration.
        flex_km (int): Radius for city clustering.
        transfer_speed_kmh (int): Assumed ground transport speed.
        distances_file (Path): Path to distance matrix JSON.

    Returns:
        list: Valid round-trip routes.
    """
    # Set start_cities as end_cities for round-trip routes
    return find_one_way_routes(
        graph, cities, cities,
        min_time_gap_hours, max_time_gap_hours,
        flex_km, transfer_speed_kmh, distances_file=distances_file
    )


def find_one_way_routes(graph, start_cities, end_cities, min_time_gap_hours, max_time_gap_hours, flex_km=0,
                        transfer_speed_kmh=50, reverse=False, distances_file=distances_json_file):
    """
    Find all valid one-way routes in the graph starting from one of the start_cities
    and ending in one of the end_cities, ensuring a minimum and maximum time gap between flights.
    Includes city clustering based on proximity defined by `flex_km`, and calculates transfer time
    based on the distance between cities and the given transfer speed.

    :param graph: The flight graph (directed).
    :param start_cities: List of start cities (nodes).
    :param end_cities: List of end cities (nodes).
    :param min_time_gap_hours: Minimum time gap in hours between consecutive flights.
    :param max_time_gap_hours: Maximum time gap in hours between consecutive flights.
    :param flex_km: Flexibility range in kilometers for clustering nearby cities.
    :param transfer_speed_kmh: Speed (in km/h) at which transfers between cities can be made.
    :param reverse: True to flip start and end cities, so that routes from end to start cities are searched.
    :param distances_file: Path to the distances.json file.
    :return: A list of valid routes.
    """
    if reverse:
        temp_cities = start_cities
        start_cities = end_cities
        end_cities = temp_cities

    # Load the distances file
    with open(distances_file, 'r') as f:
        distances = json.load(f)

    valid_routes = []
    min_time_gap = timedelta(hours=min_time_gap_hours)
    max_time_gap = timedelta(hours=max_time_gap_hours)

    def get_nearby_cities(city):
        """
        Get a list of cities within flex_km of the given city based on the distances.json file.

        :param city: The current city.
        :return: List of nearby cities including the city itself.
        """
        if city not in distances:
            return [city]  # Return the city itself if no distances are available
        return [
                   nearby_city
                   for nearby_city, distance in distances[city].items()
                   if distance <= flex_km
               ] + [city]

    def calculate_transfer_time(city_a, city_b):
        """
        Calculate the minimum transfer time between two cities based on the distance
        and the given transfer speed.

        :param city_a: Starting city.
        :param city_b: Destination city.
        :return: Minimum transfer time as a timedelta.
        """
        if city_a not in distances or city_b not in distances[city_a]:
            return timedelta(0)  # Default to zero if no distance is found
        distance = distances[city_a][city_b]
        # Add 1 hour buffer for airport procedures + transport time
        transfer_time_hours = (distance / transfer_speed_kmh) + 1
        return timedelta(hours=transfer_time_hours)

    def dfs(city, route, current_time):
        """
        Depth-first search (DFS) to find all valid one-way routes.

        :param city: Current city (node).
        :param route: List of edges representing the current route.
        :param current_time: Current time (arrival time at the current city).
        """
        # Always save the current route (valid partial route)
        if len(route) > 0:
            if city in end_cities:
                valid_routes.append(route[:])  # Save the current partial route

        # Explore all outgoing flights from the current city and nearby cities
        nearby_cities = get_nearby_cities(city)
        for nearby_city in nearby_cities:
            if nearby_city in graph:
                for neighbor in graph.neighbors(nearby_city):
                    neighbor_values = graph[nearby_city][neighbor].values()
                    for flight_times in neighbor_values:
                        if isinstance(flight_times, list) and isinstance(flight_times[0], list):
                            # Unpack the flight times
                            departure_time_str = flight_times[0][0]
                            arrival_time_str = flight_times[0][1]

                            departure_time = parse_time(departure_time_str)
                            arrival_time = parse_time(arrival_time_str)

                            # Calculate transfer time
                            transfer_time = calculate_transfer_time(city, nearby_city)

                            # Check if the flight falls within the valid time window
                            if current_time + min_time_gap + transfer_time <= departure_time <= current_time + max_time_gap + transfer_time:
                                # Add the flight to the route and continue DFS
                                route.append((nearby_city, neighbor, flight_times[0]))
                                dfs(neighbor, route, arrival_time)
                                route.pop()  # Backtracking
                        else:
                            raise ValueError(f"Unexpected data format for flight times: {flight_times}")

    # Main logic: Start DFS directly from the specified start cities
    for start_city in start_cities:
        if start_city in graph:
            for neighbor in graph.neighbors(start_city):
                for flight_times in graph[start_city][neighbor].values():
                    if isinstance(flight_times, list) and isinstance(flight_times[0], list):
                        # Unpack the flight times
                        departure_time_str = flight_times[0][0]
                        arrival_time_str = flight_times[0][1]

                        departure_time = parse_time(departure_time_str)
                        arrival_time = parse_time(arrival_time_str)

                        # Start DFS with the first valid flight
                        dfs(neighbor, [(start_city, neighbor, flight_times[0])], arrival_time)
                    else:
                        raise ValueError(f"Unexpected data format for flight times: {flight_times}")

    return valid_routes


def filter_routes_by_flights(routes, min_flights=None, max_flights=None):
    """
    Filters the routes based on the minimum and/or maximum number of flights.

    :param routes: List of routes to filter.
    :param min_flights: Minimum number of flights required in the route.
    :param max_flights: Maximum number of flights allowed in the route.
    :return: Filtered list of routes.
    """
    filtered_routes = []

    for route in routes:
        num_flights = len(route)
        if (min_flights is None or num_flights >= min_flights) and (max_flights is None or num_flights <= max_flights):
            filtered_routes.append(route)

    return filtered_routes


def sort_routes(routes, sort_by="departure_time", reverse=False):
    """
    Sort the routes based on the specified criteria.

    :param routes: List of routes to be sorted.
    :param sort_by: Criteria to sort by ('start_city', 'end_city', 'departure_time', 'arrival_time').
    :param reverse: Boolean, True for descending order, False for ascending.
    :return: Sorted list of routes.
    """

    if sort_by == "start_city":
        return sorted(routes, key=lambda route: route[0][0], reverse=reverse)
    elif sort_by == "end_city":
        return sorted(routes, key=lambda route: route[-1][1], reverse=reverse)
    elif sort_by == "departure_time":
        return sorted(routes, key=lambda route: parse_time(route[0][2][0]), reverse=reverse)
    elif sort_by == "arrival_time":
        return sorted(routes, key=lambda route: parse_time(route[-1][2][1]), reverse=reverse)
    elif sort_by == "trip_duration":
        return sorted(routes, key=lambda route: parse_time(route[-1][2][1]) - parse_time(route[0][2][0]),
                      reverse=reverse)
    elif sort_by == "flight_time":
        return sorted(routes, key=lambda route: sum((parse_time(seg[2][1]) - parse_time(seg[2][0]) for seg in route),
                                                    timedelta()), reverse=reverse)
    elif sort_by == "ground_time":
        return sorted(routes, key=lambda route: (parse_time(route[-1][2][1]) - parse_time(route[0][2][0])) - sum(
            (parse_time(seg[2][1]) - parse_time(seg[2][0]) for seg in route), timedelta()), reverse=reverse)
    elif sort_by == "percent_in_air":
        return sorted(routes, key=lambda route: sum((parse_time(seg[2][1]) - parse_time(seg[2][0]) for seg in route),
                                                    timedelta()) / (
                                                        parse_time(route[-1][2][1]) - parse_time(route[0][2][0])),
                      reverse=reverse)
    elif sort_by == "percent_on_ground":
        return sorted(routes, key=lambda route: 1 - (
                sum((parse_time(seg[2][1]) - parse_time(seg[2][0]) for seg in route), timedelta()) / (
                parse_time(route[-1][2][1]) - parse_time(route[0][2][0]))), reverse=reverse)
    elif sort_by == "number_of_flights":
        return sorted(routes, key=lambda route: len(route), reverse=reverse)
    else:
        raise ValueError(f"Unknown sort_by value: {sort_by}")


def load_json(file_path):
    """
    Load a JSON file.
    :param file_path: Path to the JSON file.
    :return: Dictionary with city and country data.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def print_routes(routes, output_mode="full", city_data=None, country_data=None, distances_file=distances_json_file):
    # Load distances from the file if provided
    distances = {}
    if distances_file:
        with open(distances_file, "r") as f:
            distances = json.load(f)

    def calculate_self_transfer_info(arrival_city, next_departure_city, arrival_time, next_departure_time):
        """
        Calculate the self-transfer duration and distance.

        :param arrival_city: City where the flight arrives.
        :param next_departure_city: City where the next flight departs.
        :param arrival_time: Arrival time at the city.
        :param next_departure_time: Departure time from the next city.
        :return: Formatted self-transfer information string.
        """
        transfer_duration = next_departure_time - arrival_time
        transfer_duration_hours = round(transfer_duration.total_seconds() / 3600, 1)

        # Get distance between the arrival city and the next departure city
        distance = distances.get(arrival_city, {}).get(next_departure_city, None)
        distance_str = f"{distance:.1f}km" if distance else "unknown distance"

        return f"({arrival_time.strftime('%a %d/%m %H:%M')}) -- SELF ({transfer_duration_hours}h, {distance_str}) ->"

    if output_mode == "detailed":
        print(len(routes), "ROUTES FOUND (DETAILED OUTPUT):\n")
        for route in routes:
            start_time_str = route[0][2][0]
            start_time = parse_time(start_time_str)
            total_duration = parse_time(route[-1][2][1]) - start_time
            flight_time_total = timedelta()
            ground_time_total = timedelta()
            self_transfer_count = 0

            unique_cities = set()
            unique_countries = set()
            revisited_cities = set()
            revisited_countries = set()
            visa_countries = set()
            non_eu_countries = set()
            new_cities = set()
            new_countries = set()

            # Initial city and departure time
            city_sequence = [f"{route[0][0]} ({start_time.strftime('%a %d/%m %H:%M')})"]

            # Iterate over flight segments
            for i in range(len(route)):
                flight = route[i]
                departure_city = flight[0]
                arrival_city = flight[1]
                departure_time = parse_time(flight[2][0])
                arrival_time = parse_time(flight[2][1])
                flight_duration = arrival_time - departure_time
                flight_time_total += flight_duration

                try:  # Handle potential inconsistencies in legacy preferences data
                    # Update departure city data
                    unique_cities.add(departure_city)
                    unique_countries.add(city_data[departure_city]['country'])
                    if departure_city not in revisited_cities:
                        if not city_data[departure_city]['visited']:
                            new_cities.add(departure_city)
                        else:
                            revisited_cities.add(departure_city)
                            new_cities.discard(departure_city)

                    if city_data[departure_city]['country'] not in revisited_countries:
                        if not country_data[city_data[departure_city]['country']]['visited']:
                            new_countries.add(city_data[departure_city]['country'])
                        else:
                            revisited_countries.add(city_data[departure_city]['country'])
                            new_countries.discard(city_data[departure_city]['country'])

                    if not country_data[city_data[departure_city]['country']]['eu_member']:
                        non_eu_countries.add(city_data[departure_city]['country'])

                    if country_data[city_data[departure_city]['country']]['visa_needed']:
                        visa_countries.add(city_data[departure_city]['country'])

                    # Update arrival city data
                    unique_cities.add(arrival_city)
                    unique_countries.add(city_data[arrival_city]['country'])
                    if arrival_city not in revisited_cities:
                        if not city_data[arrival_city]['visited']:
                            new_cities.add(arrival_city)
                        else:
                            revisited_cities.add(arrival_city)
                            new_cities.discard(arrival_city)

                    if city_data[arrival_city]['country'] not in revisited_countries:
                        if not country_data[city_data[arrival_city]['country']]['visited']:
                            new_countries.add(city_data[arrival_city]['country'])
                        else:
                            revisited_countries.add(city_data[arrival_city]['country'])
                            new_countries.discard(city_data[arrival_city]['country'])

                    if not country_data[city_data[arrival_city]['country']]['eu_member']:
                        non_eu_countries.add(city_data[arrival_city]['country'])

                    if country_data[city_data[arrival_city]['country']]['visa_needed']:
                        visa_countries.add(city_data[arrival_city]['country'])

                    # Handle the next flight for ground time
                    if i < len(route) - 1:
                        next_departure_city = route[i + 1][0]
                        next_departure_time = parse_time(route[i + 1][2][0])
                        ground_time = next_departure_time - arrival_time
                        ground_time_total += ground_time

                        if arrival_city != next_departure_city:
                            self_transfer_count += 1
                            self_transfer_info = calculate_self_transfer_info(
                                arrival_city, next_departure_city, arrival_time, next_departure_time
                            )
                            city_sequence.append(
                                f"--({round(flight_duration.total_seconds() / 3600, 1)}h)-> ({arrival_time.strftime('%a %d/%m %H:%M')}) {arrival_city} {self_transfer_info} {next_departure_city} ({next_departure_time.strftime('%a %d/%m %H:%M')})"
                            )
                        else:
                            city_sequence.append(
                                f"--({round(flight_duration.total_seconds() / 3600, 1)}h)-> ({arrival_time.strftime('%a %d/%m %H:%M')}) {arrival_city}({round(ground_time.total_seconds() / 3600, 1)}h) ({next_departure_time.strftime('%a %d/%m %H:%M')})"
                            )
                    else:
                        city_sequence.append(
                            f"--({round(flight_duration.total_seconds() / 3600, 1)}h)-> ({arrival_time.strftime('%a %d/%m %H:%M')}) {arrival_city}"
                        )

                    # Add final arrival city to statistics
                    unique_cities.add(arrival_city)
                    unique_countries.add(city_data[arrival_city]['country'])
                    if not city_data[arrival_city]['visited']:
                        new_cities.add(arrival_city)
                    else:
                        revisited_cities.add(arrival_city)

                    if not country_data[city_data[arrival_city]['country']]['visited']:
                        new_countries.add(city_data[arrival_city]['country'])
                    else:
                        revisited_countries.add(city_data[arrival_city]['country'])

                    if not country_data[city_data[arrival_city]['country']]['eu_member']:
                        non_eu_countries.add(city_data[arrival_city]['country'])

                    if country_data[city_data[arrival_city]['country']]['visa_needed']:
                        visa_countries.add(city_data[arrival_city]['country'])
                except KeyError:
                    pass

            percent_in_air = (flight_time_total.total_seconds() / total_duration.total_seconds()) * 100
            percent_on_ground = 100 - percent_in_air

            # Final detailed output
            print(" ".join(city_sequence))
            print(f"Total trip: {total_duration}")
            print(f"Number of flights: {len(route)}")
            print(f"Flight time: {flight_time_total}, Ground time: {ground_time_total}")
            print(f"In air: {percent_in_air:.2f}%, On ground: {percent_on_ground:.2f}%")
            print(f"Unique cities: {len(unique_cities)}, Names: {', '.join(unique_cities)}")
            print(
                f"Revisited cities: {len(revisited_cities)}, Names: {', '.join(revisited_cities) if revisited_cities else 'None'}")
            print(f"New cities: {len(new_cities)}, Names: {', '.join(new_cities)}")
            print(f"Visited countries: {len(unique_countries)}, Names: {', '.join(unique_countries)}")
            print(
                f"Revisited countries: {len(revisited_countries)}, Names: {', '.join(revisited_countries) if revisited_countries else 'None'}")
            print(f"New countries: {len(new_countries)}, Names: {', '.join(new_countries)}")
            print(f"Non-EU countries: {len(non_eu_countries)}, Names: {', '.join(non_eu_countries)}")
            print(f"Visa needed: {'Yes, for ' + ', '.join(visa_countries) if visa_countries else 'No'}")
            print(f"Number of self-transfers: {self_transfer_count}")
            print("\n")

    elif output_mode == "light":
        print(len(routes), "ROUTES FOUND (LIGHT OUTPUT):\n")
        for route in routes:
            city_sequence = []
            for i in range(len(route)):
                flight = route[i]
                departure_city = flight[0]
                arrival_city = flight[1]
                departure_time = parse_time(flight[2][0])
                arrival_time = parse_time(flight[2][1])

                if i == 0:
                    city_sequence.append(f"{departure_city} ({departure_time.strftime('%a %d/%m %H:%M')})")

                if i < len(route) - 1:
                    next_departure_city = route[i + 1][0]
                    next_departure_time = parse_time(route[i + 1][2][0])

                    if arrival_city != next_departure_city:
                        self_transfer_info = calculate_self_transfer_info(
                            arrival_city, next_departure_city, arrival_time, next_departure_time
                        )
                        city_sequence.append(
                            f"{arrival_city} (Arrival: {arrival_time.strftime('%a %d/%m %H:%M')}) {self_transfer_info} {next_departure_city} ({next_departure_time.strftime('%a %d/%m %H:%M')})"
                        )
                    else:
                        city_sequence.append(f"{arrival_city} ({next_departure_time.strftime('%a %d/%m %H:%M')})")
                else:
                    city_sequence.append(f"{arrival_city} ({arrival_time.strftime('%a %d/%m %H:%M')})")

            print(" -> ".join(city_sequence))
            print()
    print(len(routes), "ROUTES FOUND\n")


def main():
    graph = get_graph(DATA_DIR / 'graph.pkl')
    settings = load_json(DATA_DIR / 'settings.json')

    # Load preferences/custom data from JSON data
    preferences = load_json(DATA_DIR / "preferences.json")
    city_data = preferences['city']
    country_data = preferences['country']

    # Extract common settings
    mode = settings['mode']
    min_time_gap_hours = settings['min_time_gap_hours']
    max_time_gap_hours = settings['max_time_gap_hours']
    min_flights = settings['min_flights']
    max_flights = settings['max_flights']
    sort_by = settings['sort_by']
    reverse_sort = settings['reverse_sort']
    output_mode = settings['output_mode']
    flex_km = settings['flex_km']
    transfer_speed_kmh = settings['transfer_speed_kmh']

    if mode == 'ow':
        start_cities = settings['start_cities']
        end_cities = settings['end_cities']
        flipped = settings['flip_start_end']
        routes = find_one_way_routes(
            graph, start_cities, end_cities, min_time_gap_hours, max_time_gap_hours, flex_km=flex_km,
            transfer_speed_kmh=transfer_speed_kmh, reverse=flipped
        )

    else:  # if mode == 'rt'
        cities = settings['cities']
        routes = find_round_trip_routes(
            graph, cities, min_time_gap_hours, max_time_gap_hours,
            flex_km=flex_km, transfer_speed_kmh=transfer_speed_kmh
        )

    # Filter and sort routes
    filtered_routes = filter_routes_by_flights(routes, min_flights=min_flights, max_flights=max_flights)
    sorted_routes = sort_routes(filtered_routes, sort_by=sort_by, reverse=reverse_sort)

    # Print routes
    print_routes(sorted_routes, output_mode, city_data=city_data, country_data=country_data)

    x = list(graph.edges)
    total = 0
    for each in x:
        total += len(each)
    print(f"Total flights in graph: {total}")


if __name__ == "__main__":
    main()
