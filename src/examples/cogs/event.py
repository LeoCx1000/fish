from __future__ import annotations

from typing import TYPE_CHECKING
import discord
from discord.ext import commands

if TYPE_CHECKING:
    from bot import Bot


async def setup(bot: Bot):
    await bot.add_cog(Example(bot))


class Example(commands.Cog, name="example"):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message):
        print("A message was sent!")
