from seleniumwire import webdriver  # Use selenium-wire for network request capture
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import os
from auto_cookie.src.config import Config
from auto_cookie.src.wizzair_login import WizzairLogin
from auto_cookie.src.wizzair_flight_search import WizzairFlightSearch
from auto_cookie.src.logger import setup_logger


def setup_driver():
    try:
        chromedriver_path = Config.CHROMEDRIVER_PATH
        if not os.path.exists(chromedriver_path):
            raise FileNotFoundError(f"ChromeDriver not found at path: {chromedriver_path}")

        # Set up selenium-wire with ChromeDriver
        service = Service(executable_path=chromedriver_path)
        options = Options()
        options.add_argument('--headless')  # Run in headless mode (optional, remove if you want to see the browser)
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        logger = setup_logger('main', 'main.log')
        logger.error(f"Error setting up WebDriver: {str(e)}")
        raise


def main():
    logger = setup_logger('main', 'main.log')
    driver = None

    try:
        # Step 1: Set up the WebDriver
        driver = setup_driver()
        logger.info("WebDriver initialized successfully")

        # Step 2: Log in
        login_handler = WizzairLogin(driver)
        login_success = login_handler.login()
        if not login_success:
            logger.error("Login failed. Cannot proceed with flight search.")
            return

        logger.info("Login successful. Proceeding with flight search.")

        # Step 3: Perform flight search and capture request
        flight_search = WizzairFlightSearch(driver)
        curl_command = flight_search.search_flight()
        if curl_command:
            logger.info("Flight search completed successfully.")
        else:
            logger.error("Flight search failed.")

    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")

    finally:
        # Step 5: Clean up the WebDriver
        if driver:
            driver.quit()
            logger.info("WebDriver closed")


if __name__ == "__main__":
    main()
