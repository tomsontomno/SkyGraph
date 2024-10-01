import asyncio
import aiohttp
import pickle
import iata
import json
import networkx as nx
from datetime import datetime, timedelta, timezone
import re
import os
import pytz


def parse_utc_offset(offset_str):
    match = re.match(r'UTC([+-])(\d+)', offset_str)
    if match:
        sign, hours = match.groups()
        hours = int(hours)
        offset = timedelta(hours=hours)
        if sign == '-':
            offset = -offset
        return timezone(offset)
    else:
        # Default to UTC if parsing fails
        return timezone.utc


def load_edges_from_file(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)


def load_from_file():
    """
    Loads the curl request data from a JSON file, if it exists.
    """
    SAVE_FILE = 'curl_request_data.json'
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, 'r') as f:
            return json.load(f)
    return None


def update_data_raw(data, origin=None, destination=None, departure=None):
    """
    Updates the 'origin', 'destination', and 'departure' fields in the data payload (JSON).
    """
    try:
        json_data = json.loads(data)

        # Only update if new values are provided
        if origin and origin != "NONE":
            json_data['origin'] = origin
        if destination and destination != "NONE":
            json_data['destination'] = destination
        if departure and departure != "NONE":
            json_data['departure'] = departure

        return json.dumps(json_data)

    except json.JSONDecodeError:
        print("Invalid JSON data format.")
        return data


from datetime import datetime


def format_flight_response(response_json, origin, destination, departure_date):
    """
    Formats the result of the flight search into a concise string with departure times.

    Args:
        response_json (dict): The JSON response from the server.
        origin (str): The IATA code of the origin city.
        destination (str): The IATA code of the destination city.
        departure_date (str): The departure date in 'YYYY-MM-DD' format.

    Returns:
        str: A formatted string indicating the result of the flight search with departure times.
    """
    # Convert departure_date to a readable format (e.g., "03. Oct")
    departure_date_formatted = datetime.strptime(departure_date, "%Y-%m-%d").strftime("%d. %b")

    # Check if the response is None or no flights were found
    if response_json is None:
        return f"{departure_date_formatted}, {origin} -> {destination}: FAIL"

    outbound_flights = response_json.get('flightsOutbound', [])

    if not outbound_flights:
        return f"{departure_date_formatted}, {origin} -> {destination}: FAIL"

    # Extract departure times
    departure_times = []
    for flight in outbound_flights:
        departure_time_str = flight.get('departure')
        if departure_time_str:
            # Convert the departure time into 24-hour format (e.g., 08:45)
            departure_time = datetime.strptime(departure_time_str, "%I:%M %p").strftime("%H:%M")
            departure_times.append(departure_time)

    # Format the response based on the number of flights and their times
    num_flights = len(outbound_flights)

    if num_flights == 1:
        return f"{departure_date_formatted}, {origin} -> {destination}: SUCCESS, 1 flight found at {departure_times[0]} local time"
    else:
        times_formatted = ', '.join(departure_times[:-1]) + f" and {departure_times[-1]}"
        return f"{departure_date_formatted}, {origin} -> {destination}: SUCCESS, {num_flights} flights found at {times_formatted} local time"


async def make_async_request(session, method, url, headers, data, cookies, origin, destination, departure_date, timeout_duration=30):
    """
    Sends an asynchronous HTTP request using aiohttp, with custom timeout handling.
    Returns the parsed response JSON and prints the formatted message.
    """
    timeout = aiohttp.ClientTimeout(total=timeout_duration)  # Set a custom timeout
    if method.upper() == 'POST':
        try:
            json_data = json.loads(data)
            async with session.post(url, headers=headers, json=json_data, cookies=cookies, timeout=timeout) as response:
                if response.status == 200:
                    response_json = await response.json()
                    print(format_flight_response(response_json, origin, destination, departure_date))  # Print the formatted result
                    return response_json  # Return the parsed response JSON
                else:
                    print(format_flight_response(None, origin, destination, departure_date))  # Print the fail message
                    return None
        except json.JSONDecodeError:
            async with session.post(url, headers=headers, data=data, cookies=cookies, timeout=timeout) as response:
                if response.status == 200:
                    response_json = await response.json()
                    print(format_flight_response(response_json, origin, destination, departure_date))  # Print the formatted result
                    return response_json  # Return the parsed response JSON
                else:
                    print(format_flight_response(None, origin, destination, departure_date))  # Print the fail message
                    return None
        except asyncio.TimeoutError:
            print(f"{departure_date}, {origin} -> {destination}: TIMEOUT")  # Print timeout message
            return None
    else:
        try:
            async with session.request(method, url, headers=headers, cookies=cookies, timeout=timeout) as response:
                if response.status == 200:
                    response_json = await response.json()
                    print(format_flight_response(response_json, origin, destination, departure_date))  # Print the formatted result
                    return response_json  # Return the parsed response JSON
                else:
                    print(format_flight_response(None, origin, destination, departure_date))  # Print the fail message
                    return None
        except asyncio.TimeoutError:
            print(f"{departure_date}, {origin} -> {destination}: TIMEOUT")  # Print timeout message
            return None


async def async_custom_request(session, origin, destination, departure_date):
    """
    Asynchronous version of custom_request using aiohttp.
    """
    saved_data = load_from_file()
    if not saved_data:
        print("No saved curl data found. Please run the script and provide a curl command first.")
        return None

    # Use saved data
    method = saved_data['method']
    url = saved_data['url']
    headers = saved_data['headers']
    data = saved_data['data']
    cookies = saved_data['cookies']

    # Update the data payload with the new values (origin, destination, departure)
    if method.upper() == 'POST' and data:
        data = update_data_raw(data, origin=origin, destination=destination, departure=departure_date)

    # Make the request and pass the additional parameters
    response_json = await make_async_request(session, method, url, headers, data, cookies, origin, destination, departure_date)
    return response_json


