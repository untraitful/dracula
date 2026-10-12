"""Variables and bleed-style embed scripts.

Variables look like `{user.mention}` and are replaced against a member/guild.

An embed script is a message that starts with `{embed}` and has parts joined by `$v`:

    {embed}$v{title: welcome {user.name}}$v{description: enjoy your stay}$v{color: #8a0303}

Supported parts: content, title, description, color, url, author, footer,
thumbnail, image, timestamp, field, button. Multi-value parts use `&&`:

    {author: name && icon url}   {footer: text && icon url}
    {field: name && value && inline}   {button: label && url}
"""

import re
from typing import Optional, Tuple

import discord

from core import theme

VARIABLE_HELP = {
    "{user}": "username (e.g. vlad)",
    "{user.mention}": "mentions the member",
    "{user.name}": "username",
    "{user.display_name}": "display name in the server",
    "{user.id}": "member id",
    "{user.avatar}": "avatar url",
    "{user.created_at}": "account creation (relative timestamp)",
    "{user.joined_at}": "server join (relative timestamp)",
    "{guild.name}": "server name",
    "{guild.id}": "server id",
    "{guild.count}": "member count",
    "{guild.count.format}": "member count as an ordinal (1st, 2nd...)",
    "{guild.icon}": "server icon url",
    "{guild.boost_count}": "number of boosts",
    "{guild.boost_tier}": "boost level",
}


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def replace_variables(text: str, member: Optional[discord.Member] = None, guild: Optional[discord.Guild] = None) -> str:
    guild = guild or (member.guild if isinstance(member, discord.Member) else None)
    values = {}
    if member is not None:
        joined = getattr(member, "joined_at", None)
        values.update({
            "{user}": member.name,
            "{user.mention}": member.mention,
            "{user.name}": member.name,
            "{user.display_name}": member.display_name,
            "{user.id}": str(member.id),
            "{user.avatar}": member.display_avatar.url,
            "{user.created_at}": discord.utils.format_dt(member.created_at, "R"),
            "{user.joined_at}": discord.utils.format_dt(joined, "R") if joined else "unknown",
        })
    if guild is not None:
        values.update({
            "{guild.name}": guild.name,
            "{guild.id}": str(guild.id),
            "{guild.count}": str(guild.member_count),
            "{guild.count.format}": ordinal(guild.member_count or 0),
            "{guild.icon}": guild.icon.url if guild.icon else "",
            "{guild.boost_count}": str(guild.premium_subscription_count),
            "{guild.boost_tier}": str(guild.premium_tier),
        })
    for key, value in values.items():
        text = text.replace(key, value)
    return text


_PART = re.compile(r"^\{\s*(\w+)\s*:\s*(.*)\}$", re.S)


def _parse_color(value: str) -> int:
    value = value.strip().lstrip("#")
    try:
        return int(value, 16)
    except ValueError:
        return theme.CRIMSON


def parse_script(text: str) -> Tuple[Optional[str], Optional[discord.Embed], Optional[discord.ui.View]]:
    """Turn a (variable-replaced) script into content / embed / view."""
    if not text.lstrip().lower().startswith("{embed}"):
        return text, None, None

    embed = discord.Embed(color=theme.CRIMSON)
    content = None
    view = None
    has_embed_content = False

    for raw in text.split("$v")[1:]:
        match = _PART.match(raw.strip())
        if not match:
            continue
        key, value = match.group(1).lower(), match.group(2).strip()
        args = [a.strip() for a in value.split("&&")]

        if key == "content":
            content = value
        elif key == "title":
            embed.title = value[:256]
        elif key == "description":
            embed.description = value[:4096]
        elif key in ("color", "colour"):
            embed.color = _parse_color(value)
        elif key == "url":
            embed.url = value
        elif key == "author":
            embed.set_author(name=args[0][:256], icon_url=args[1] if len(args) > 1 and args[1] else None)
        elif key == "footer":
            embed.set_footer(text=args[0][:2048], icon_url=args[1] if len(args) > 1 and args[1] else None)
        elif key == "thumbnail":
            embed.set_thumbnail(url=value)
        elif key == "image":
            embed.set_image(url=value)
        elif key == "timestamp":
            embed.timestamp = discord.utils.utcnow()
        elif key == "field" and len(args) >= 2:
            inline = len(args) > 2 and args[2].lower() in ("true", "yes", "inline")
            embed.add_field(name=args[0][:256], value=args[1][:1024], inline=inline)
        elif key == "button" and len(args) >= 2 and args[1].startswith("http"):
            view = view or discord.ui.View()
            view.add_item(discord.ui.Button(label=args[0][:80], url=args[1]))
        else:
            continue
        if key not in ("content", "button", "color", "colour"):
            has_embed_content = True

    return content, (embed if has_embed_content else None), view


async def send_script(
    destination: discord.abc.Messageable,
    script: str,
    member: Optional[discord.Member] = None,
    guild: Optional[discord.Guild] = None,
) -> Optional[discord.Message]:
    content, embed, view = parse_script(replace_variables(script, member, guild))
    if not content and not embed:
        return None
    kwargs = {"content": content, "embed": embed}
    if view is not None:
        kwargs["view"] = view
    return await destination.send(**kwargs, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
