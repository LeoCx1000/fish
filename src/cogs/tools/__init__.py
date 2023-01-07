from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

import discord

from .afk import AfkCommands
from .downloads import DownloadCommands
from .money import MoneyCommands
from .other import OtherCommands
from .reminder import ReminderCommands
from .tags import TagCommands

# from .video import Video

if TYPE_CHECKING:
    from bot import Bot
    from utils import PGTimer


class Tools(
    # Video,
    TagCommands,
    DownloadCommands,
    OtherCommands,
    AfkCommands,
    MoneyCommands,
    ReminderCommands,
    name="tools",
):
    """Useful tools"""

    def __init__(self, bot: Bot):
        super().__init__(bot)
        self.currently_downloading: list[str] = []
        self._have_data = asyncio.Event()
        self._current_timer: Optional[PGTimer] = None
        self._task = bot.loop.create_task(self.dispatch_timers())

    @property
    def display_emoji(self) -> discord.PartialEmoji:
        return discord.PartialEmoji(name="\U0001f528")


async def setup(bot: Bot):
    await bot.add_cog(Tools(bot))
