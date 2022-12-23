from __future__ import annotations

import asyncio
import datetime
import math
import re
import sys
import textwrap
from io import BytesIO
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import aiohttp
import discord
from aiohttp import ClientResponse
from dateutil.relativedelta import relativedelta
from discord.ext import commands
from PIL import Image as PImage
from PIL import ImageSequence
from wand.image import Image as wImage

from ..vars import USER_FLAGS, VIDEOS_RE, P, T, video_regexes
from ..vars.errors import (
    BadGateway,
    BadRequest,
    Forbidden,
    NoCover,
    NotFound,
    ResponseError,
    ServerErrorResponse,
    Unauthorized,
    UnknownAccount,
)
from .classes import plural

if TYPE_CHECKING:
    from bot import Bot
    from cogs.context import Context


async def get_lastfm_data(
    bot: Bot,
    version: str,
    method: str,
    endpoint: str,
    query: str,
    extras: Optional[Dict] = None,
) -> Dict[Any, Any]:

    url = f"http://ws.audioscrobbler.com/{version}/"

    params: Dict[Any, Any] = {
        "method": method,
        endpoint: query,
        "api_key": bot.config["keys"]["lastfm-key"],
        "format": "json",
    }

    if extras:
        params.update(extras)

    async with bot.session.get(url, params=params) as response:
        response_checker(response)
        return await response.json()


async def get_steam_data(
    bot: Bot,
    endpoint: str,
    version: str,
    account: int,
    ids: bool = False,
) -> Dict:
    url = f"https://api.steampowered.com/{endpoint}/{version}"

    params: Dict[str, Any] = {
        "key": bot.config["keys"]["steam-key"],
        f"steamid{'s' if ids else ''}": account,
    }

    async with bot.session.get(url, params=params) as response:
        response_checker(response)
        return await response.json()


async def get_sp_cover(bot: Bot, query: str) -> Tuple[str, bool]:
    url = "https://api.spotify.com/v1/search"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bot.spotify_key}",
    }

    data = {"q": query, "type": "album", "market": "ES", "limit": "1"}

    async with bot.session.get(url, headers=headers, params=data) as r:
        results = await r.json()

    try:
        return results["albums"]["items"][0]["images"][0]["url"], results["albums"][
            "items"
        ][0]["id"] in await bot.redis.smembers("nsfw_covers")
    except (IndexError, KeyError):
        raise NoCover("No cover found for this album, sorry.")


def to_thread(func: Callable[P, T]) -> Callable[P, Awaitable[T]]:
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


async def get_twemoji(
    session: aiohttp.ClientSession, emoji: str, *, svg: bool = True
) -> Optional[bytes]:
    try:
        folder = ("72x72", "svg")[svg]
        ext = ("png", "svg")[svg]
        formatted = "-".join([f"{ord(char):x}" for char in emoji])
        url = f"https://twemoji.maxcdn.com/v/latest/{folder}/{formatted}.{ext}"

        async with session.get(url) as r:
            if r.ok:
                byt = await r.read()
                if svg:
                    return await svgbytes_to_btyes(byt)
                else:
                    return byt

    except Exception:
        return None


@to_thread
def svgbytes_to_btyes(svg: bytes) -> bytes:
    with wImage(
        blob=svg, format="svg", width=500, height=500, background="none"
    ) as asset:
        _img = asset.make_blob("png")

    if _img is not None:
        return _img

    raise TypeError("Failed to convert svg to bytes")


async def template(session: aiohttp.ClientSession, assetID: int) -> BytesIO:
    async with session.get(
        f"https://assetdelivery.roblox.com/v1/asset?id={assetID}"
    ) as r:
        if r.status == 200:
            text = await r.text()
            results = re.search(r"\?id=(?P<id>[0-9]+)", text)
            if results:
                img = await to_bytesio(
                    session,
                    url=f"https://assetdelivery.roblox.com/v1/asset?id={results.group('id')}",
                )
                return img

        raise TypeError(f"Sorry, I couldn't find that asset.`")


async def to_bytesio(
    session: aiohttp.ClientSession, url: str, skip_check: bool = False
) -> BytesIO:
    async with session.get(url) as resp:
        if not skip_check:
            response_checker(resp)

        data = await resp.read()

        return BytesIO(data)


async def to_bytes(
    session: aiohttp.ClientSession, url: str, skip_check: bool = False
) -> bytes:
    async with session.get(url) as resp:
        if not skip_check:
            response_checker(resp)

        data = await resp.read()

    return data


