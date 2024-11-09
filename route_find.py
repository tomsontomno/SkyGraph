import json

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
        if start_city in graph:
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


def find_one_way_routes(graph, start_cities, end_cities, min_time_gap_hours, max_time_gap_hours, flex_km=0, transfer_speed_kmh=50, distances_file="distances.json"):
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
    :param distances_file: Path to the distances.json file.
    :return: A list of valid routes.
    """
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
        transfer_time_hours = distance / transfer_speed_kmh
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
    else:
        raise ValueError(f"Unknown sort_by value: {sort_by}")


def load_settings(file_path):
    """
    Load the settings JSON file containing information about cities and countries.
    :param file_path: Path to the JSON file.
    :return: Dictionary with city and country data.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def print_routes(routes, output_mode="full", city_data=None, country_data=None, distances_file=None):
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

        return f"-- SELF ({transfer_duration_hours}h, {distance_str}) ->"

    if output_mode == "detailed":
        print(len(routes), "ROUTES FOUND (DETAILED OUTPUT):\n")
        for route in routes:
            start_time_str = route[0][2][0]
            start_time = parse_time(start_time_str)
            total_duration = parse_time(route[-1][2][1]) - start_time
            flight_time_total = timedelta()
            ground_time_total = timedelta()
            self_transfer_count = 0

            # Initial city and departure time
            city_sequence = [f"{route[0][0]} ({start_time.strftime('%d/%m %H:%M')})"]

            # Iterate over the flight segments
            for i in range(len(route)):
                flight = route[i]
                departure_city = flight[0]
                arrival_city = flight[1]
                departure_time = parse_time(flight[2][0])
                arrival_time = parse_time(flight[2][1])
                flight_duration = arrival_time - departure_time
                flight_time_total += flight_duration

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
                            f"--({round(flight_duration.total_seconds() / 3600, 1)}h)-> {arrival_city} {self_transfer_info} {next_departure_city} ({next_departure_time.strftime('%d/%m %H:%M')})"
                        )
                    else:
                        city_sequence.append(
                            f"--({round(flight_duration.total_seconds() / 3600, 1)}h)-> ({arrival_time.strftime('%d/%m %H:%M')}) {arrival_city}({round(ground_time.total_seconds() / 3600, 1)}h) ({next_departure_time.strftime('%d/%m %H:%M')})"
                        )
                else:
                    city_sequence.append(
                        f"--({round(flight_duration.total_seconds() / 3600, 1)}h)-> ({arrival_time.strftime('%d/%m %H:%M')}) {arrival_city}"
                    )

            print(" ".join(city_sequence))
            print(f"Total trip: {total_duration}")
            print(f"Number of flights: {len(route)}")
            print(f"Flight time: {flight_time_total}, Ground time: {ground_time_total}")
            print(f"Number of self-transfers: {self_transfer_count}")
            print("\n")
    elif output_mode == "full":
        print(len(routes), "ROUTES FOUND (FULL OUTPUT):\n")
        for route in routes:
            print("Route:")
            for segment in route:
                print(f"  {segment[0]} -> {segment[1]}, Departure: {segment[2][0]}, Arrival: {segment[2][1]}")
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
                    city_sequence.append(f"{departure_city} ({departure_time.strftime('%d/%m %H:%M')})")

                if i < len(route) - 1:
                    next_departure_city = route[i + 1][0]
                    next_departure_time = parse_time(route[i + 1][2][0])

                    if arrival_city != next_departure_city:
                        self_transfer_info = calculate_self_transfer_info(
                            arrival_city, next_departure_city, arrival_time, next_departure_time
                        )
                        city_sequence.append(
                            f"{arrival_city} (Arrival: {arrival_time.strftime('%d/%m %H:%M')}) {self_transfer_info} {next_departure_city} ({next_departure_time.strftime('%d/%m %H:%M')})"
                        )
                    else:
                        city_sequence.append(f"{arrival_city} ({next_departure_time.strftime('%d/%m %H:%M')})")
                else:
                    city_sequence.append(f"{arrival_city} ({arrival_time.strftime('%d/%m %H:%M')})")

            print(" -> ".join(city_sequence))
            print()




