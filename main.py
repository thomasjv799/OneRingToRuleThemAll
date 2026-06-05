import logging
import os
import threading

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if __name__ == "__main__":
    if os.getenv("DISCORD_BOT_TOKEN"):
        from bot.discord_bot import run as run_discord
        threading.Thread(target=run_discord, daemon=True).start()

    from bot.telegram_bot import run as run_telegram
    run_telegram()
