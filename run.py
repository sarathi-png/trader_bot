import asyncio
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import Settings
from main import QuotexSignalBot


def setup_logging(level: str = "INFO", log_file: str = "logs/bot.log"):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file)
        ]
    )


async def run_login(settings: Settings):
    from auth.ssid_extractor import get_or_refresh_ssid, delete_session

    delete_session()
    logger = logging.getLogger(__name__)
    logger.info("Forcing re-authentication via Playwright...")

    ssid = await get_or_refresh_ssid(
        email=settings.quotex_email,
        password=settings.quotex_password,
        force_refresh=True,
        headless=settings.quotex_headless,
        is_demo=settings.quotex_demo,
    )

    if ssid:
        print(f"\nLogin successful! SSID: {ssid[:12]}...")
        print("Session cached. You can now start the bot normally.")
    else:
        print("\nLogin failed. Check your credentials and try again.")
    return ssid


async def main():
    parser = argparse.ArgumentParser(description="Quotex Signal Bot")
    parser.add_argument("--login", action="store_true", help="Force re-authentication via browser")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode with simulated data")
    args = parser.parse_args()

    settings = Settings.from_env()
    setup_logging(settings.log_level, settings.log_file)

    logger = logging.getLogger(__name__)

    if args.login:
        await run_login(settings)
        return

    use_mock = args.mock or not settings.quotex_email or settings.quotex_email == "your_email@example.com"
    if use_mock:
        logger.warning("Running in MOCK mode with simulated data.")

    bot = QuotexSignalBot(settings, use_mock=use_mock)

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
