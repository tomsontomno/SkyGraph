import re


def curl_to_fetch(curl_command):
    # Extract URL
    url_match = re.search(r"curl\s+'(.*?)'", curl_command)
    url = url_match.group(1) if url_match else ''

    # Extract headers
    headers = {}
    header_matches = re.findall(r"-H\s+'(.*?)'", curl_command)
    for header in header_matches:
        key, value = header.split(': ', 1)
        headers[key] = value

    # Extract data (POST body)
    data_match = re.search(r"--data-raw\s+'(.*?)'", curl_command)
    data = data_match.group(1) if data_match else ''

    # Create the fetch request
    fetch_command = f"fetch('{url}', {{\n"
    fetch_command += "    method: 'POST',\n"
    fetch_command += "    headers: {\n"
    for key, value in headers.items():
        fetch_command += f"        '{key}': '{value}',\n"
    fetch_command = fetch_command.rstrip(",\n")  # Remove the trailing comma
    fetch_command += "\n    },\n"

    if data:
        fetch_command += f"    body: '{data}',\n"

    fetch_command += "})\n"
    fetch_command += ".then(response => response.text())\n"
    fetch_command += ".then(html => {\n"
    fetch_command += "    console.log(html);\n"
    fetch_command += "    document.open();\n"
    fetch_command += "    document.write(html);\n"
    fetch_command += "    document.close();\n"
    fetch_command += "})\n"
    fetch_command += ".catch(err => console.error(err));\n"

    return fetch_command


def save_to_file(fetch_code, filename="injection_request.js"):
    with open(filename, 'w') as file:
        file.write(fetch_code)
    print(f"Fetch code saved to {filename}")


"""
# FORMAT:
# [FlightCode]+[DepartureAirport]%23[DepartureDateTime]%7E[ArrivalAirport]%23[ArrivalDateTime]
# Example:
# W43386+FCO%2320241005T2140%7ECLJ%2320241006T0050

# YOU DONT NEED TO DO THIS EVERY TIME! There are no cookies saved, simply copy from injection_request.js and adjust
# only the code as shown in the example and in README_ghostflight_injection.txt
"""
if __name__ == "__main__":
    # Read the curl command from user input
    print("Please enter your curl command (press Enter twice to finish):")
    curl_command_lines = []

    while True:
        line = input()
        if not line:
            break
        curl_command_lines.append(line)

    curl_command = "\n".join(curl_command_lines)

    # Convert the curl command to a fetch command
    fetch_code = curl_to_fetch(curl_command)

    # Output the fetch command to the console
    print("\nGenerated fetch command:")
    print(fetch_code)

    # Save the fetch command to a file
    save_to_file(fetch_code)
