"""Components v2 building blocks in dracula's style.

Every reply is a `Card`: a LayoutView holding one accented container. Children can be
plain strings (turned into text displays) or any v2 item.
"""

import os
from pathlib import Path
from typing import Iterable, Optional, Tuple, Union

import discord

from core import theme

ChildLike = Union[str, discord.ui.Item, None]


def _item(child: Union[str, discord.ui.Item]) -> discord.ui.Item:
    return discord.ui.TextDisplay(child) if isinstance(child, str) else child


def small(text: str) -> str:
    """Discord's subtext (`-#`) applied to every line."""
    return "\n".join(f"-# {line}" if line else "" for line in text.splitlines())


def heading(title: str, subtitle: Optional[str] = None, level: int = 2) -> str:
    text = f"{'#' * level} {title}"
    return f"{text}\n{small(subtitle)}" if subtitle else text


def sep(*, large: bool = False, visible: bool = True) -> discord.ui.Separator:
    spacing = discord.SeparatorSpacing.large if large else discord.SeparatorSpacing.small
    return discord.ui.Separator(spacing=spacing, visible=visible)


def section(text: str, *, thumbnail: Optional[str] = None, button: Optional[discord.ui.Button] = None) -> discord.ui.Item:
    """Text with a thumbnail or button beside it; plain text if neither is given."""
    if thumbnail:
        return discord.ui.Section(discord.ui.TextDisplay(text), accessory=discord.ui.Thumbnail(thumbnail))
    if button:
        return discord.ui.Section(discord.ui.TextDisplay(text), accessory=button)
    return discord.ui.TextDisplay(text)


def gallery(*urls: str) -> Optional[discord.ui.MediaGallery]:
    urls = [u for u in urls if u]
    if not urls:
        return None
    return discord.ui.MediaGallery(*(discord.MediaGalleryItem(u) for u in urls[:10]))


def link(label: str, url: str, emoji: Optional[str] = None) -> discord.ui.Button:
    return discord.ui.Button(label=label, url=url, emoji=emoji)


def link_row(*links: Tuple[str, str]) -> discord.ui.ActionRow:
    return discord.ui.ActionRow(*(link(label, url) for label, url in links))


BANNER_FILE = Path(__file__).resolve().parent.parent / "assets" / "banner.jpg"


def banner() -> Optional[discord.ui.MediaGallery]:
    """The gothic banner, from DRACULA_BANNER_URL or the bundled assets/banner.jpg.

    The bundled file has to be uploaded with the message: pass `banner_file()` as `file=`.
    """
    url = os.getenv("DRACULA_BANNER_URL")
    if url:
        return gallery(url)
    if BANNER_FILE.exists():
        return gallery(f"attachment://{BANNER_FILE.name}")
    return None


def banner_file() -> Optional[discord.File]:
    if os.getenv("DRACULA_BANNER_URL") or not BANNER_FILE.exists():
        return None
    return discord.File(BANNER_FILE, filename=BANNER_FILE.name)


def footer() -> str:
    return small(theme.FOOTER)


class Card(discord.ui.LayoutView):
    """A single accented container, optionally with text above it."""

    def __init__(self, *children: ChildLike, accent: int = theme.CRIMSON, above: Optional[str] = None,
                 timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        if above:
            self.add_item(discord.ui.TextDisplay(above))
        self.container = discord.ui.Container(accent_colour=accent)
        self.add_item(self.container)
        self.extend(*children)

    def extend(self, *children: ChildLike) -> "Card":
        for child in children:
            if child is not None:
                self.container.add_item(_item(child))
        return self


def status(emoji: str, accent: int, user: discord.abc.User, text: str) -> Card:
    """bleed-style one line reply: `🦇 @user: text`."""
    return Card(f"{emoji} {user.mention}: {text}", accent=accent)


def approve(user: discord.abc.User, text: str) -> Card:
    return status(theme.APPROVE_EMOJI, theme.APPROVE, user, text)


def warn(user: discord.abc.User, text: str) -> Card:
    return status(theme.WARN_EMOJI, theme.WARN, user, text)


def deny(user: discord.abc.User, text: str) -> Card:
    return status(theme.DENY_EMOJI, theme.DENY, user, text)


def media_card(title: str, url: str, *, subtitle: Optional[str] = None) -> Card:
    """A heading over a big image, with a button to open the original."""
    return Card(
        heading(title, subtitle, level=3),
        gallery(url),
        discord.ui.ActionRow(link("open original", url, "🔗")),
    )


def lines(rows: Iterable[str]) -> str:
    return "\n".join(r for r in rows if r)
