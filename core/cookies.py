import os
import shlex
import json
import logging
from core import project_paths

# Setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SAVE_FILE = project_paths.CURL_REQUEST_FILE


def parse_curl_command(curl_command):
    """
    Parses a cURL command string to extract HTTP method, URL, headers, data, and cookies.

    Args:
        curl_command (str): The raw cURL command string.

    Returns:
        tuple: (method, url, headers, data, cookies)
    """
    curl_command = curl_command.replace('\\\n', ' ')
    tokens = shlex.split(curl_command)
    method = 'GET'
    url = ''
    headers = {}
    cookies = None
    data = None

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == 'curl':
            i += 1
            continue
        elif token.startswith(('http', "'http", '"http')):
            url = token.strip("'\"")
            i += 1
        elif token in ('-H', '--header'):
            header = tokens[i + 1].strip("'\"")
            key, value = header.split(':', 1)
            headers[key.strip()] = value.strip()
            i += 2
        elif token in ('--data', '--data-raw', '--data-binary'):
            data = tokens[i + 1].strip("'\"")
            method = 'POST'
            i += 2
        elif token == '-X':
            method = tokens[i + 1].upper()
            i += 2
        elif token in ('-b', '--cookie'):
            cookies = tokens[i + 1].strip("'\"")
            i += 2
        else:
            i += 1
    return method, url, headers, data, cookies


def extract_cookies(headers):
    """
    Extracts cookies from a headers dictionary and removes the 'cookie' key.

    Args:
        headers (dict): Dictionary of HTTP headers.

    Returns:
        dict: Extracted cookies as key-value pairs.
    """
    cookies_str = headers.get('cookie', '')
    cookies = {}
    if cookies_str:
        for cookie in cookies_str.split('; '):
            if '=' in cookie:
                key, value = cookie.split('=', 1)
                if key not in ('OptanonAlertBoxClosed', 'OptanonConsent'):
                    cookies[key] = value
    headers.pop('cookie', None)
    return cookies


def update_data_raw(data, origin=None, destination=None, departure=None):
    try:
        json_data = json.loads(data)
        if origin and origin != "NONE":
            json_data['origin'] = origin
        if destination and destination != "NONE":
            json_data['destination'] = destination
        if departure and departure != "NONE":
            json_data['departure'] = departure
        return json.dumps(json_data)
    except json.JSONDecodeError:
        logger.error("Invalid JSON data format.")
        return data


def get_curl_command_input():
    logger.info("Loading cURL from file if exists")
    curl_path = "curl_input.txt"
    if os.path.exists(curl_path):
        with open(curl_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        logger.info("No curl_input.txt found, initiating manual entry mode.")
        print("Please paste your cURL command below. Type 'END' on a new line to finish:")
        curl_lines = []
        while True:
            line = input()
            if line.strip().upper() == "END":
                break
            curl_lines.append(line)
        return "\n".join(curl_lines)


def save_to_file(data):
    SAVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SAVE_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    logger.info(f"Saved cURL data to {SAVE_FILE}")


def load_from_file():
    if SAVE_FILE.exists():
        with SAVE_FILE.open('r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_cookies(curl_command=None):
    if curl_command is None:
        curl_command = get_curl_command_input()

    if curl_command.strip():
        method, url, headers, data, cookies = parse_curl_command(curl_command)
        save_to_file({
            'method': method,
            'url': url,
            'headers': headers,
            'data': data,
            'cookies': cookies
        })
    else:
        previous_data = load_from_file()
        if previous_data:
            logger.info("No new data entered. Using previously saved cookies.")
        else:
            logger.warning("No previous data found. Nothing to save.")


if __name__ == '__main__':
    save_cookies()
