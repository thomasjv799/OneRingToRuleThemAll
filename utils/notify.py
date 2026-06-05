import os
import httpx


def notify(text: str, platform: str, chat_id: str, parse_mode: str | None = None) -> None:
    if platform == "telegram":
        _send_telegram(text, chat_id, parse_mode)
    elif platform == "discord":
        _send_discord(text, chat_id)


def _send_telegram(text: str, chat_id: str, parse_mode: str | None = None) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=10,
    ).raise_for_status()


def _send_discord(text: str, channel_id: str) -> None:
    token = os.environ["DISCORD_BOT_TOKEN"]
    httpx.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        json={"content": text[:2000]},
        timeout=10,
    ).raise_for_status()
