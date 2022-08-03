import textwrap
import discord
from bot import Bot, Context
from dateutil import parser
from discord.ext import commands
from utils import FieldPageSource, Pager, RobloxAccountConverter, to_thread
from utils.roblox import *  # smd


async def setup(bot: Bot):
    await bot.add_cog(Roblox(bot))


class Roblox(commands.Cog, name="roblox"):
    """Roblox related commands"""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @commands.group(name="roblox", aliases=("rbx",), invoke_without_command=True)
    async def roblox(
        self,
        ctx: Context,
        *,
        account: int = commands.parameter(
            converter=RobloxAccountConverter,
            default=None,
            displayed_default="[roblox account]",
        ),
    ):
        """Get information about a roblox account"""

        async with ctx.typing():
            user = account or await RobloxAccountConverter().convert(
                ctx, str(ctx.author)
            )

            info = await fetch_info(ctx.bot.session, user)

            embed = discord.Embed(timestamp=parser.parse(info["created"]))
            embed.description = textwrap.shorten(info["description"], 100)

            name = (
                info["name"]
                if info["name"] == info["displayName"]
                else f'{info["name"]}  •  {info["displayName"]}'
            )
            embed.set_author(name=name, icon_url=f"attachment://{user}_headshot.png")

            followers = await fetch_followers_count(ctx.bot.session, user)
            friends = await fetch_friend_count(ctx.bot.session, user)
            embed.add_field(
                name="Followers",
                value=f"Followers: {followers:,}\nFriends: {friends:,}",
            )

            rblx_info = await fetch_rblx_trade_user_info(ctx.bot.session, user)
            rap = f'{rblx_info["accountRAP"]:,}'
            value = f'{rblx_info["accountValue"]:,}'

            embed.add_field(name="Value", value=f"Value: {value}\nRAP: {rap}")
            embed.add_field(
                name="Place vists", value=f'{rblx_info["placeVisitCount"]:,}'
            )

            onlinestatus = await fetch_onlinestatus(ctx.bot.session, user)
            onlinestatus_str = ["Offline", "Online"][onlinestatus["IsOnline"]]
            if not onlinestatus["IsOnline"]:
                onlinestatus_str += f'\n{ctx.bot.e_reply}Last seen {discord.utils.format_dt(parser.parse(onlinestatus["LastOnline"]), "R")}'

            embed.add_field(name="Status", value=onlinestatus_str)

            _badges = await fetch_badges(ctx.bot.session, user)
            badges = ", ".join([data["name"] for data in _badges])

            embed.set_footer(text=f"ID: {user}\nBadges: {badges}\nCreated")

            headshot = discord.File(
                await ctx.to_image(await fetch_headshot(ctx.bot.session, user)),
                f"{user}_headshot.png",
            )

        await ctx.send(embed=embed, files=[headshot])

    @roblox.command(name="set")
    async def roblox_set(self, ctx: Context, username: str):
        """Alias for set roblox command"""

        command = self.bot.get_command("set roblox")

        if command is None:
            return

        await command(ctx, username=username)

    @commands.command(name="friends")
    async def friends(
        self,
        ctx: Context,
        *,
        account: int = commands.parameter(
            converter=RobloxAccountConverter,
            default=None,
            displayed_default="[roblox account]",
        ),
    ):
        """Get the friends of a roblox account"""

        user = account or await RobloxAccountConverter().convert(ctx, str(ctx.author))
        name = (await fetch_info(ctx.bot.session, user))["name"]
        friends = await fetch_friends(ctx.bot.session, user)

        if not friends["data"]:
            raise TypeError(f"{name} has no friends.")

        entries = [
            (
                data["name"]
                if data["name"] == data["displayName"]
                else f'{data["name"]}  •  {data["displayName"]}',
                f'ID: `{data["id"]}`',
            )
            for data in friends["data"]
        ]
        # \nCreated: {discord.utils.format_dt(parser.parse(data["created"]), "D")} # api gives inacurate date, saving for later if ever fixed

        p = FieldPageSource(entries, per_page=4)
        p.embed.title = f"{name}'s friends"
        menu = Pager(p, ctx=ctx)
        await menu.start(ctx)