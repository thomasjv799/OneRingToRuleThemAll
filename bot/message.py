from dataclasses import dataclass


@dataclass
class Message:
    platform: str   # "telegram" | "discord"
    user_id: str
    chat_id: str
    text: str
