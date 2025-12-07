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
    Run the async flight fetcher and route analysis pipeline.
    """
    days = days or [0, 1, 2, 3]

    # Step 1: Get cookies
    if manually_enter_cookies:
        logger.info("Saving cookies manually...")
        cookies.save_cookies()
    else:
        logger.info("Running cookie automation...")
        cookie_main.main()

    # Step 2: Run the flight data fetcher
    logger.info("Starting flight data fetcher...")
    await fetcher.main(days=days, verbose=verbose)

    # Step 3: Run the route finder
    logger.info("Starting route finder...")
    route_find.main()


def main(days=None, manually_enter_cookies=True, verbose=False):
    """
    Entry point for the program.
    """
    days = days or [0, 1, 2, 3]
    logger.info(f"Main process started with days={days}, manually_enter_cookies={manually_enter_cookies}")
    asyncio.run(async_main(
        manually_enter_cookies=manually_enter_cookies,
        days=days,
        verbose=verbose
    ))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main(days=[1, 2, 3], manually_enter_cookies=True, verbose=True)
