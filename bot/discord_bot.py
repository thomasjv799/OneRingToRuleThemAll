import logging
import os

import discord

from ai.graph import run_graph

log = logging.getLogger(__name__)

_intents = discord.Intents.default()
_intents.message_content = True


class _Client(discord.Client):
    async def on_ready(self):
        log.info("Discord bot ready: %s", self.user)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        user_id = str(message.author.id)
        reply = run_graph(user_id, message.content)
        await message.channel.send(reply)


_client = _Client(intents=_intents)


def run() -> None:
    token = os.environ["DISCORD_BOT_TOKEN"]
    log.info("Discord bot started")
    _client.run(token)
