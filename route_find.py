import networkx as nx
from datetime import datetime, timedelta
import pickle


def get_graph(file_path):
    """
    Function to load a pickled graph from a file.
    :param file_path: The path to the pickled graph file.
    :return: The loaded graph object.
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


def find_round_trip_routes(graph, start_cities, min_time_gap_hours, max_time_gap_hours, allow_revisit=True):
    """
    Find all valid routes in the graph starting from one of the start_cities, ensuring
    a minimum and maximum time gap between consecutive flights, allowing cities to be revisited.

    :param graph: The flight graph (directed).
    :param start_cities: List of start cities (nodes).
    :param min_time_gap_hours: Minimum time gap in hours between consecutive flights.
    :param max_time_gap_hours: Maximum time gap in hours between consecutive flights.
    :param allow_revisit: Boolean flag indicating whether cities can be revisited in the same route.
    :return: A list of valid routes.
    """
    valid_routes = []
    min_time_gap = timedelta(hours=min_time_gap_hours)
    max_time_gap = timedelta(hours=max_time_gap_hours)

    def dfs(city, route, current_time, visited=None):
        """
        Depth-first search (DFS) to find all valid routes.

        :param city: Current city (node).
        :param route: List of edges representing the current route.
        :param current_time: Current time (arrival time at the current city).
        :param visited: Set of cities already visited (used to prevent cycles when allow_revisit=False).
        """
        # If not allowing revisits, keep track of visited cities
        if visited is None:
            visited = set()

        if not allow_revisit and city in visited:
            return  # Skip if the city was already visited and revisits are not allowed

        # Add the city to visited set if revisits are not allowed
        if not allow_revisit:
            visited.add(city)

        # If we are back in a start city and have a valid route, the route is complete
        if city in start_cities and len(route) > 0:
            valid_routes.append(route[:])  # Store a copy of the current route
            return

        # Explore all outgoing flights from the current city
        for neighbor in graph.neighbors(city):
            for flight_times in graph[city][neighbor].values():
                if isinstance(flight_times, list) and isinstance(flight_times[0], list):
                    # Unpack the inner list
                    departure_time_str = flight_times[0][0]
                    arrival_time_str = flight_times[0][1]

                    departure_time = parse_time(departure_time_str)
                    arrival_time = parse_time(arrival_time_str)

                    # Check if the flight can be taken (departure is within the time gap range)
                    if current_time + min_time_gap <= departure_time <= current_time + max_time_gap:
                        # Continue DFS with the new city
                        route.append((city, neighbor, flight_times[0]))  # Add current flight to the route
                        dfs(neighbor, route, arrival_time, visited.copy())  # Pass a copy of the visited set
                        route.pop()  # Backtrack
                else:
                    raise ValueError(f"Unexpected data format for flight times: {flight_times}")

    # Start DFS from each start city
    for start_city in start_cities:
        for neighbor in graph.neighbors(start_city):
            for flight_times in graph[start_city][neighbor].values():
                if isinstance(flight_times, list) and isinstance(flight_times[0], list):
                    # Unpack the inner list
                    departure_time_str = flight_times[0][0]
                    arrival_time_str = flight_times[0][1]

                    departure_time = parse_time(departure_time_str)
                    arrival_time = parse_time(arrival_time_str)

                    # Start DFS with each valid flight
                    dfs(neighbor, [(start_city, neighbor, flight_times[0])], arrival_time)
                else:
                    raise ValueError(f"Unexpected data format for flight times: {flight_times}")

    return valid_routes


def find_one_way_routes(graph, start_cities, end_cities, min_time_gap_hours, max_time_gap_hours):
    """
    Find all valid one-way routes in the graph starting from one of the start_cities
    and ending in one of the end_cities, ensuring a minimum and maximum time gap between flights.

    :param graph: The flight graph (directed).
    :param start_cities: List of start cities (nodes).
    :param end_cities: List of end cities (nodes).
    :param min_time_gap_hours: Minimum time gap in hours between consecutive flights.
    :param max_time_gap_hours: Maximum time gap in hours between consecutive flights.
    :return: A list of valid routes.
    """
    valid_routes = []
    min_time_gap = timedelta(hours=min_time_gap_hours)
    max_time_gap = timedelta(hours=max_time_gap_hours)

    def dfs(city, route, current_time):
        """
        Depth-first search (DFS) to find all valid one-way routes.

        :param city: Current city (node).
        :param route: List of edges representing the current route.
        :param current_time: Current time (arrival time at the current city).
        """
        # If we are in an end city, the route is complete
        if city in end_cities:
            valid_routes.append(route[:])  # Store a copy of the current route
            return

        # Explore all outgoing flights from the current city
        for neighbor in graph.neighbors(city):
            for flight_times in graph[city][neighbor].values():
                if isinstance(flight_times, list) and isinstance(flight_times[0], list):
                    # Unpack the inner list
                    departure_time_str = flight_times[0][0]
                    arrival_time_str = flight_times[0][1]

                    departure_time = parse_time(departure_time_str)
                    arrival_time = parse_time(arrival_time_str)

                    # Check if the flight can be taken (departure is within the time gap range)
                    if current_time + min_time_gap <= departure_time <= current_time + max_time_gap:
                        # Continue DFS with the new city
                        route.append((city, neighbor, flight_times[0]))  # Add current flight to the route
                        dfs(neighbor, route, arrival_time)
                        route.pop()  # Backtrack
                else:
                    raise ValueError(f"Unexpected data format for flight times: {flight_times}")

    # Start DFS from each start city
    for start_city in start_cities:
        for neighbor in graph.neighbors(start_city):
            for flight_times in graph[start_city][neighbor].values():
                if isinstance(flight_times, list) and isinstance(flight_times[0], list):
                    # Unpack the inner list
                    departure_time_str = flight_times[0][0]
                    arrival_time_str = flight_times[0][1]

                    departure_time = parse_time(departure_time_str)
                    arrival_time = parse_time(arrival_time_str)

                    # Start DFS with each valid flight
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
        return sorted(routes, key=lambda route: route[0][0], reverse=reverse)  # Sort by starting city name
    elif sort_by == "end_city":
        return sorted(routes, key=lambda route: route[-1][1], reverse=reverse)  # Sort by ending city name
    elif sort_by == "departure_time":
        return sorted(routes, key=lambda route: parse_time(route[0][2][0]), reverse=reverse)  # Sort by departure time
    elif sort_by == "arrival_time":
        return sorted(routes, key=lambda route: parse_time(route[-1][2][1]), reverse=reverse)  # Sort by arrival time
    else:
        raise ValueError(f"Unknown sort_by value: {sort_by}")


def print_routes(routes, output_mode="full"):
    """
    Prints the routes based on the output mode.

    :param routes: List of routes to print.
    :param output_mode: 'full' for detailed route info, 'light' for city-only sequence with times.
    """
    if output_mode == "full":
        print(len(routes), "ROUTES FOUND (FULL OUTPUT):\n")
        for route in routes:
            print("Route:")
            for segment in route:
                print(f"  {segment[0]} -> {segment[1]}, Departure: {segment[2][0]}, Arrival: {segment[2][1]}")
            print("\n")
    elif output_mode == "light":
        print(len(routes), "ROUTES FOUND (LIGHT OUTPUT):\n")
        for route in routes:
            # Get the departure time from the start city
            departure_time_str = route[0][2][0]
            departure_time = parse_time(departure_time_str)
            city_sequence = [
                f"{route[0][0]} ({departure_time.strftime('%d/%m %H:%M')})"]  # Start city with departure time

            for i in range(len(route) - 1):
                arrival_time_str = route[i][2][1]  # Arrival at the current city
                departure_time_str = route[i + 1][2][0]  # Departure from the next city

                arrival_time = parse_time(arrival_time_str)
                departure_time = parse_time(departure_time_str)

                # Calculate time spent at the current city (i.e., time between arrival and next departure)
                time_spent = departure_time - arrival_time
                hours_spent = time_spent.total_seconds() / 3600  # Convert to hours

                # Append the next city and the time spent at the current city
                city_sequence.append(f"{route[i][1]} ({round(hours_spent, 1)}h)")

            # Add the final destination (last city) with its arrival time
            arrival_time_str = route[-1][2][1]
            arrival_time = parse_time(arrival_time_str)
            city_sequence.append(f"{route[-1][1]} ({arrival_time.strftime('%d/%m %H:%M')})")

            # Print the light output format with time spent
            print(" -> ".join(city_sequence))
            print()


if __name__ == "__main__":
    graph = get_graph('graph.pkl')

    # Define start cities, end cities, minimum, and maximum time gaps
    start_cities_rt = ["Cologne", "Dortmund", "Eindhoven", "Frankfurt"]
    # start_cities_rt = ["Cologne", "Dortmund", "Frankfurt"]

    # one way settings:
    start_cities_ow = ["Cologne", "Dortmund", "Eindhoven", "Frankfurt", "Brussels", "Stuttgart", "Karlsruhe/Baden-Baden", "Memmingen", "Nuremberg"]
    end_cities_ow = ["Santorini", "Larnaca", "Heraklion (Crete)", "Athens", "Nice", "Olbia", "Cairo", "Mykonos", "Ibiza", "Alghero", "Catania", "Tromso", "Reykjavik", "Zakynthos"]

    min_time_gap_hours = 3.5
    max_time_gap_hours = 24

    # Find all valid routes
    routes = find_round_trip_routes(graph, start_cities_rt, min_time_gap_hours, max_time_gap_hours)
    # routes = find_one_way_routes(graph, start_cities, end_cities, min_time_gap_hours, max_time_gap_hours)

    # Filter routes by the number of flights
    min_flights = None  # Minimum number of flights required (optional, None for disregard)
    max_flights = None  # Maximum number of flights allowed (optional, None for disregard)

    filtered_routes = filter_routes_by_flights(routes, min_flights=min_flights, max_flights=max_flights)

    # Sort the filtered routes
    sort_by = "arrival_time"  # Options: 'start_city', 'end_city', 'departure_time', 'arrival_time'
    reverse_sort = False  # Change to True for descending order

    sorted_routes = sort_routes(filtered_routes, sort_by=sort_by, reverse=reverse_sort)

    # Choose output mode ('full' or 'light')
    output_mode = "light"  # 'full' for detailed output

    # Print the routes in the selected mode
    print_routes(sorted_routes, output_mode)

    x = list(graph.edges)
    total = 0
    for each in x:
        total += len(each)

    print(total)