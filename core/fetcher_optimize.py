import os
import re
import json
import time
import pickle
import logging
import asyncio
import pytz
import requests
import aiohttp
import networkx as nx
from datetime import datetime, timedelta, timezone
import simpleaudio as sa
from pathlib import Path
from core import iata
from core.proxy_manager import ProxyManager
from core.cookies import save_cookies
from core.project_paths import ARCHIVE_FLIGHTGRAPH_DIR, GRAPH_PKL_FILE, SUCCESS_SOUND

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger()

# Global states
# Global configuration
n = 100  # Total proxy pool size
m = 1  # Requests per proxy per rotation cycle
proxy_manager = ProxyManager(window_size=n, requests_per_proxy=m)
MAX_CONCURRENT_REQUESTS = 3  # Concurrency limit to prevent rate limiting

global_wait_event = asyncio.Event()
global_wait_event.set()

cookie_lock = asyncio.Lock()


def update_proxies_file():
    api_token = os.getenv("WEBSHARE_API_TOKEN")
    proxies_url = os.getenv("WEBSHARE_PROXIES_URL")

    if not api_token or not proxies_url:
        logger.error("Missing environment variables: WEBSHARE_API_TOKEN or WEBSHARE_PROXIES_URL")
        return

    headers = {"Authorization": f"Token {api_token}"}

    try:
        logger.info("Fetching proxy list from remote provider...")
        response = requests.get(proxies_url, headers=headers, timeout=10)
        response.raise_for_status()

        project_root = Path(__file__).resolve().parents[2]
        proxy_file = project_root / "data" / "current" / "proxies.txt"
        proxy_file.parent.mkdir(parents=True, exist_ok=True)

        with open(proxy_file, "wb") as file:
            file.write(response.content)

        logger.info("Proxy list updated.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error updating proxy list: {e}")


def parse_utc_offset(offset_str):
    match = re.match(r'UTC([+-])(\d+)', offset_str)
    if match:
        sign, hours = match.groups()
        return timezone(timedelta(hours=int(hours) if sign == '+' else -int(hours)))
    return timezone.utc


def load_edges_from_file(file_path: Path):
    with file_path.open('r') as file:
        return json.load(file)


def load_from_file(
        filepath: Path = Path(__file__).resolve().parents[1] / "data" / "current" / "curl_request_data.json"):
    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return None

    try:
        with filepath.open("r", encoding="utf-8") as f:
            data = json.load(f)
            logger.info(f"Loaded data from {filepath}")
            return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {filepath}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while reading {filepath}: {e}")

    return None


def update_data_raw(data, origin=None, destination=None, departure=None):
    json_data = json.loads(data)
    if origin and origin != "NONE":
        json_data['origin'] = origin
    if destination and destination != "NONE":
        json_data['destination'] = destination
    if departure and departure != "NONE":
        json_data['departure'] = departure
    return json.dumps(json_data)


async def make_async_request(session, method, url, headers, data, cookies, origin, destination, departure_date,
                             timeout_duration=15, verbose=False):
    timeout = aiohttp.ClientTimeout(total=timeout_duration)
    cookie_dict = {k.strip(): v.strip() for k, v in (item.split('=', 1) for item in cookies.split(';') if '=' in item)}
    headers = dict(headers)
    headers.pop('Connection', None)
    max_retries = 10  # Retry limit for transient network errors

    for retry in range(max_retries):
        await global_wait_event.wait()
        proxy = proxy_manager.get_next_proxy()
        if not proxy:
            logger.warning("No proxies available, waiting...")
            await asyncio.sleep(1)
            continue

        proxy_url = f"http://{proxy['username']}:{proxy['password']}@{proxy['address']}:{proxy['port']}"
        try:
            async with session.request(
                    method, url, headers=headers, data=data, cookies=cookie_dict, proxy=proxy_url,
                    timeout=timeout, ssl=True, allow_redirects=False
            ) as response:
                result = await handle_response(response, origin, destination, departure_date, verbose)
                if result is not None:
                    if verbose:
                        logger.info(f"{departure_date}, {origin} -> {destination}: Status {response.status}")
                    return result
                elif response.status == 429:
                    logger.warning(f"{departure_date}, {origin} -> {destination}: 429, throttling...")
                    proxy_manager.set_proxy_on_cooldown(proxy, 5)  # Respect rate limit
                    await asyncio.sleep(2)
        except (aiohttp.ClientProxyConnectionError, asyncio.TimeoutError, aiohttp.ClientError) as e:
            if retry >= 5:
                logger.warning(f"{departure_date}, {origin} -> {destination}: Proxy error with {proxy['address']}:{proxy['port']}, retry {retry + 1}/{max_retries}")
            proxy_manager.set_proxy_on_cooldown(proxy, 1)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"{departure_date}, {origin} -> {destination}: Unexpected error {e}")
            proxy_manager.set_proxy_on_cooldown(proxy, 2)
            await asyncio.sleep(1)

    logger.error(f"{departure_date}, {origin} -> {destination}: Exhausted retries, failed")
    return None


