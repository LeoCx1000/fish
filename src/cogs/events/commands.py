import datetime
from typing import List, Tuple

import discord
from bot import Bot
from discord.ext import commands, tasks
from utils import GuildContext


async def setup(bot: Bot):
    await bot.add_cog(CommandEvents(bot))


class CommandEvents(commands.Cog, name="command_events"):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.Cog.listener("on_command_completion")
    async def on_command_comletion(self, ctx: GuildContext):
        if ctx.command is None:
            return

        sql = """
        INSERT INTO command_logs(user_id, guild_id, channel_id, message_id, command, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """

        await self.bot.pool.execute(
            sql,
            ctx.author.id,
            ctx.guild.id,
            ctx.channel.id,
            ctx.message.id,
            ctx.command.name,
            discord.utils.utcnow(),
        )