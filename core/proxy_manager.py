from typing import Optional, List, Dict
from datetime import datetime, timedelta
from core.project_paths import path_in_current
import logging

logger = logging.getLogger(__name__)


class ProxyManager:
    def __init__(self, proxy_file: str = None, window_size: int = 5, requests_per_proxy: int = 5):
        self.proxy_file = proxy_file or path_in_current("proxies.txt")
        self.proxies = self.load_proxies(self.proxy_file)
        self.window_size = window_size
        self.requests_per_proxy = requests_per_proxy
        self.failed_proxies = set()
        self.current_window = []
        self.current_proxy_index = 0
        logger.info(f"ProxyManager initialized with {len(self.proxies)} proxies "
                    f"(window_size={self.window_size}, requests_per_proxy={self.requests_per_proxy})")
        self.load_initial_window()

    def load_proxies(self, file_path: str) -> List[Dict[str, Optional[datetime]]]:
        proxies = []
        logger.debug(f"Loading proxies from: {file_path}")
        with open(file_path, 'r') as file:
            for line in file:
                line = line.strip()
                if line:
                    try:
                        ip, port, username, password = line.split(':')
                        proxies.append({
                            "address": ip,
                            "port": port,
                            "username": username,
                            "password": password,
                            "cooldown_until": None,
                            "requests_count": 0
                        })
                    except ValueError:
                        logger.warning(f"Invalid proxy line: {line}. Skipping.")
        logger.info(f"Loaded {len(proxies)} proxies.")
        return proxies

    def load_initial_window(self):
        self.current_window = [
            proxy for proxy in self.proxies
            if proxy["address"] not in self.failed_proxies and
            (proxy["cooldown_until"] is None or datetime.now() > proxy["cooldown_until"])
        ][:self.window_size]
        logger.debug(f"Initial proxy window loaded with {len(self.current_window)} proxies.")

    def validate_proxy(self, proxy) -> bool:
        is_valid = isinstance(proxy, dict) and "address" in proxy and "port" in proxy
        if not is_valid:
            logger.warning(f"Invalid proxy object: {proxy}")
        return is_valid

    def get_next_proxy(self) -> Optional[Dict[str, Optional[datetime]]]:
        if not self.current_window:
            logger.warning("No available proxies in the current window. Reloading window...")
            self.load_initial_window()
            if not self.current_window:
                logger.error("No proxies available at all.")
                return None

        self.current_proxy_index %= len(self.current_window)
        proxy = self.current_window[self.current_proxy_index]

        if (
            self.validate_proxy(proxy) and
            proxy["address"] not in self.failed_proxies and
            (proxy["cooldown_until"] is None or datetime.now() > proxy["cooldown_until"])
        ):
            proxy["requests_count"] += 1
            logger.debug(f"Using proxy {proxy['address']} (count: {proxy['requests_count']})")

            if proxy["requests_count"] >= self.requests_per_proxy:
                logger.debug(f"Rotating proxy {proxy['address']}")
                self.current_proxy_index = (self.current_proxy_index + 1) % len(self.current_window)
                proxy["requests_count"] = 0

            return proxy

        logger.warning(f"Removing invalid or cooldown proxy: {proxy['address']}")
        self.current_window.pop(self.current_proxy_index)

        if not self.current_window:
            logger.warning("All proxies in current window exhausted. Reloading window.")
            self.load_initial_window()

        return self.get_next_proxy()

    def set_proxy_on_cooldown(self, proxy, cooldown: float = 5):
        if self.validate_proxy(proxy):
            proxy["cooldown_until"] = datetime.now() + timedelta(minutes=cooldown)
            logger.info(f"Proxy {proxy['address']} is on cooldown until {proxy['cooldown_until']}.")
            self.replace_proxy_in_window(proxy)
        else:
            logger.warning(f"Cannot set cooldown on invalid proxy: {proxy}")

    def mark_proxy_as_failed(self, proxy):
        if self.validate_proxy(proxy):
            self.failed_proxies.add(proxy["address"])
            logger.info(f"Marked proxy {proxy['address']} as permanently failed.")
            self.replace_proxy_in_window(proxy)
        else:
            logger.warning(f"Cannot mark invalid proxy as failed: {proxy}")

    def replace_proxy_in_window(self, failed_proxy):
        next_available_proxy = next(
            (p for p in self.proxies
             if p["address"] not in self.failed_proxies and
             (p["cooldown_until"] is None or datetime.now() > p["cooldown_until"])
             and p not in self.current_window), None)

        if next_available_proxy:
            logger.debug(f"Replacing proxy {failed_proxy['address']} with {next_available_proxy['address']}")
            self.current_window[self.current_proxy_index] = next_available_proxy
        else:
            logger.warning("No replacement proxy found. Reducing window size.")
            self.current_window.pop(self.current_proxy_index)
