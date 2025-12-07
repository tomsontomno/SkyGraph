import asyncio
import logging
from dotenv import load_dotenv
from pathlib import Path

from auto_cookie.src import main as cookie_main
from core import cookies, route_find, fetcher_optimize as fetcher

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
logger = logging.getLogger("main")


async def async_main(manually_enter_cookies=False, days=None, verbose=False):
    """
    Orchestrates the asynchronous flight data acquisition and route analysis pipeline.

    Args:
        manually_enter_cookies (bool): If True, prompts user for manual cookie entry.
        days (list[int], optional): List of day offsets to scan. Defaults to [0, 1, 2, 3].
        verbose (bool): Enables detailed logging if True.
    """
    days = days or [0, 1, 2, 3]

    # Step 1: Credential Management
    if manually_enter_cookies:
        logger.info("Initiating manual cookie entry...")
        cookies.save_cookies()
    else:
        logger.info("Executing automated cookie retrieval...")
        cookie_main.main()

    # Step 2: Data Acquisition
    logger.info("Initializing flight data fetcher...")
    await fetcher.main(days=days, verbose=verbose)

    # Step 3: Route Analysis
    logger.info("Executing route finding algorithm...")
    route_find.main()


def main(days=None, manually_enter_cookies=True, verbose=False):
    """
    Application entry point. Configures logging and triggers the async event loop.
    """
    days = days or [0, 1, 2, 3]
    logger.info(f"Process initialized. Parameters: days={days}, manual_cookies={manually_enter_cookies}")
    asyncio.run(async_main(
        manually_enter_cookies=manually_enter_cookies,
        days=days,
        verbose=verbose
    ))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main(days=[1, 2, 3], manually_enter_cookies=True, verbose=True)
