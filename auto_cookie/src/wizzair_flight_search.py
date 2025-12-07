import re
from seleniumwire import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import json
from datetime import datetime, timedelta
from .logger import setup_logger
from pathlib import Path


class WizzairFlightSearch:
    def __init__(self, driver):
        self.driver = driver
        self.logger = setup_logger('wizzair_flight_search', 'wizzair_flight_search.log')

    def search_flight(self):
        # Hardcoded flight search parameters
        origin = "AUH"  # Abu Dhabi
        destination = "ALA"  # Almaty
        tomorrow = datetime.now() + timedelta(days=1)
        departure_date = tomorrow.strftime("%Y-%m-%d")

        try:
            # Navigate to the English flight search page (matching Chrome)
            self.driver.get("https://multipass.wizzair.com/de/w6/subscriptions/spa/private-page/wallets")
            self.logger.info("Navigated to English flight search page")

            # Wait for the search form to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[contains(@id, 'autocomplete-origin')]"))
            )

            # Fill in the origin
            origin_field = self.driver.find_element(By.XPATH, "//input[contains(@id, 'autocomplete-origin')]")
            origin_field.send_keys(origin)
            self.logger.info(f"Filled origin: {origin}")
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//ul[contains(@id, 'autocomplete-result-list')]//li"))
            )
            origin_field.send_keys(Keys.DOWN)
            origin_field.send_keys(Keys.ENTER)

            # Fill in the destination
            destination_field = self.driver.find_element(By.XPATH, "//input[contains(@id, 'autocomplete-destination')]")
            destination_field.send_keys(destination)
            self.logger.info(f"Filled destination: {destination}")
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//ul[contains(@id, 'autocomplete-result-list')]//li"))
            )
            destination_field.send_keys(Keys.DOWN)
            destination_field.send_keys(Keys.ENTER)

            # Fill in the departure date (DD-MM-YYYY)
            departure_date_formatted = tomorrow.strftime("%d-%m-%Y")
            departure_date_field = self.driver.find_element(By.ID, "Abflugdatum")
            departure_date_field.send_keys(departure_date_formatted)
            departure_date_field.send_keys(Keys.RETURN)
            self.logger.info(f"Filled departure date: {departure_date_formatted}")

            # Submit the initial search
            search_button = self.driver.find_element(By.XPATH, "//button[contains(@class, 'SearchCombo-submit')]")
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'SearchCombo-submit')]"))
            )
            search_button.click()
            self.logger.info("Initial flight search submitted")

            # Wait for the second search button
            WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "CvoSearchFlight-submit"))
            )
            self.logger.info("Results page loaded, second search button found")

            # Click the second "Search" button
            second_search_button = self.driver.find_element(By.CLASS_NAME, "CvoSearchFlight-submit")
            second_search_button.click()
            self.logger.info("Second search button clicked")

            # Wait for the XHR request
            time.sleep(5)

            # Capture the request
            curl_command = self.capture_request_as_curl()
            return curl_command

        except Exception as e:
            self.logger.error(f"Error during flight search: {str(e)}")
            return None

    def capture_request_as_curl(self):
        try:
            # Log all requests to the target URL
            target_url = "https://multipass.wizzair.com/de/w6/subscriptions/json/availability/d50b03eb-2498-49b7-a850-6124365cc048"
            self.logger.info(f"Logging all requests to {target_url}:")
            for request in self.driver.requests:
                if target_url in request.url:
                    content_type = request.headers.get('content-type', 'N/A')
                    body = request.body.decode('utf-8') if request.body else 'No body'
                    self.logger.info(
                        f"Request URL: {request.url}, Method: {request.method}, Content-Type: {content_type}, Body: {body}")

            # Filter for the JSON XHR request
            for request in self.driver.requests:
                if "d50b03eb-2498-49b7-a850-6124365cc048" in request.url and request.headers.get(
                        'content-type') == 'application/json':
                    self.logger.info(f"Captured target JSON request")
                    # Fix the body to match Chrome
                    if request.body:
                        body = json.loads(request.body.decode('utf-8'))
                        if body.get('arrival') == '':
                            body['arrival'] = None
                            self.logger.info("Adjusted 'arrival' from empty string to null")
                    curl_command = self.request_to_curl(request, fixed_body=body)
                    self.parse_curl_and_save_to_file(curl_command)
                    return curl_command

            self.logger.warning(f"No JSON request found for {target_url}. Check logged requests above.")
            return None

        except Exception as e:
            self.logger.error(f"Error capturing request: {str(e)}")
            return None

    def request_to_curl(self, request, fixed_body=None):
        """Convert a captured request to a cURL command with optional body override."""
        curl_parts = ["curl"]

        # Add the URL
        curl_parts.append(f"'{request.url}'")

        # Add the method
        curl_parts.append(f"-X {request.method}")

        # Add headers (match Chrome more closely)
        chrome_headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9,fa-IR;q=0.8,fa;q=0.7,de;q=0.6,fr;q=0.5,nl;q=0.4',
            'cache-control': 'no-cache',
            'content-type': 'application/json',
            'dnt': '1',
            'origin': 'https://multipass.wizzair.com',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://multipass.wizzair.com/de/w6/subscriptions/availability/d50b03eb-2498-49b7-a850-6124365cc048',
            'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            'x-xsrf-token': request.headers.get('x-xsrf-token')
        }
        for header, value in chrome_headers.items():
            if value:  # Skip if value is None (e.g., missing x-xsrf-token)
                curl_parts.append(f"-H '{header}: {value}'")

        # Add cookies
        cookies = self.driver.get_cookies()
        cookie_string = '; '.join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
        curl_parts.append(f"-b '{cookie_string}'")

        # Add the body (use fixed_body if provided, else original)
        if fixed_body is not None:
            body_str = json.dumps(fixed_body)
            curl_parts.append(f"--data-raw '{body_str}'")
        elif request.body:
            body = request.body.decode('utf-8')
            curl_parts.append(f"--data-raw '{body}'")

        # Join into a single cURL command
        curl_command = " ".join(curl_parts)
        self.logger.info("Generated cURL command")
        return curl_command

    def parse_curl_and_save_to_file(self, curl_command: str) -> None:
        if not curl_command:
            self.logger.error("No cURL command to save")
            return

        try:
            # Dynamic path
            project_root = Path(__file__).resolve().parents[2]
            output_file = project_root / "data" / "current" / "curl_request_data.json"
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Parse cURL
            url_match = re.search(r"curl '([^']+)'", curl_command)
            url = url_match.group(1) if url_match else ""

            method_match = re.search(r"-X (\w+)", curl_command)
            method = method_match.group(1) if method_match else "GET"

            headers = dict(re.findall(r"-H '([^:]+): (.*?)'", curl_command))

            data_match = re.search(r"--data-raw '(.+?)'", curl_command)
            data = data_match.group(1) if data_match else ""

            cookies_match = re.search(r"-b '(.+?)'", curl_command)
            cookies = cookies_match.group(1) if cookies_match else ""

            result = {
                "method": method,
                "url": url,
                "headers": headers,
                "data": data,
                "cookies": cookies
            }

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)

            self.logger.info(f"cURL command saved to {output_file}")

        except Exception as e:
            self.logger.error(f"Error saving cURL command: {str(e)}")


    def save_curl_command(self, curl_command, filename="flight_search_curl.sh"):
        """Save the cURL command to a file."""
        if not curl_command:
            self.logger.error("No cURL command to save")
            return False

        try:
            with open(filename, 'w') as f:
                f.write(curl_command)
            self.logger.info(f"cURL command saved to {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving cURL command: {str(e)}")
            return False


if __name__ == "__main__":
    raise RuntimeError("WizzairFlightSearch should not be run directly. Use main.py instead.")