def main():
    graph = get_graph('graph.pkl')

    # Load the settings.json data
    settings = load_settings('settings.json')
    city_data = settings['city']
    country_data = settings['country']

    min_time_gap_hours = 2
    max_time_gap_hours = 15

    # Filter routes by the number of flights
    min_flights = 2
    max_flights = None

    # Sort the filtered routes by:
    # "start_city", "end_city", "departure_time", "arrival_time", "trip_duration", "flight_time", "ground_time", "percent_in_air", "percent_on_ground"
    # Choose output mode ('full', 'light', or 'detailed')
    sort_by = "percent_in_air"
    reverse_sort = False
    output_mode = "full"

    # Define start cities, end cities, minimum, and maximum time gaps
    start_cities_rt = ["Dortmund", "Frankfurt", "Cologne", "Eindhoven", "Hamburg", "Stuttgart"]  # , "Bremen", "Hamburg", "Stuttgart"
    start_cities_rt = ["Dortmund", "Eindhoven", "Frankfurt", "Cologne", "Stuttgart", "Bremen", "Hamburg",
                       "Karlsruhe/Baden-Baden", "Memmingen", "Nuremberg", "Friedrichshafen"]
    routes = find_round_trip_routes(graph, start_cities_rt, min_time_gap_hours, max_time_gap_hours)

    # one way settings:
    start_cities_ow = ["Dortmund", "Frankfurt", "Cologne", "Eindhoven", "Hamburg", "Stuttgart"]
    end_cities_ow = ["Zaragoza", "Santander", "Ibiza", "Gran Canaria", "Girona", "Fuerteventura", "Castellon", "Bilbao",
                     "Alicante", "Turku", "Lyon", "Nice", "Alghero", "Ancona", "Bari", "Brindisi", "Catania", "Comiso",
                     "Genoa", "Naples", "Olbia", "Perugia", "Pisa", "Rimini", "Trieste", "Turin", "Salerno", "Pristina",
                     "Debrecen", "Malta", "Marrakech", "Agadir", "Niš", "Chisinau", "Alesund", "Tromsø", "Stavanger",
                     "Haugesund", "Bergen", "Tashkent", "Samarkand", "Porto", "Funchal (Madeira)", "Lisbon", "Faro",
                     "Ljubljana", "Dubrovnik", "Split", "Podgorica", "Sarajevo", "Banja Luka", "Baku", "Malmö",
                     "Gothenburg", "Geneva", "Kefalonia", "Heraklion (Crete)",
                     "Chania (Crete)", "Athens", "Sofia", "Burgas", "Bishkek", "Skopje", "Ohrid", "Belgrade",
                     "Turkistan", "Astana", "Almaty", "Yerevan", "Tel Aviv", "Amman", "Aqaba", "Dubai", "Abu Dhabi",
                     "Riyadh", "Medina", "Jeddah", "Dammam", "Erbil", "Salalah", "Muscat", "Sohag", "Sharm El Sheikh",
                     "Cairo", "Hurghada", "Alexandria", "Male", "Leipzig", "Friedrichshafen"]
    end_citys_all = ['Dortmund', 'Eindhoven', 'Cologne', 'Frankfurt', 'Aberdeen', 'Abu Dhabi', 'Agadir', 'Alesund',
                     'Alexandria', 'Alghero', 'Alicante', 'Almaty', 'Amman', 'Ancona', 'Antalya', 'Aqaba', 'Astana',
                     'Athens', 'Bacau', 'Baku', 'Banja Luka', 'Barcelona', 'Bari', 'Basel (BSL)', 'Basel (MLH)',
                     'Belgrade', 'Bergen', 'Berlin', 'Bilbao', 'Billund', 'Birmingham', 'Bishkek', 'Bologna', 'Brasov',
                     'Bratislava', 'Bremen', 'Brindisi', 'Brussels', 'Brussels Charleroi', 'Bucharest', 'Budapest',
                     'Burgas', 'Cairo', 'Castellon', 'Catania', 'Chania (Crete)', 'Chisinau', 'Cluj-Napoca', 'Comiso',
                     'Constanta', 'Copenhagen', 'Corfu', 'Craiova', 'Dalaman', 'Dammam', 'Debrecen', 'Dubai',
                     'Dubrovnik', 'Erbil', 'Faro', 'Friedrichshafen', 'Fuerteventura', 'Funchal (Madeira)', 'Gdansk',
                     'Geneva', 'Genoa', 'Girona', 'Glasgow', 'Gothenburg', 'Gran Canaria', 'Grenoble', 'Hamburg',
                     'Haugesund', 'Heraklion (Crete)', 'Hurghada', 'Iasi', 'Ibiza', 'Istanbul', 'Izmir', 'Jeddah',
                     'Karlsruhe/Baden-Baden', 'Katowice', 'Kaunas', 'Kefalonia', 'Kos', 'Kosice', 'Krakow', 'Kutaisi',
                     'Larnaca', 'Leeds', 'Leipzig', 'Lisbon', 'Liverpool', 'Ljubljana', 'London Gatwick',
                     'London Luton', 'Lublin', 'Lyon', 'Madrid', 'Malaga', 'Male', 'Mallorca', 'Malmo', 'Malta',
                     'Marrakech', 'Marsa Alam', 'Medina', 'Memmingen', 'Milan Bergamo', 'Milan Malpensa', 'Muscat',
                     'Mykonos', 'Naples', 'Nice', 'Nis', 'Nuremberg', 'Ohrid', 'Olbia', 'Oslo', 'Oslo Sandefjord',
                     'Paris Beauvais', 'Paris Orly', 'Perugia', 'Pescara', 'Pisa', 'Plovdiv', 'Podgorica',
                     'Poprad-Tatry', 'Porto', 'Poznan', 'Prague', 'Pristina', 'Radom', 'Reykjavik', 'Rhodes', 'Riga',
                     'Rimini', 'Riyadh', 'Rome Ciampino', 'Rome Fiumicino', 'Rzeszow', 'Salalah', 'Salerno', 'Salzburg',
                     'Samarkand', 'Santander', 'Santorini', 'Sarajevo', 'Satu Mare', 'Sevilla', 'Sharm El Sheikh',
                     'Sibiu', 'Skiathos', 'Skopje', 'Sofia', 'Sohag', 'Split', 'Stavanger', 'Stockholm Arlanda',
                     'Stockholm Skavsta', 'Stuttgart', 'Suceava', 'Szczecin', 'Tallinn', 'Tashkent', 'Tenerife',
                     'Thessaloniki', 'Timisoara', 'Tirana', 'Tirgu-Mures', 'Trieste', 'Tromso', 'Trondheim', 'Turin',
                     'Turkistan', 'Turku', 'Tuzla', 'Valencia', 'Varna', 'Venice Marco Polo', 'Venice Treviso',
                     'Verona', 'Vienna', 'Vilnius', 'Warsaw', 'Wroclaw', 'Yerevan', 'Zakynthos', 'Zaragoza']
    end_citys_test = ['Dubai', "Alexandria", 'Yerevan', 'Heraklion (Crete)', 'Hurghada', 'Abu Dhabi']

    routes = find_one_way_routes(graph, start_cities_ow, end_citys_test, min_time_gap_hours, max_time_gap_hours, 150)

    filtered_routes = filter_routes_by_flights(routes, min_flights=min_flights, max_flights=max_flights)
    sorted_routes = sort_routes(filtered_routes, sort_by=sort_by, reverse=reverse_sort)

    # Print the routes in the selected mode
    print_routes(sorted_routes, output_mode, city_data=city_data, country_data=country_data)

    x = list(graph.edges)
    total = 0
    for each in x:
        total += len(each)

    print(total)


if __name__ == "__main__":
    main()
