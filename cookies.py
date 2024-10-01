import shlex
import json
import os

# Define the path to the saved JSON file
SAVE_FILE = 'curl_request_data.json'


def parse_curl_command(curl_command):
    """
    Parses the provided curl command string and extracts method, URL, headers, and data.
    """
    curl_command = curl_command.replace('\\\n', ' ')
    tokens = shlex.split(curl_command)
    method = 'GET'
    url = ''
    headers = {}
    data = None

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == 'curl':
            i += 1
            continue
        elif token.startswith('http') or token.startswith("'http") or token.startswith('"http'):
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
        else:
            i += 1
    return method, url, headers, data


def extract_cookies(headers):
    """
    Extracts cookies from the 'cookie' header and returns them as a dictionary,
    excluding the 'OptanonAlertBoxClosed' cookie.
    """
    cookies_str = headers.get('cookie', '')
    cookies = {}
    if cookies_str:
        for cookie in cookies_str.split('; '):
            if '=' in cookie:
                key, value = cookie.split('=', 1)
                # Exclude the 'OptanonAlertBoxClosed' cookie
                if key != 'OptanonAlertBoxClosed' and key != 'OptanonConsent':
                    cookies[key] = value
    headers.pop('cookie', None)
    return cookies


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


def get_curl_command_input():
    """
    Reads a multi-line curl command input from the user until an empty line is encountered.
    """
    print("Paste your curl command (end with an empty line):")
    curl_lines = []
    while True:
        try:
            line = input()
            if line.strip() == '':
                break  # Empty line signals end of input
            curl_lines.append(line)
        except EOFError:
            break  # End of file (Ctrl+D)

    return '\n'.join(curl_lines)


def save_to_file(data):
    """
    Saves the curl request data (url, headers, cookies, etc.) to a JSON file.
    """
    with open(SAVE_FILE, 'w') as f:
        json.dump(data, f, indent=4)


def load_from_file():
    """
    Loads the curl request data from a JSON file, if it exists.
    """
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, 'r') as f:
            return json.load(f)
    return None


def save_cookies():
    # Enter new curl command
    curl_command = get_curl_command_input()
    method, url, headers, data = parse_curl_command(curl_command)
    cookies = extract_cookies(headers)

    # Save the original curl command to the file
    save_to_file({
        'method': method,
        'url': url,
        'headers': headers,
        'data': data,
        'cookies': cookies
    })


# Run the main function
if __name__ == '__main__':
    save_cookies()