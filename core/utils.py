"""Shared helpers: durations, hierarchy checks."""

import re
from datetime import timedelta

import discord
from discord.ext import commands

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION = re.compile(r"(\d+)\s*([smhdw])", re.I)


class Duration(commands.Converter):
    """Converts strings like `10m`, `1h30m`, `2d` to a timedelta."""

    async def convert(self, ctx, argument: str) -> timedelta:
        matches = _DURATION.findall(argument)
        if not matches or "".join(f"{n}{u}" for n, u in matches).lower() != argument.replace(" ", "").lower():
            raise commands.BadArgument(f"`{argument}` is not a duration the dead understand (try `10m`, `2h`, `1d`)")
        seconds = sum(int(n) * _UNITS[u.lower()] for n, u in matches)
        return timedelta(seconds=seconds)


def human_delta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    parts = []
    for name, size in (("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount} {name}{'s' if amount != 1 else ''}")
    return ", ".join(parts) or "0 seconds"


async def can_moderate(ctx, target: discord.Member, action: str) -> bool:
    """Bleed-style hierarchy checks. Replies with a denial and returns False if not allowed."""
    if target == ctx.author:
        await ctx.warn(f"you cannot **{action}** yourself, mortal")
        return False
    if target == ctx.guild.owner:
        await ctx.warn(f"you cannot **{action}** the lord of this castle")
        return False
    if target == ctx.guild.me:
        await ctx.warn(f"you cannot **{action}** me, i am eternal")
        return False
    if ctx.author != ctx.guild.owner and target.top_role >= ctx.author.top_role:
        await ctx.warn(f"you cannot **{action}** {target.mention}, their bloodline outranks yours")
        return False
    if target.top_role >= ctx.guild.me.top_role:
        await ctx.warn(f"i cannot **{action}** {target.mention}, their role sits above mine")
        return False
    return True


async def can_manage_role(ctx, role: discord.Role) -> bool:
    if role.is_default() or role.managed:
        await ctx.warn(f"{role.mention} cannot be given or taken")
        return False
    if role >= ctx.guild.me.top_role:
        await ctx.warn(f"{role.mention} sits above my highest role")
        return False
    if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
        await ctx.warn(f"{role.mention} sits above your highest role")
        return False
    return True
