from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    TypeAlias,
    Union,
)

import asyncpg
import discord
from discord.ext import commands

from utils import (
    FieldPageSource,
    Pager,
    SteamIDConverter,
    UnknownAccount,
    add_prefix,
    get_or_fetch_user,
    plural,
    to_bytesio,
    BlankException,
    human_join,
    CHECK,
)

if TYPE_CHECKING:
    from bot import Bot
    from cogs.context import Context


async def setup(bot: Bot):
    await bot.add_cog(Settings(bot))


Logger = [
    "avatars",
    "guild avatars",
    "nicknames",
    "discrims",
    "usernames",
    "joins",
    "uptime",
]


class Settings(commands.Cog, name="settings"):
    """Settings for the bot"""

    def __init__(self, bot: Bot):
        self.bot = bot

    @property
    def display_emoji(self) -> discord.PartialEmoji:
        return discord.PartialEmoji(name="\U00002699\U0000fe0f")

    async def unlink_method(self, ctx: Context, user_id: int, option: str):
        await ctx.bot.pool.execute(
            f"UPDATE accounts SET {option} = NULL WHERE user_id = $1", user_id
        )
        await ctx.bot.redis.hdel(f"accounts:{user_id}", option)

        await ctx.send(f"Your {option} account has been unlinked.", ephemeral=True)

    async def link_method(self, ctx: Context, user_id: int, option: str, username: str):
        username = username.lower()
        sql = f"""
        INSERT INTO accounts (user_id, {option}) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE
        SET {option} = $2 WHERE accounts.user_id = $1
        """
        await ctx.bot.pool.execute(
            sql,
            ctx.author.id,
            username,
        )
        await ctx.bot.redis.hset(f"accounts:{user_id}", option, username)

        await ctx.send(f"Your {option} account has been linked.", ephemeral=True)

    @commands.command(
        name="auto-solve",
        aliases=("as", "auto_solve"),
        extras={"UPerms": ["Manage Server"]},
    )
    @commands.has_permissions(manage_guild=True)
    async def auto_solve(self, ctx: Context):
        """Toggles automatic solving of pokétwo's pokémon hints"""

        try:
            sql = "INSERT INTO guild_settings(guild_id, poketwo) VALUES($1, $2)"
            await self.bot.pool.execute(sql, ctx.guild.id, True)
        except asyncpg.UniqueViolationError:
            if str(ctx.guild.id) in await self.bot.redis.smembers("poketwo_guilds"):
                sql = "UPDATE guild_settings SET poketwo = NULL WHERE guild_id = $1"
                await self.bot.pool.execute(sql, ctx.guild.id)
                await self.bot.redis.srem("poketwo_guilds", ctx.guild.id)
                await ctx.send("Disabled auto solving for this server.")
                return

            sql = "UPDATE guild_settings SET poketwo = $1 WHERE guild_id = $2"
            await self.bot.pool.execute(sql, True, ctx.guild.id)

        await self.bot.redis.sadd("poketwo_guilds", ctx.guild.id)
        await ctx.send("Enabled auto solving for this server.")

    @commands.group(name="prefix", invoke_without_command=True)
    async def prefix(self, ctx: Context):
        """Set the prefix for the bot"""
        sql = """SELECT * FROM guild_prefixes WHERE guild_id = $1 ORDER BY time DESC"""
        results = await ctx.bot.pool.fetch(sql, ctx.guild.id)

        if results == []:
            await ctx.send("This server has no prefixes set.")
            return

        entries = [
            (
                record["prefix"],
                f'{discord.utils.format_dt(record["time"], "R")}  |  {discord.utils.format_dt(record["time"], "d")} | {(await get_or_fetch_user(self.bot, record["author_id"])).mention}',
            )
            for record in results
        ]

        p = FieldPageSource(entries, per_page=4)
        p.embed.title = f"Prefixes in {ctx.guild}"
        menu = Pager(p, ctx=ctx)
        await menu.start(ctx)

    @prefix.command(name="add", aliases=("set", "setprefix", "+"))
    @commands.has_permissions(manage_guild=True)
    async def prefix_add(self, ctx: Context, *, prefix: str):
        """Add a prefix to the server"""
        if len(prefix) > 10:
            await ctx.send("Prefixes can only be 10 characters long.")
            return

        try:
            check = self.bot.prefixes[ctx.guild.id]
            if prefix in check:
                await ctx.send("This prefix is already set.")
                return

        except KeyError:
            pass

        sql = """INSERT INTO guild_prefixes (guild_id, prefix, author_id, time) VALUES ($1, $2, $3, $4)"""
        await ctx.bot.pool.execute(
            sql, ctx.guild.id, prefix, ctx.author.id, discord.utils.utcnow()
        )
        add_prefix(self.bot, ctx.guild.id, prefix)
        await ctx.send(f"Added prefix `{prefix}` to the server.")

    @prefix.command(name="remove", aliases=("delete", "del", "rm", "-"))
    @commands.has_permissions(manage_guild=True)
    async def prefix_remove(self, ctx: Context, *, prefix: str):
        """Remove a prefix from the server"""

        try:
            sql = """DELETE FROM guild_prefixes WHERE guild_id = $1 AND prefix = $2"""
            await ctx.bot.pool.execute(sql, ctx.guild.id, prefix)
            self.bot.prefixes[ctx.guild.id].remove(prefix)
            await ctx.send(f"Removed prefix `{prefix}` from the server.")
        except (KeyError, ValueError):
            await ctx.send("This prefix does not exist.")
            return

    @commands.command(name="accounts")
    async def accounts(self, ctx: Context, *, user: discord.User = commands.Author):
        """Shows your linked accounts"""
        accounts = await ctx.bot.pool.fetchrow(
            "SELECT * FROM accounts WHERE user_id = $1", user.id
        )

        if not accounts:
            await ctx.send(f"{str(user)} has no linked accounts.")
            return

        embed = discord.Embed()
        embed.set_author(
            name=f"{user.display_name} - Connected accounts",
            icon_url=user.display_avatar.url,
        )

        embed.add_field(name="Last.fm", value=accounts["lastfm"] or "Not set")
        embed.add_field(name="osu!", value=accounts["osu"] or "Not set")
        embed.add_field(name="Steam", value=accounts["steam"] or "Not set")
        embed.add_field(name="Roblox", value=accounts["roblox"] or "Not set")

        await ctx.send(embed=embed, check_ref=True)

    @commands.group(name="set", invoke_without_command=True)
    async def set(self, ctx: Context):
        """Sets your profile for a site"""
        await ctx.send_help(ctx.command)

    @set.command(name="lastfm", aliases=["fm"])
    async def set_lastfm(self, ctx: Context, username: str):
        """Sets your last.fm account"""
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,15}", username):
            raise UnknownAccount("Invalid username.")

        await self.link_method(ctx, ctx.author.id, "lastfm", username)

    @set.command(name="osu")
    async def set_osu(self, ctx: Context, *, username: str):
        """Sets your osu! account"""
        if not re.fullmatch(r"[a-zA-Z0-9_\s-]{2,16}", username):
            raise UnknownAccount("Invalid username.")

        await self.link_method(ctx, ctx.author.id, "osu", username)

    @set.command(name="steam")
    async def set_steam(self, ctx: Context, username: str):
        """Sets your steam account"""
        SteamIDConverter(username)
        await self.link_method(ctx, ctx.author.id, "steam", username)

    @set.command(name="roblox")
    async def set_roblox(self, ctx: Context, *, username: str):
        """Sets your roblox account"""

        await self.link_method(ctx, ctx.author.id, "roblox", username)

    @set.command(name="genshin")
    async def set_genshin(self, ctx: Context, *, user_id: str):
        """Sets your genshin account"""
        if not re.match(r"[0-9]{4,15}", user_id):
            raise UnknownAccount("Invalid UID.")

        await self.link_method(ctx, ctx.author.id, "genshin", user_id)

    @commands.group(name="unlink", invoke_without_command=True)
    async def unlink(self, ctx: Context):
        """Unlinks your account"""
        await ctx.send_help(ctx.command)

    @unlink.command(name="lastfm")
    async def unlink_lastfm(self, ctx: Context):
        """Unlinks your last.fm account"""
        await self.unlink_method(ctx, ctx.author.id, "lastfm")

    @unlink.command(name="osu")
    async def unlink_osu(self, ctx: Context):
        """Unlinks your osu account"""
        await self.unlink_method(ctx, ctx.author.id, "osu")

    @unlink.command(name="steam")
    async def unlink_steam(self, ctx: Context):
        """Unlinks your steam account"""
        await self.unlink_method(ctx, ctx.author.id, "steam")

    @unlink.command(name="roblox")
    async def unlink_roblox(self, ctx: Context):
        """Unlinks your roblox account"""
        await self.unlink_method(ctx, ctx.author.id, "roblox")

    @unlink.command(name="genshin")
    async def unlink_genshin(self, ctx: Context):
        """Unlinks your genshin account"""
        await self.unlink_method(ctx, ctx.author.id, "genshin")

    @commands.group(
        name="auto-download", aliases=("auto-dl", "adl"), invoke_without_command=True
    )
    async def auto_download(self, ctx: Context):
        sql = """SELECT auto_download FROM guild_settings WHERE guild_id = $1"""
        results = await self.bot.pool.fetchval(sql, ctx.guild.id)

        if not results:
            message = "This server does not have an auto-download channel set yet."

            if (
                isinstance(ctx.author, discord.Member)
                and ctx.author.guild_permissions.manage_guild
            ):
                message += f"\nYou can set one with `{ctx.prefix}auto_download set`."

            await ctx.send(message)
            return

        channel = self.bot.get_channel(results)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        await ctx.send(f"Auto-download is set to {channel.mention}.")

    @auto_download.command(
        name="set",
        aliases=("create", "create_channel", "create_dl_channel"),
        extras={"UPerms": ["Manage Server"]},
    )
    @commands.has_guild_permissions(manage_guild=True)
    async def auto_download_set(
        self, ctx: Context, channel: Optional[discord.TextChannel]
    ):
        sql = """SELECT auto_download FROM guild_settings WHERE guild_id = $1"""
        result = await self.bot.pool.fetchval(sql, ctx.guild.id)

        if result is not None:
            return await ctx.send(f"Auto-download is already setup here.")

        if channel is None:
            if not ctx.me.guild_permissions.manage_channels:
                return await ctx.send(
                    f"I cannot create a channel so you can either make one yourself or use `{ctx.prefix}auto_download set <channel>` to set an already made one."
                )

            response = await ctx.prompt(
                "You didn't provide a channel so I will create one, is this okay?"
            )
            if response is None:
                return await ctx.send(
                    f"Okay, I won't create a channel, instead specify one with `{ctx.prefix}auto_download set <channel>`."
                )

            channel = await ctx.guild.create_text_channel(
                name=f"auto-download",
                topic="Valid links posted here will be auto downloaded. \nAccepted sites are, Youtube, TikTok, Twitter, and reddit.",
            )

            first_sql = """SELECT guild_id FROM guild_settings WHERE guild_id = $1"""
            results = await self.bot.pool.fetchval(first_sql, ctx.guild.id)

            sql = (
                """INSERT INTO guild_settings (guild_id, auto_download) VALUES ($1, $2)"""
                if not results
                else """UPDATE guild_settings SET auto_download = $2 WHERE guild_id = $1"""
            )

            await self.bot.pool.execute(sql, ctx.guild.id, channel.id)
            await self.bot.redis.sadd("auto_download_channels", channel.id)
            return await ctx.send(f"Auto-download is now set to {channel.mention}.")

        if not channel.permissions_for(ctx.me).send_messages:
            return await ctx.send(
                f"I don't have permission to send messages in {channel.mention}."
            )

        first_sql = """SELECT guild_id FROM guild_settings WHERE guild_id = $1"""
        results = await self.bot.pool.fetchval(first_sql, ctx.guild.id)

        sql = (
            """INSERT INTO guild_settings (guild_id, auto_download) VALUES ($1, $2)"""
            if not results
            else """UPDATE guild_settings SET auto_download = $2 WHERE guild_id = $1"""
        )

        await self.bot.pool.execute(sql, ctx.guild.id, channel.id)
        await self.bot.redis.sadd("auto_download_channels", channel.id)
        await ctx.send(f"Auto-download is now set to {channel.mention}.")

    @auto_download.command(
        name="remove", aliases=("delete",), extras={"UPerms": ["Manage Server"]}
    )
    @commands.has_guild_permissions(manage_guild=True)
    async def auto_download_remove(self, ctx: Context):
        sql = """SELECT auto_download FROM guild_settings WHERE guild_id = $1"""
        result = await self.bot.pool.fetchval(sql, ctx.guild.id)

        if not result:
            return await ctx.send(
                "This server does not have an auto-download channel set yet."
            )

        if not isinstance(result, int):
            return

        channel = self.bot.get_channel(result)
        if isinstance(channel, discord.TextChannel):
            results = await ctx.prompt(
                f"Are you sure you want to delete {channel.mention}?"
            )
            if not results:
                return await ctx.send(f"Well I didn't want to delete it anyway.")

        sql = """UPDATE guild_settings SET auto_download = NULL WHERE guild_id = $1"""
        await self.bot.pool.execute(sql, ctx.guild.id)
        await self.bot.redis.srem("auto_download_channels", result)
        await ctx.send(f"Removed auto-downloads for this server.")

    @commands.group(name="data", invoke_without_command=True)
    async def data_group(self, ctx: Context):
        """Manage your data I store on you."""
        await ctx.send_help(ctx.command)

    @data_group.group(name="remove", aliases=("delete",), invoke_without_command=True)
    async def remove_group(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @remove_group.group(
        name="avatars", aliases=("pfps", "avs", "avys"), invoke_without_command=True
    )
    async def delete_avatars(self, ctx: Context, id: Optional[int] = None):
        avatars: List[asyncpg.Record] = await self.bot.pool.fetch(
            "SELECT * FROM avatars WHERE user_id = $1 ORDER BY created_at DESC",
            ctx.author.id,
        )
        if id:
            try:
                avatar = avatars[id - 1]
            except:
                return await ctx.send("Couldn't find an avatar at that index for you.")

            file = discord.File(
                await to_bytesio(ctx.session, avatar["avatar"]), filename="avatar.png"
            )

            prompt = await ctx.prompt(
                "Are you sure you want to delete this avatar from your avatars? This action **CANNOT** be undone.",
                files=[file],
                timeout=10,
            )

            if not prompt:
                return await ctx.send("Good, I didn't want to delete it anyway.")

            await self.bot.pool.execute(
                "DELETE FROM avatars WHERE avatar_key = $1 AND user_id = $2",
                avatar["avatar_key"],
                ctx.author.id,
            )

            return await ctx.send(f"Successfully deleted that avatar.")

        prompt = await ctx.prompt(
            "Are you sure you want to delete **ALL OF YOUR AVATARS**? This action **CANNOT** be undone.",
            timeout=10,
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM avatars WHERE user_id = $1 RETURNING avatar",
            ctx.author.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):avatar}")

    @delete_avatars.command(name="guild", aliases=("server",))
    async def delete_guild_avatars(
        self,
        ctx: Context,
        guild: Optional[discord.Guild] = commands.CurrentGuild,
        id: Optional[int] = None,
    ):
        guild = guild or ctx.guild
        avatars: List[asyncpg.Record] = await self.bot.pool.fetch(
            "SELECT * FROM guild_avatars WHERE member_id = $1 AND guild_id = $2 ORDER BY created_at DESC",
            ctx.author.id,
            guild.id,
        )
        if id:
            try:
                avatar = avatars[id - 1]
            except:
                return await ctx.send("Couldn't find an avatar at that index for you.")

            file = discord.File(
                await to_bytesio(ctx.session, avatar["avatar"]), filename="avatar.png"
            )

            prompt = await ctx.prompt(
                "Are you sure you want to delete this avatar from your guild avatars? This action **CANNOT** be undone.",
                files=[file],
                timeout=10,
            )

            if not prompt:
                return await ctx.send("Good, I didn't want to delete it anyway.")

            await self.bot.pool.execute(
                "DELETE FROM guild_avatars WHERE avatar_key = $1 AND member_id = $2 AND guild_id = $3",
                avatar["avatar_key"],
                ctx.author.id,
                guild.id,
            )

            return await ctx.send(f"Successfully deleted that avatar.")

        prompt = await ctx.prompt(
            "Are you sure you want to delete **ALL OF YOUR AVATARS**? This action **CANNOT** be undone.",
            timeout=10,
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM guild_avatars WHERE member_id = $1 AND guild_id = $2 RETURNING avatar",
            ctx.author.id,
            guild.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):guild avatar}")

    @remove_group.command(name="usernames")
    async def remove_usernames(self, ctx: Context):
        records = await ctx.pool.fetch(
            """SELECT * FROM username_logs WHERE user_id = $1""", ctx.author.id
        )

        if records == []:
            raise BlankException("I have no username history on record for you.")

        prompt = await ctx.prompt(
            f"Are you sure you want to delete {plural(len(records)):username}? This action **CANNOT** be undone."
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM username_logs WHERE user_id = $1 RETURNING username",
            ctx.author.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):username}")

    @remove_group.command(name="discrims", aliases=("discriminators",))
    async def remove_discrims(self, ctx: Context):
        records = await ctx.pool.fetch(
            """SELECT * FROM discrim_logs WHERE user_id = $1""", ctx.author.id
        )

        if records == []:
            raise BlankException("I have no discriminator history on record for you.")

        prompt = await ctx.prompt(
            f"Are you sure you want to delete {plural(len(records)):discriminator}? This action **CANNOT** be undone."
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM discrim_logs WHERE user_id = $1 RETURNING discrim",
            ctx.author.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):discriminator}")

    @remove_group.command(name="nicknames")
    async def remove_nicknames(
        self, ctx: Context, *, guild: Optional[discord.Guild] = commands.CurrentGuild
    ):
        guild = guild or ctx.guild
        records = await ctx.pool.fetch(
            """SELECT * FROM nickname_logs WHERE user_id = $1 AND guild_id = $2""",
            ctx.author.id,
            guild.id,
        )

        if records == []:
            raise BlankException(
                "I have no nickname history on record for you for this guild."
            )

        prompt = await ctx.prompt(
            f"Are you sure you want to delete {plural(len(records)):nickname}? This action **CANNOT** be undone."
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM nickname_logs WHERE user_id = $1 AND guild_id = $2 RETURNING nickname",
            ctx.author.id,
            guild.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):username}")

    @remove_group.command(name="uptime")
    async def remove_uptime(
        self, ctx: Context, *, guild: Optional[discord.Guild] = commands.CurrentGuild
    ):
        guild = guild or ctx.guild
        records = await ctx.pool.fetch(
            """SELECT * FROM uptime_logs WHERE user_id = $1""",
            ctx.author.id,
            guild.id,
        )

        if records == []:
            raise BlankException("I have no uptime history on record for you.")

        prompt = await ctx.prompt(
            f"Are you sure you want to opt out of having your uptime tracked?? This action **CANNOT** be undone."
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to do that anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM uptime_logs WHERE user_id = $1",
            ctx.author.id,
            guild.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):username}")

    @remove_group.group(name="guild", invoke_without_command=True)
    async def remove_guild_group(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @remove_guild_group.command(name="icons")
    @commands.has_guild_permissions(administrator=True)
    async def remove_guild_icons(
        self, ctx: Context, *, guild: Optional[discord.Guild] = commands.CurrentGuild
    ):
        guild = guild or ctx.guild

        records = await ctx.pool.fetch(
            """SELECT * FROM guild_icons WHERE guild_id = $1""",
            guild.id,
        )

        if records == []:
            raise BlankException("I have no icon history on record for this guild.")

        prompt = await ctx.prompt(
            f"Are you sure you want to delete {plural(len(records)):icon}? This action **CANNOT** be undone."
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM guild_ioncs WHERE guild_id = $1 RETURNING icon",
            guild.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):icon}")

    @remove_guild_group.command(name="bans")
    @commands.has_guild_permissions(administrator=True)
    async def remove_guild_bans(
        self, ctx: Context, *, guild: Optional[discord.Guild] = commands.CurrentGuild
    ):
        guild = guild or ctx.guild

        records = await ctx.pool.fetch(
            """SELECT * FROM guild_bans WHERE guild_id = $1""",
            guild.id,
        )

        if records == []:
            raise BlankException("I have no ban history on record for this guild.")

        prompt = await ctx.prompt(
            f"Are you sure you want to delete {plural(len(records)):ban log}? This action **CANNOT** be undone."
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM guild_bans WHERE guild_id = $1 RETURNING target_id",
            guild.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):ban log}")

    @remove_guild_group.command(name="names")
    @commands.has_guild_permissions(administrator=True)
    async def remove_guild_names(
        self, ctx: Context, *, guild: Optional[discord.Guild] = commands.CurrentGuild
    ):
        guild = guild or ctx.guild

        records = await ctx.pool.fetch(
            """SELECT * FROM guild_name_logs WHERE guild_id = $1""",
            guild.id,
        )

        if records == []:
            raise BlankException("I have no name history on record for this guild.")

        prompt = await ctx.prompt(
            f"Are you sure you want to delete {plural(len(records)):guild name}? This action **CANNOT** be undone."
        )

        if not prompt:
            return await ctx.send("Good, I didn't want to delete them anyway.")

        deleted = await self.bot.pool.fetch(
            "DELETE FROM guild_name_logs WHERE guild_id = $1 RETURNING target_id",
            guild.id,
        )

        await ctx.send(f"Deleted {plural(len(deleted)):guild name}")

    @commands.group(name="opt", invoke_without_command=True)
    async def opt_group(self, ctx: Context):
        """Opt in or out of a logger

        Due to technical reasons, opting out from `guild names`, `guild bans` and `guild icons` is not possible yet, but you can still delete the data at any time."""
        items: Set[str] = await ctx.redis.smembers(f"opted_out:{ctx.author.id}")

        if items == set():
            raise BlankException(
                "You haven't opted out of any loggers. good on you \U0001f609"
            )

        await ctx.send(
            f"You have opted out from {human_join([f'`{item}`' for item in items], final='and')}"
        )

    @opt_group.command(name="in")
    async def opt_in(self, ctx: Context, *, logger: str):
        if logger.lower() not in Logger:
            raise BlankException(
                f"Logger must be one of {human_join([f'`{log}`' for log in Logger])}"
            )

        sql = """UPDATE opted_out SET items = array_remove(opted_out.items, $1) WHERE user_id = $2"""

        await ctx.pool.execute(sql, logger, ctx.author.id)
        await ctx.redis.srem(f"opted_out:{ctx.author.id}", logger)
        await ctx.send(str(CHECK))

    @opt_group.command(name="out")
    async def opt_out(self, ctx: Context, *, logger: str):
        if logger.lower() not in Logger:
            raise BlankException(
                f"Logger must be one of {human_join([f'`{log}`' for log in Logger])}"
            )

        sql = """
        INSERT INTO opted_out (user_id, items) VALUES ($1, ARRAY [$2]) 
        ON CONFLICT (user_id) DO UPDATE
        SET items = array_append(opted_out.items, $2) 
        WHERE opted_out.user_id = $1
        """

        await ctx.pool.execute(sql, ctx.author.id, logger)
        await ctx.redis.sadd(f"opted_out:{ctx.author.id}", logger)
        await ctx.send(str(CHECK))

    @commands.command(
        name="fm-reactions",
        invoke_without_command=True,
        aliases=("fmr", "fm_reactions"),
    )
    async def fm_reactions(self, ctx: Context):
        """Toggles auto reactions to fish fm commands for yourself."""

        sql = """
        INSERT INTO user_settings (user_id, fm_autoreact) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE
        SET fm_autoreact = NOT user_settings.fm_autoreact
        WHERE user_settings.user_id = $1
        RETURNING *
        """
        results: Dict[Any, Any] = await self.bot.pool.fetchrow(sql, ctx.author.id, True)
        value: bool = results["fm_autoreact"]

        if value:
            await self.bot.redis.sadd("fm_autoreactions", ctx.author.id)
        else:
            await self.bot.redis.srem("fm_autoreactions", ctx.author.id)

        await ctx.send(
            f"{'Enabled' if value else 'Disabled'} auto-reactions for the fm command for you."
        )

    @commands.group(
        name="auto-reactions",
        invoke_without_command=True,
        aliases=("ar", "auto_reactions"),
    )
    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(add_reactions=True)
    async def auto_reactions(self, ctx: Context):
        """Toggles auto reactions to media posts in this server."""

        sql = """
        INSERT INTO guild_settings (guild_id, auto_reactions) VALUES ($1, $2)
        ON CONFLICT (guild_id) DO UPDATE
        SET auto_reactions = NOT guild_settings.auto_reactions
        WHERE guild_settings.guild_id = $1
        RETURNING *
        """
        results: Dict[Any, Any] = await self.bot.pool.fetchrow(sql, ctx.guild.id, True)
        value: bool = results["auto_reactions"]

        if value:
            await self.bot.redis.sadd("auto_reactions", ctx.guild.id)
        else:
            await self.bot.redis.srem("auto_reactions", ctx.guild.id)

        await ctx.send(
            f"{'Enabled' if value else 'Disabled'} auto-reactions in this server."
        )
