from __future__ import annotations

import datetime
import os
import re
from typing import Dict, List, Optional, Tuple

import aiohttp
import asyncpg
import discord
import pandas as pd
from discord.ext import commands

initial_extensions = {
    "jishaku",
    "cogs.owner",
}
bot_extensions = {
    "cogs.tools",
    "cogs.events.errors",
    "cogs.events.guilds",
    "cogs.events.members",
    "cogs.events.messages",
    "cogs.events.users",
    "cogs.pokemon",
}
os.environ["JISHAKU_HIDE"] = "True"
os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
os.environ["JISHAKU_NO_DM_TRACEBACK"] = "True"


class Bot(commands.Bot):
    session: aiohttp.ClientSession
    pool: asyncpg.Pool

    async def no_dms(self, ctx: commands.Context[Bot]):
        return ctx.guild is not None

    async def user_blacklist(self, ctx: commands.Context[Bot]):
        return ctx.author.id not in self.blacklisted_users

    async def guild_blacklist(self, ctx: commands.Context[Bot]):
        if ctx.guild is None:
            return True

        return ctx.guild.id not in self.blacklisted_guilds

    def __init__(self, intents: discord.Intents, config: Dict, testing: bool):
        prefix: List = ["fish ", "f"] if not testing else ["fish. ", "f."]
        super().__init__(
            command_prefix=commands.when_mentioned_or(*prefix),
            intents=intents,
            strip_after_prefix=True,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False
            ),
        )
        self.config: Dict = config
        self.uptime: Optional[datetime.datetime] = None
        self.embedcolor = 0xFAA0C1
        self.webhooks: Dict[str, discord.Webhook] = {}
        self.testing = testing
        self.pokemon: List[str] = []
        self.blacklisted_guilds: List[int] = []
        self.blacklisted_users: List[int] = []
        self.add_check(self.no_dms)
        self.add_check(self.user_blacklist)
        self.add_check(self.guild_blacklist)

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        _database = (
            self.config["databases"]["testing_psql"]
            if self.testing
            else self.config["databases"]["psql"]
        )
        connection = await asyncpg.create_pool(_database)

        if connection is None:
            raise asyncpg.ConnectionFailureError("Failed to connect to database")

        self.pool = connection

        blacklisted_guilds = await self.pool.fetch(
            "SELECT guild_id FROM guild_blacklist"
        )
        self.blacklisted_guilds = [guild["guild_id"] for guild in blacklisted_guilds]

        blacklisted_users = await self.pool.fetch("SELECT user_id FROM user_blacklist")
        self.blacklisted_users = [user["user_id"] for user in blacklisted_users]

        self.webhooks["error_logs"] = discord.Webhook.from_url(
            url=self.config["webhooks"]["error_logs"], session=self.session
        )

        self.webhooks["join_logs"] = discord.Webhook.from_url(
            url=self.config["webhooks"]["join_logs"], session=self.session
        )

        url = "https://raw.githubusercontent.com/poketwo/data/master/csv/pokemon.csv"
        data = pd.read_csv(url)
        pokemon = [str(p).lower() for p in data["name.en"]]

        for p in pokemon:
            if re.search(r"[\U00002640\U0000fe0f|\U00002642\U0000fe0f]", p):
                pokemon[pokemon.index(p)] = re.sub(
                    "[\U00002640\U0000fe0f|\U00002642\U0000fe0f]", "", p
                )
            if re.search(r"[\U000000e9]", p):
                pokemon[pokemon.index(p)] = re.sub("[\U000000e9]", "e", p)

        self.pokemon = pokemon

        if not self.testing:
            for extension in bot_extensions:
                initial_extensions.add(extension)

        for extension in initial_extensions:
            try:
                await self.load_extension(extension)
            except Exception as e:
                print(f"Failed to load {extension}: {e}")

    async def on_ready(self):
        if self.uptime is None:
            self.uptime = discord.utils.utcnow()

        print(f"Logged in as {str(self.user)}")

    async def close(self):
        for extension in initial_extensions:
            try:
                await self.unload_extension(extension)
            except Exception:
                pass

        await self.session.close()
        await self.pool.close()

        await super().close()


if __name__ == "__main__":
    print("Hello, please run the launcher.py file!")
