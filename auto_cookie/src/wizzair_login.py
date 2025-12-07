from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from .config import Config
from .logger import setup_logger


class WizzairLogin:
    def __init__(self, driver):
        self.driver = driver
        self.logger = setup_logger('wizzair_login', 'wizzair_login.log')

    def login(self, email=None, password=None):
        email = email or Config.EMAIL
        password = password or Config.PASSWORD

        if not email or not password:
            raise ValueError("Email and password must be provided either through parameters or .env file")

        try:
            self.driver.get(Config.get_login_url())

            # Wait for email field to be visible
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )

            # Fill email
            email_field = self.driver.find_element(By.ID, "username")
            email_field.send_keys(email)
            self.logger.info("Email field filled")

            # Fill password
            password_field = self.driver.find_element(By.ID, "password")
            password_field.send_keys(password)
            self.logger.info("Password field filled")

            # Click submit
            submit_button = self.driver.find_element(By.ID, "kc-login")
            submit_button.click()
            self.logger.info("Login button clicked")

            # Wait for login to complete (you might need to adjust this)
            time.sleep(5)

            return True

        except Exception as e:
            self.logger.error(f"Error during login: {str(e)}")
            return False