async def fetch_flight_data(semaphore, session, origin, destination, departure_date_str, ready_up_time, now):
    async with semaphore:
        await asyncio.sleep(0.04)
        flight_data_json = await async_custom_request(session, iata.city2iata[origin], iata.city2iata[destination],
                                                      departure_date_str)
        if flight_data_json:
            outbound_flights = flight_data_json.get('flightsOutbound', [])
            flights = []
            for flight in outbound_flights:
                # Parse departure time
                departure_date_str = flight.get('departureDateIso')
                departure_time_str = flight.get('departure')
                departure_offset_str = flight.get('departureOffsetText')

                if departure_date_str and departure_time_str and departure_offset_str:
                    # Parse time zone
                    departure_tz = parse_utc_offset(departure_offset_str)
                    # Combine date and time
                    departure_datetime_naive = datetime.strptime(
                        f"{departure_date_str} {departure_time_str}", "%Y-%m-%d %I:%M %p"
                    )
                    # Make the datetime object timezone-aware
                    departure_datetime = departure_datetime_naive.replace(tzinfo=departure_tz)
                else:
                    continue  # Skip if necessary data is missing

                # Parse arrival time
                arrival_date_str = flight.get('arrivalDateIso') or departure_date_str
                arrival_time_str = flight.get('arrival')
                arrival_offset_str = flight.get('arrivalOffsetText')

                if arrival_date_str and arrival_time_str and arrival_offset_str:
                    arrival_tz = parse_utc_offset(arrival_offset_str)
                    arrival_datetime_naive = datetime.strptime(
                        f"{arrival_date_str} {arrival_time_str}", "%Y-%m-%d %I:%M %p"
                    )
                    arrival_datetime = arrival_datetime_naive.replace(tzinfo=arrival_tz)

                    # Adjust for overnight flights (if arrival time is before departure time)
                    if arrival_datetime < departure_datetime:
                        arrival_datetime += timedelta(days=1)

                else:
                    continue  # Skip if necessary data is missing

                # Calculate the time difference in UTC
                time_diff = (
                    departure_datetime.astimezone(timezone.utc) - now
                ).total_seconds() / 3600  # Convert to hours

                # Check if the flight departs at least 'ready_up_time' hours from now
                if time_diff >= ready_up_time:
                    # Store flight times as ISO formatted strings including the local time zone offset
                    flights.append([
                        departure_datetime.isoformat(),
                        arrival_datetime.isoformat()
                    ])
            if flights:
                return origin, destination, flights
        else:
            return None


async def build_flight_graph(city_pairs, start_date, num_days, ready_up_time, max_concurrent_requests=2):
    graph = nx.DiGraph()  # Directed graph
    utc_plus_2 = pytz.FixedOffset(120)
    now = datetime.now(utc_plus_2)

    # Limit the number of concurrent requests with a semaphore
    semaphore = asyncio.Semaphore(max_concurrent_requests)

    async with aiohttp.ClientSession() as session:
        tasks = []
        for origin, destinations in city_pairs.items():
            for destination in destinations:
                for day_offset in range(0, num_days + 1):
                    date = start_date + timedelta(days=day_offset)
                    departure_date_str = date.strftime("%Y-%m-%d")
                    task = fetch_flight_data(semaphore, session, origin, destination, departure_date_str, ready_up_time,
                                             now)
                    tasks.append(task)

        results = await asyncio.gather(*tasks)

        for result in results:
            if result:
                origin, destination, flights = result
                if flights:
                    if graph.has_edge(origin, destination):
                        graph[origin][destination]['flights'].extend(flights)
                    else:
                        graph.add_edge(origin, destination, flights=flights)

    graph_file = "graph.pkl"

    with open(graph_file, 'wb') as f:
        pickle.dump(graph, f)
    print(f"Graph saved to {graph_file}")
    return graph


def graph_to_json(graph):
    graph_dict = {}
    for origin, destination, data in graph.edges(data=True):
        if origin not in graph_dict:
            graph_dict[origin] = {}
        graph_dict[origin][destination] = data['flights']
    return graph_dict


def main():
    city_pairs = load_edges_from_file("edges.json")

    start_date = datetime.now()
    num_days = 3  # Fetch flights for today + 3 upcoming days
    ready_up_time = 0  # Disregard flights departing in less than 3 hours

    # Build the flight graph asynchronously
    flight_graph = asyncio.run(build_flight_graph(city_pairs, start_date, num_days, ready_up_time))

    # Convert graph to JSON
    flight_json = graph_to_json(flight_graph)

    # Define the subfolder where you want to save the file
    subfolder = "flight_graph"

    # Ensure the subfolder exists
    os.makedirs(subfolder, exist_ok=True)

    # Define UTC+2 timezone
    utc_plus_2 = pytz.FixedOffset(120)
    now = datetime.now(utc_plus_2)

    # Create the full path for the file (subfolder + filename)
    file_path = os.path.join(subfolder, now.strftime("%Y_%m_%d_T%H_%M_%S_flight_graph.json"))

    # Save the file to the subfolder
    with open(file_path, "w") as f:
        json.dump(flight_json, f, indent=4)

    print(f"Flight graph saved to {file_path}")


if __name__ == "__main__":
    main()