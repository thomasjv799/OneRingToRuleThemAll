import os
import httpx


def notify(text: str, platform: str, chat_id: str) -> None:
    if platform == "telegram":
        _send_telegram(text, chat_id)
    elif platform == "discord":
        _send_discord(text, chat_id)


def _send_telegram(text: str, chat_id: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    ).raise_for_status()


def _send_discord(text: str, channel_id: str) -> None:
    token = os.environ["DISCORD_BOT_TOKEN"]
    httpx.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        json={"content": text},
        timeout=10,
    ).raise_for_status()
