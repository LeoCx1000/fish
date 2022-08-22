import asyncio
import logging
import logging.handlers

import discord
import toml
from discord import gateway

from bot import Bot
from utils import mobile

gateway.DiscordWebSocket.identify = mobile

testing = False


async def main():
    logger = logging.getLogger("discord")
    logger.setLevel(logging.ERROR)
    logging.getLogger("discord.http").setLevel(logging.ERROR)

    handler = logging.handlers.RotatingFileHandler(
        filename="discord.log",
        encoding="utf-8",
        maxBytes=32 * 1024 * 1024,  # 32 MiB
        backupCount=5,  # Rotate through 5 files
    )
    dt_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(
        "[{asctime}] [{levelname:<8}] {name}: {message}", dt_fmt, style="{"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    config = toml.load("config.toml")

    intents = discord.Intents.all()

    bot = Bot(intents, config, testing, logger)

    async with bot:
        await bot.start(config["tokens"]["bot"])


asyncio.run(main())