async def handle_response(response, origin, destination, departure_date, verbose):
    if response.status == 200:
        return await response.json()
    elif response.status == 400:
        return 400
    elif response.status == 429:
        return None  # Trigger retry
    elif response.status == 500 and False:
        print(response)
        logger.info(f"{departure_date}, {origin} -> {destination}: Cookies expired")
        async with cookie_lock:
            save_cookies()
        return None
    else:
        if verbose:
            logger.info(f"{departure_date}, {origin} -> {destination}: Status {response.status}")
        return None


async def async_custom_request(session, origin, destination, departure_date, saved_data, verbose=False):
    if not saved_data:
        logger.error("No saved curl data provided.")
        return None

    method = saved_data['method']
    url = saved_data['url']
    headers = saved_data['headers']
    data = update_data_raw(saved_data['data'], origin, destination, departure_date)
    cookies = saved_data['cookies']

    return await make_async_request(
        session, method, url, headers, data, cookies,
        origin, destination, departure_date, verbose=verbose
    )


async def fetch_flight_data(semaphore, session, origin, destination, departure_date_str, ready_up_time, now, saved_data,
                            verbose=False):
    async with semaphore:
        while True:
            flight_data_json = await async_custom_request(
                session, iata.city2iata[origin], iata.city2iata[destination],
                departure_date_str, saved_data, verbose=verbose
            )
            if flight_data_json is not None:
                break
            logger.info(f"{departure_date_str}, {origin} -> {destination}: Retrying due to failure")
            await asyncio.sleep(2)

        if flight_data_json and flight_data_json != 400:
            outbound_flights = flight_data_json.get('flightsOutbound', [])
            flights = []
            for flight in outbound_flights:
                try:
                    dep_time = parse_flight_time(flight, 'departure', departure_date_str, 'departureOffsetText')
                    arr_date_str = flight.get('arrivalDateIso') or departure_date_str
                    arr_time = parse_flight_time(flight, 'arrival', arr_date_str, 'arrivalOffsetText')
                    if dep_time and arr_time:
                        time_diff = (dep_time.astimezone(timezone.utc) - now).total_seconds() / 3600
                        if time_diff >= ready_up_time:
                            flights.append([dep_time.isoformat(), arr_time.isoformat()])
                except Exception as e:
                    logger.error(f"Error parsing flight {flight}: {e}")
            if flights:
                return origin, destination, flights
        return None


def parse_flight_time(flight, key, date_str, offset_key):
    time_str = flight.get(key)
    offset_str = flight.get(offset_key)
    if time_str and offset_str:
        tz = parse_utc_offset(offset_str)
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p").replace(tzinfo=tz)
        if key == 'arrival' and dt < datetime.strptime(f"{date_str} {flight.get('departure')}",
                                                       "%Y-%m-%d %I:%M %p").replace(tzinfo=tz):
            dt += timedelta(days=1)
        return dt
    return None


