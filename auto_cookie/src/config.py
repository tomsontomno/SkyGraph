import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
CURRENT_DIR = DATA_DIR / "current"
CURL_REQUEST_FILE = CURRENT_DIR / "curl_request_data.json"


class Config:
    BASE_URL = "https://multipass.wizzair.com/auth/realms/w6/protocol/openid-connect/auth"
    EMAIL = os.getenv("WIZZAIR_EMAIL")
    PASSWORD = os.getenv("WIZZAIR_PASSWORD")
    CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH", "chromedriver")

    @staticmethod
    def get_login_url():
        params = {
            "scope": "openid roles tenant address phone subs email passenger",
            "response_type": "code",
            "client_id": "cvo-laravel",
            "redirect_uri": "https://multipass.wizzair.com/de/w6/subscriptions/auth/callback",
            "state": "15399ea13aeb60f4baa5d05585f51c31",
            "ui_locales": "de",
            "kc_locale": "de"
        }
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{Config.BASE_URL}?{query_string}"