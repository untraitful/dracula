import logging
import os
import time

import discord
from discord.ext import commands

from core.context import Context
from core.database import Database

log = logging.getLogger("dracula")

DEFAULT_PREFIX = "$"

EXTENSIONS = [
    "cogs.events",
    "cogs.help",
    "cogs.information",
    "cogs.moderation",
    "cogs.utility",
    "cogs.servers",
    "cogs.embeds",
    "cogs.roles",
    "cogs.voicemaster",
    "cogs.antinuke",
]


async def get_prefix(bot: "Dracula", message: discord.Message):
    prefix = DEFAULT_PREFIX
    if message.guild:
        prefix = bot.prefixes.get(message.guild.id, DEFAULT_PREFIX)
    return commands.when_mentioned_or(prefix)(bot, message)


class Dracula(commands.Bot):
    def __init__(self, owner_ids=None, db_path: str = "dracula.db"):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = False
        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            case_insensitive=True,
            strip_after_prefix=True,
            owner_ids=set(owner_ids or []),
            allowed_mentions=discord.AllowedMentions.none(),  # v2 text pings, so mentions are opt-in
            activity=discord.Activity(type=discord.ActivityType.watching, name=f"the crypt • {DEFAULT_PREFIX}help"),
        )
        self.db = Database(db_path)
        self.prefixes: dict[int, str] = {}
        self.started = time.time()

    async def get_context(self, message, *, cls=Context):
        return await super().get_context(message, cls=cls)

    async def setup_hook(self):
        await self.db.connect()
        for row in await self.db.fetchall("SELECT guild_id, prefix FROM prefixes"):
            self.prefixes[row["guild_id"]] = row["prefix"]
        for ext in EXTENSIONS:
            await self.load_extension(ext)
            log.info("loaded %s", ext)

    async def close(self):
        await self.db.close()
        await super().close()

    async def on_ready(self):
        log.info("risen as %s (%s) in %d guilds", self.user, self.user.id, len(self.guilds))

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # like bleed: editing a message re-runs the command
        if before.content != after.content:
            await self.process_commands(after)

    async def on_command_error(self, ctx: Context, error: commands.CommandError):
        error = getattr(error, "original", error)
        if isinstance(error, (commands.CommandNotFound, commands.NotOwner)):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.send_help(ctx.command)
        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
            return await ctx.warn(f"you lack the **{perms}** permission to wield this")
        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
            return await ctx.warn(f"i lack the **{perms}** permission to do that")
        if isinstance(error, commands.MemberNotFound):
            return await ctx.warn(f"no soul named **{error.argument}** walks these halls")
        if isinstance(error, commands.UserNotFound):
            return await ctx.warn(f"no soul named **{error.argument}** exists")
        if isinstance(error, commands.RoleNotFound):
            return await ctx.warn(f"no bloodline named **{error.argument}** exists")
        if isinstance(error, commands.ChannelNotFound):
            return await ctx.warn(f"no chamber named **{error.argument}** exists")
        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.warn(f"patience... try again in **{error.retry_after:.1f}s**")
        if isinstance(error, commands.NoPrivateMessage):
            return await ctx.warn("this rite can only be performed inside a server")
        if isinstance(error, commands.CheckFailure):
            return await ctx.warn(str(error) or "the spirits forbid you from doing that")
        if isinstance(error, (commands.BadArgument, commands.BadUnionArgument, commands.BadLiteralArgument)):
            return await ctx.warn(str(error))
        if isinstance(error, discord.Forbidden):
            return await ctx.warn("i lack the power to do that here")
        log.exception("unhandled error in %s", ctx.command, exc_info=error)
        await ctx.deny(f"a curse befell this command: `{type(error).__name__}`")


def load_owner_ids() -> list[int]:
    raw = os.getenv("OWNER_IDS", "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()]
