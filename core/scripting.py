"""Variables and bleed-style embed scripts, rendered as components v2 cards.

Variables look like `{user.mention}` and are replaced against a member/guild.

An embed script is a message that starts with `{embed}` and has parts joined by `$v`:

    {embed}$v{title: welcome {user.name}}$v{description: enjoy your stay}$v{color: #8a0303}

Supported parts: content, title, description, color, url, author, footer,
thumbnail, image, timestamp, field, button. Multi-value parts use `&&`:

    {field: name && value}   {button: label && url}

Scripts are rendered as a v2 container: the colour becomes the accent bar, the
thumbnail sits beside the title, the image becomes a media gallery and buttons
live inside the card. (Author and footer icons from old scripts are ignored,
v2 cards have nowhere to put them.)
"""

import re
import time
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple

import discord

from core import theme, ui

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

MAX_FIELDS = 25
MAX_BUTTONS = 5


def parse_hex(value: str) -> Optional[int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def is_script(text: str) -> bool:
    return text.lstrip().lower().startswith("{embed}")


def iter_parts(text: str) -> Iterator[Tuple[str, str, List[str]]]:
    """Yield (key, raw value, `&&`-split args) for each part of an embed script."""
    for raw in text.split("$v")[1:]:
        match = _PART.match(raw.strip())
        if not match:
            continue
        value = match.group(2).strip()
        yield match.group(1).lower(), value, [a.strip() for a in value.split("&&")]


@dataclass
class Draft:
    """An embed script as data. Serialises to / from script text and renders to v2 items."""

    content: str = ""
    title: str = ""
    description: str = ""
    url: str = ""
    color: int = theme.CRIMSON
    author: str = ""
    footer: str = ""
    thumbnail: str = ""
    image: str = ""
    timestamp: bool = False
    fields: List[Tuple[str, str]] = field(default_factory=list)
    buttons: List[Tuple[str, str]] = field(default_factory=list)

    # ---- script text

    def to_script(self) -> str:
        parts = ["{embed}"]

        def add(key: str, *values: str):
            parts.append(f"{{{key}: {' && '.join(values)}}}")

        if self.content:
            add("content", self.content)
        if self.author:
            add("author", self.author)
        if self.title:
            add("title", self.title)
        if self.url:
            add("url", self.url)
        if self.description:
            add("description", self.description)
        add("color", f"#{self.color:06x}")
        if self.thumbnail:
            add("thumbnail", self.thumbnail)
        for name, value in self.fields:
            add("field", name, value)
        if self.image:
            add("image", self.image)
        if self.footer:
            add("footer", self.footer)
        if self.timestamp:
            add("timestamp", "true")
        for label, url in self.buttons:
            add("button", label, url)
        return "$v".join(parts)

    @classmethod
    def from_script(cls, text: str) -> "Draft":
        draft = cls()
        if not is_script(text):
            draft.content = text.strip()
            return draft
        for key, value, args in iter_parts(text):
            if key == "content":
                draft.content = value
            elif key == "title":
                draft.title = value[:256]
            elif key == "description":
                draft.description = value[:4000]
            elif key in ("color", "colour"):
                draft.color = parse_hex(value) or theme.CRIMSON
            elif key == "url":
                draft.url = value
            elif key == "author":
                draft.author = args[0][:256]
            elif key == "footer":
                draft.footer = args[0][:2048]
            elif key == "thumbnail":
                draft.thumbnail = value
            elif key == "image":
                draft.image = value
            elif key == "timestamp":
                draft.timestamp = True
            elif key == "field" and len(args) >= 2 and len(draft.fields) < MAX_FIELDS:
                draft.fields.append((args[0][:256], args[1][:1024]))
            elif key == "button" and len(args) >= 2 and len(draft.buttons) < MAX_BUTTONS:
                if args[1].startswith(("http://", "https://")):
                    draft.buttons.append((args[0][:80], args[1]))
        return draft

    # ---- rendering

    @property
    def has_card(self) -> bool:
        return any((self.title, self.description, self.author, self.footer, self.thumbnail,
                    self.image, self.timestamp, self.fields, self.buttons))

    @property
    def empty(self) -> bool:
        return not self.content and not self.has_card

    def render_items(self) -> List[discord.ui.Item]:
        """Top-level v2 items: optional message text, then the accented card."""
        items: List[discord.ui.Item] = []
        if self.content:
            items.append(discord.ui.TextDisplay(self.content[:2000]))
        if not self.has_card:
            return items

        card = discord.ui.Container(accent_colour=self.color)
        head = []
        if self.author:
            head.append(ui.small(self.author))
        if self.title:
            head.append(f"## [{self.title}]({self.url})" if self.url else f"## {self.title}")
        if self.description:
            head.append(self.description)
        if head or self.thumbnail:
            card.add_item(ui.section("\n".join(head) or "\u200b", thumbnail=self.thumbnail or None))
        if self.fields:
            if head or self.thumbnail:
                card.add_item(ui.sep())
            card.add_item(discord.ui.TextDisplay("\n\n".join(f"**{name}**\n{value}" for name, value in self.fields)))
        if self.image:
            card.add_item(ui.gallery(self.image))
        foot = [self.footer] if self.footer else []
        if self.timestamp:
            foot.append(f"<t:{int(time.time())}:f>")
        if foot:
            card.add_item(ui.sep())
            card.add_item(discord.ui.TextDisplay(ui.small(" • ".join(foot))))
        if self.buttons:
            card.add_item(ui.link_row(*self.buttons))
        items.append(card)
        return items

    def render(self) -> Optional[discord.ui.LayoutView]:
        items = self.render_items()
        if not items:
            return None
        view = discord.ui.LayoutView(timeout=None)
        for item in items:
            view.add_item(item)
        return view


async def send_script(
    destination: discord.abc.Messageable,
    script: str,
    member: Optional[discord.Member] = None,
    guild: Optional[discord.Guild] = None,
) -> Optional[discord.Message]:
    view = Draft.from_script(replace_variables(script, member, guild)).render()
    if view is None:
        return None
    return await destination.send(view=view, allowed_mentions=discord.AllowedMentions(users=True))
