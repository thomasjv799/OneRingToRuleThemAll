import logging
import os
import threading

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if __name__ == "__main__":
    # Telegram is blocked in India; disabled by default. Set ENABLE_TELEGRAM to
    # re-enable it as a secondary transport. Discord is the required primary.
    enable_telegram = os.getenv("ENABLE_TELEGRAM", "").lower() in ("1", "true", "yes")

    if enable_telegram and os.getenv("TELEGRAM_BOT_TOKEN"):
        from bot.telegram_bot import run as run_telegram
        threading.Thread(target=run_telegram, daemon=True).start()

    from bot.discord_bot import run as run_discord
    run_discord()