async def build_flight_graph(city_pairs, start_date, days, ready_up_time,
                             max_concurrent_requests=MAX_CONCURRENT_REQUESTS, verbose=False):
    graph = nx.DiGraph()
    utc_plus_2 = pytz.FixedOffset(120)
    now = datetime.now(utc_plus_2)
    semaphore = asyncio.Semaphore(max_concurrent_requests)

    saved_data = load_from_file()
    if not saved_data:
        logger.error("Failed to load cURL request data. Aborting graph build.")
        return graph

    total_tasks = sum(len(destinations) * len(days) for destinations in city_pairs.values())
    completed_tasks = 0
    reported_milestones = set()

    async def process_task(task):
        nonlocal completed_tasks
        result = await task
        completed_tasks += 1

        progress_percent = int((completed_tasks / total_tasks) * 100)
        milestone = (progress_percent // 10) * 10

        if milestone not in reported_milestones and milestone <= 100:
            reported_milestones.add(milestone)
            logger.info(f"{milestone}% - {completed_tasks} out of {total_tasks} completed")

        return result

    async with aiohttp.ClientSession() as session:
        tasks = [
            process_task(
                fetch_flight_data(
                    semaphore, session, origin, destination,
                    (start_date + timedelta(days=day_offset)).strftime("%Y-%m-%d"),
                    ready_up_time, now, saved_data, verbose=verbose
                )
            )
            for origin, destinations in city_pairs.items()
            for destination in destinations
            for day_offset in days
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, tuple):
                origin, destination, flights = result
                if graph.has_edge(origin, destination):
                    graph[origin][destination]['flights'].extend(flights)
                else:
                    graph.add_edge(origin, destination, flights=flights)
            elif isinstance(result, Exception):
                logger.error(f"Task failed with exception: {result}")

    GRAPH_PKL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with GRAPH_PKL_FILE.open("wb") as f:
        pickle.dump(graph, f)

    logger.info(f"Graph saved to {GRAPH_PKL_FILE}. Max concurrent requests: {max_concurrent_requests}")
    return graph


def graph_to_json(graph):
    result = {}

    for origin in graph.nodes:
        destination_data = {}

        for destination, attributes in graph[origin].items():
            destination_data[destination] = attributes['flights']

        result[origin] = destination_data

    return result


async def async_run_scan(filepath: Path, verbose=False, num_days=None):
    city_pairs = load_edges_from_file(filepath)
    start_date = datetime.now()
    ready_up_time = 0  # Capture all flights
    days = num_days or [0, 1, 2, 3]

    logger.info(f"Scanning {filepath} with {len(city_pairs)} origins, {sum(len(d) for d in city_pairs.values())} routes, {len(days)} days")

    # Build flight graph
    flight_graph = await build_flight_graph(city_pairs, start_date, days, ready_up_time, verbose=verbose)
    flight_json = graph_to_json(flight_graph)

    # Save JSON to archive
    json_file_path = ARCHIVE_FLIGHTGRAPH_DIR / f"{datetime.now():%Y_%m_%d_T%H_%M_%S}_flight_graph.json"
    with json_file_path.open("w", encoding="utf-8") as f:
        json.dump(flight_json, f, indent=4)
    logger.info(f"Flight graph JSON archived at {json_file_path}")

    # Save Pickle to current
    with GRAPH_PKL_FILE.open("wb") as f:
        pickle.dump(flight_graph, f)
    logger.info(f"Flight graph pickle saved to {GRAPH_PKL_FILE}")

    return json_file_path


async def main(wait_before_start_seconds=0, verbose=False, days=None):
    start_time = time.time()
    update_proxies_file()
    days = days or [0, 1, 2, 3]
    current_time = datetime.now() + timedelta(seconds=wait_before_start_seconds)
    logger.info(f"RUNNING AT: {current_time.strftime('%H:%M:%S')}")
    await asyncio.sleep(wait_before_start_seconds)

    project_root = Path(__file__).resolve().parents[1]
    edges_path = project_root / "data" / "current" / "edges.json"
    result = await async_run_scan(edges_path, verbose, days)
    if os.path.exists(result):
        with open(result, "r") as f:
            data = json.load(f)
            if data:
                wave_obj = sa.WaveObject.from_wave_file(str(SUCCESS_SOUND))
                play_obj = wave_obj.play()
                play_obj.wait_done()
                logger.info("All tasks completed successfully.")
            else:
                logger.warning("Result file empty.")
    else:
        logger.error("Scan failed.")

    elapsed_time = time.time() - start_time
    logger.info(f"Execution completed in {int(elapsed_time // 60)} minute(s) and {int(elapsed_time % 60)} second(s).")



if __name__ == "__main__":
    asyncio.run(main(verbose=False))