async def mobile(self) -> None:
    """Sends the IDENTIFY packet."""
    payload = {
        "op": self.IDENTIFY,
        "d": {
            "token": self.token,
            "properties": {
                "$os": sys.platform,
                "$browser": "Discord iOS",
                "$device": "discord.py",
                "$referrer": "",
                "$referring_domain": "",
            },
            "compress": True,
            "large_threshold": 250,
        },
    }

    if self.shard_id is not None and self.shard_count is not None:
        payload["d"]["shard"] = [self.shard_id, self.shard_count]

    state = self._connection
    if state._activity is not None or state._status is not None:
        payload["d"]["presence"] = {
            "status": state._status,
            "game": state._activity,
            "since": 0,
            "afk": False,
        }

    if state._intents is not None:
        payload["d"]["intents"] = state._intents.value

    await self.call_hooks(
        "before_identify", self.shard_id, initial=self._initial_identify
    )
    await self.send_as_json(payload)


def add_prefix(bot: Bot, guild_id: int, prefix: str):
    try:
        bot.prefixes[guild_id].append(prefix)
    except KeyError:
        bot.prefixes[guild_id] = [prefix]


async def get_lastfm(bot: Bot, user_id: int) -> str:
    """Get the last.fm username for the given user ID."""
    name = await bot.redis.hget(f"accounts:{user_id}", "lastfm")
    if not name:
        raise UnknownAccount("No last.fm account set.")
    return name


async def get_roblox(bot: Bot, user_id: int) -> str:
    """Get the roblox username for the given user ID."""
    name = await bot.redis.hget(f"accounts:{user_id}", "roblox")
    if not name:
        raise UnknownAccount("No roblox account set.")
    return name


async def get_genshin(bot: Bot, user_id: int) -> str:
    """Get the genshin UID for the given user ID."""
    name = await bot.redis.hget(f"accounts:{user_id}", "genshin")
    if not name:
        raise UnknownAccount("No genshin account set.")
    return name


async def get_osu(bot: Bot, user_id: int) -> str:
    """Get the osu! username for the given user ID."""
    name = await bot.redis.hget(f"accounts:{user_id}", "osu")
    if name is None:
        raise UnknownAccount("No osu! account set.")
    return name


async def get_user_badges(
    member: Union[discord.Member, discord.User],
    ctx: Context,
    fetched_user: Optional[discord.User] = None,
) -> List:
    flags = dict(member.public_flags)

    user_flags = []
    if await ctx.bot.is_owner(member):
        user_flags.append(f"<:cr_owner:972016928371654676> Bot Owner")

    if isinstance(member, discord.Member) and member.guild.owner == member:
        user_flags.append(f"<:owner:949147456376033340> Server Owner")

    if isinstance(member, discord.Member) and member.premium_since:
        user_flags.append(f"<:booster:949147430786596896> Server Booster")

    if member.display_avatar.is_animated() or fetched_user and fetched_user.banner:
        user_flags.append(f"<:nitro:949147454991896616> Nitro")

    for flag, text in USER_FLAGS.items():
        try:
            if flags[flag]:
                user_flags.append(text)
        except KeyError:
            continue

    return user_flags


async def get_video(ctx: Context, url: str, auto: bool = False) -> Optional[str]:
    if not VIDEOS_RE.search(url):
        return None

    for _, data in video_regexes.items():
        results = data["regex"].search(url)
        if results:
            if data["nsfw"] and not ctx.channel.is_nsfw():
                msg = "The site given has been marked as NSFW, please switch to a NSFW channel."
                if auto:
                    await ctx.send(msg)
                    return

                raise commands.BadArgument(msg)

            return results.group()


def natural_size(size_in_bytes: int) -> str:
    """
    Converts a number of bytes to an appropriately-scaled unit
    E.g.:
        1024 -> 1.00 KiB
        12345678 -> 11.77 MiB
    """
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")

    power = int(math.log(max(abs(size_in_bytes), 1), 1024))

    return f"{size_in_bytes / (1024 ** power):.2f} {units[power]}"


async def run(cmd: str) -> Optional[str]:

    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if stdout:
        return f"[stdout]\n{stdout.decode()}"

    if stderr:
        raise TypeError(f"[stderr]\n{stderr.decode()}")


def cleanup_code(content: str) -> str:
    """Automatically removes code blocks from the code."""

    if content.startswith("```") and content.endswith("```"):
        return "\n".join(content.split("\n")[1:-1])

    return content.strip("` \n")


def human_join(seq: Sequence[str], delim=", ", final="or", spaces: bool = True) -> str:
    size = len(seq)
    if size == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {final} {seq[1]}"

    final = f" {final} " if spaces else final
    return delim.join(seq[:-1]) + f"{final}{seq[-1]}"


