import discord
from discord.ext import commands


class UnknownAccount(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class VideoIsLive(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class NotTenorUrl(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class ResponseError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class ServerErrorResponse(ResponseError):
    pass


class BadGateway(ServerErrorResponse):
    pass


class ClientErrorResponse(ResponseError):
    pass


class NotFound(ClientErrorResponse):
    pass


class Unauthorized(ClientErrorResponse):
    pass


class BadRequest(ClientErrorResponse):
    pass


class Forbidden(ClientErrorResponse):
    pass


class ImageTooLarge(commands.BadArgument):
    pass


class InvalidColor(commands.BadArgument):
    pass


class RateLimitExceeded(commands.BadArgument):
    pass


class NoCover(commands.BadArgument):
    pass


class InvalidDateProvided(commands.BadArgument):
    pass


IGNORED = (
    commands.CommandNotFound,
    commands.NotOwner,
    commands.CheckFailure,
)
SEND = (
    VideoIsLive,
    NotTenorUrl,
    discord.HTTPException,
    TypeError,
    ValueError,
    commands.GuildNotFound,
    commands.UserNotFound,
    commands.BadArgument,
    commands.MissingRequiredArgument,
    commands.TooManyArguments,
    commands.UserInputError,
    UnknownAccount,
    commands.BotMissingPermissions,
    commands.MissingPermissions,
    ServerErrorResponse,
    BadGateway,
    ClientErrorResponse,
    NotFound,
    Unauthorized,
    BadRequest,
    Forbidden,
    ImageTooLarge,
    InvalidColor,
    RateLimitExceeded,
    NoCover,
)