def human_timedelta(
    dt: datetime.datetime,
    *,
    source: Optional[datetime.datetime] = None,
    accuracy: Optional[int] = 3,
    brief: bool = False,
    suffix: bool = True,
) -> str:
    now = source or datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)

    # Microsecond free zone
    now = now.replace(microsecond=0)
    dt = dt.replace(microsecond=0)

    # This implementation uses relativedelta instead of the much more obvious
    # divmod approach with seconds because the seconds approach is not entirely
    # accurate once you go over 1 week in terms of accuracy since you have to
    # hardcode a month as 30 or 31 days.
    # A query like "11 months" can be interpreted as "!1 months and 6 days"
    if dt > now:
        delta = relativedelta(dt, now)
        output_suffix = ""
    else:
        delta = relativedelta(now, dt)
        output_suffix = " ago" if suffix else ""

    attrs = [
        ("year", "y"),
        ("month", "mo"),
        ("day", "d"),
        ("hour", "h"),
        ("minute", "m"),
        ("second", "s"),
    ]

    output = []
    for attr, brief_attr in attrs:
        elem = getattr(delta, attr + "s")
        if not elem:
            continue

        if attr == "day":
            weeks = delta.weeks
            if weeks:
                elem -= weeks * 7
                if not brief:
                    output.append(format(plural(weeks), "week"))
                else:
                    output.append(f"{weeks}w")

        if elem <= 0:
            continue

        if brief:
            output.append(f"{elem}{brief_attr}")
        else:
            output.append(format(plural(elem), attr))

    if accuracy is not None:
        output = output[:accuracy]

    if len(output) == 0:
        return "now"
    else:
        if not brief:
            return human_join(output, final="and") + output_suffix
        else:
            return " ".join(output) + output_suffix


def format_relative(dt: datetime.datetime) -> str:
    return discord.utils.format_dt(dt, "R")


# https://github.com/CuteFwan/Koishi/blob/master/cogs/avatar.py#L82-L102
@to_thread
def format_bytes(filesize_limit: int, images: List[bytes]) -> BytesIO:
    xbound = math.ceil(math.sqrt(len(images)))
    ybound = math.ceil(len(images) / xbound)
    size = int(2520 / xbound)

    with PImage.new(
        "RGBA", size=(xbound * size, ybound * size), color=(0, 0, 0, 0)
    ) as base:
        x, y = 0, 0
        for avy in images:
            if avy:
                im = PImage.open(BytesIO(avy)).resize(
                    (size, size), resample=PImage.BICUBIC
                )
                base.paste(im, box=(x * size, y * size))
            if x < xbound - 1:
                x += 1
            else:
                x = 0
                y += 1
        buffer = BytesIO()
        base.save(buffer, "png")
        buffer.seek(0)
        buffer = resize_to_limit(buffer, filesize_limit)
        return buffer


# https://github.com/CuteFwan/Koishi/blob/master/cogs/utils/images.py#L4-L34
def resize_to_limit(data: BytesIO, limit: int) -> BytesIO:
    """
    Downsize it for huge PIL images.
    Half the resolution until the byte count is within the limit.
    """
    current_size = data.getbuffer().nbytes
    while current_size > limit:
        with PImage.open(data) as im:
            data = BytesIO()
            if im.format == "PNG":
                im = im.resize(
                    tuple([i // 2 for i in im.size]), resample=PImage.BICUBIC
                )
                im.save(data, "png")
            elif im.format == "GIF":
                durations = []
                new_frames = []
                for frame in ImageSequence.Iterator(im):
                    durations.append(frame.info["duration"])
                    new_frames.append(
                        frame.resize([i // 2 for i in im.size], resample=PImage.BICUBIC)
                    )
                new_frames[0].save(
                    data,
                    save_all=True,
                    append_images=new_frames[1:],
                    format="gif",
                    version=im.info["version"],
                    duration=durations,
                    loop=0,
                    transparency=0,
                    background=im.info["background"],
                    palette=im.getpalette(),
                )
            data.seek(0)
            current_size = data.getbuffer().nbytes
    return data


def response_checker(response: ClientResponse) -> bool:
    if response.status == 200:
        return True
    elif response.status == 502:
        raise BadGateway("The server is down or under maintenance, try again later.")
    elif response.status == 404:
        raise NotFound("The requested resource could not be found.")
    elif response.status == 400:
        raise BadRequest("The request was invalid.")
    elif response.status == 401:
        raise Unauthorized("The request requires authentication.")
    elif response.status == 403:
        raise Forbidden("The request was forbidden.")
    elif str(response.status).startswith("5"):
        reason = (
            f"\nReason: {textwrap.shorten(response.reason, 100)}"
            if response.reason
            else ""
        )
        raise ServerErrorResponse(
            f"The server returned an error ({response.status}). {reason}"
        )
    else:
        raise ResponseError(
            f"Something went wrong, try again later? \nStatus code: `{response.status}`"
        )


def is_table(ctx: Context) -> bool:
    return ctx.guild.id == 848507662437449750


def has_mod(ctx: Context) -> bool:
    return 884182961702977599 in [r.id for r in ctx.author.roles]


def yes_no():
    return "no"