"""Custom context with bleed-style approve / warn / deny replies, a paginator and confirmations."""

from typing import List, Optional

import discord
from discord.ext import commands

from core import theme, ui


class Paginator(discord.ui.LayoutView):
    def __init__(self, author: discord.abc.User, title: str, pages: List[str], accent: int = theme.CRIMSON):
        super().__init__(timeout=120)
        self.author = author
        self.title = title
        self.pages = pages
        self.accent = accent
        self.index = 0
        self.message: Optional[discord.Message] = None
        self.build()

    def build(self, active: bool = True):
        self.clear_items()
        container = discord.ui.Container(accent_colour=self.accent)
        container.add_item(discord.ui.TextDisplay(ui.heading(self.title, level=3)))
        container.add_item(ui.sep())
        container.add_item(discord.ui.TextDisplay(self.pages[self.index]))
        container.add_item(ui.sep())
        container.add_item(discord.ui.TextDisplay(ui.small(f"page {self.index + 1}/{len(self.pages)} • {theme.FOOTER}")))
        if active and len(self.pages) > 1:
            container.add_item(discord.ui.ActionRow(
                self._button("⬅️", self._previous),
                self._button("➡️", self._next),
                self._button("✖️", self._close, discord.ButtonStyle.danger),
            ))
        self.add_item(container)

    @staticmethod
    def _button(emoji: str, callback, style=discord.ButtonStyle.secondary) -> discord.ui.Button:
        button = discord.ui.Button(emoji=emoji, style=style)
        button.callback = callback
        return button

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(view=ui.deny(interaction.user, "these pages are not yours to turn"), ephemeral=True)
            return False
        return True

    async def _turn(self, interaction: discord.Interaction, step: int):
        self.index = (self.index + step) % len(self.pages)
        self.build()
        await interaction.response.edit_message(view=self)

    async def _previous(self, interaction: discord.Interaction):
        await self._turn(interaction, -1)

    async def _next(self, interaction: discord.Interaction):
        await self._turn(interaction, 1)

    async def _close(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.defer()
        await interaction.delete_original_response()

    async def on_timeout(self):
        if self.message:
            self.build(active=False)
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Confirm(discord.ui.LayoutView):
    def __init__(self, author: discord.abc.User, text: str):
        super().__init__(timeout=30)
        self.author = author
        self.value: Optional[bool] = None
        yes = discord.ui.Button(label="seal it", emoji="🩸", style=discord.ButtonStyle.danger)
        no = discord.ui.Button(label="spare it", style=discord.ButtonStyle.secondary)
        yes.callback = self._yes
        no.callback = self._no
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"{theme.WARN_EMOJI} {author.mention}: {text}"),
            discord.ui.ActionRow(yes, no),
            accent_colour=theme.WARN,
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    async def _yes(self, interaction: discord.Interaction):
        self.value = True
        await interaction.response.defer()
        self.stop()

    async def _no(self, interaction: discord.Interaction):
        self.value = False
        await interaction.response.defer()
        self.stop()


class Context(commands.Context):
    async def send_card(self, card: discord.ui.LayoutView, **kwargs) -> discord.Message:
        return await self.send(view=card, **kwargs)

    async def approve(self, text: str, **kwargs) -> discord.Message:
        return await self.send(view=ui.approve(self.author, text), **kwargs)

    async def warn(self, text: str, **kwargs) -> discord.Message:
        return await self.send(view=ui.warn(self.author, text), **kwargs)

    async def deny(self, text: str, **kwargs) -> discord.Message:
        return await self.send(view=ui.deny(self.author, text), **kwargs)

    async def neutral(self, text: str, **kwargs) -> discord.Message:
        return await self.send(view=ui.Card(text, accent=theme.NEUTRAL), **kwargs)

    async def paginate(self, lines: List[str], title: str, per_page: int = 10, numbered: bool = True) -> discord.Message:
        """Split `lines` into pages and send them with page buttons."""
        if not lines:
            return await self.warn("nothing lurks here")
        if numbered:
            lines = [f"`{i + 1}` {line}" for i, line in enumerate(lines)]
        pages = ["\n".join(lines[i:i + per_page]) for i in range(0, len(lines), per_page)]
        view = Paginator(self.author, title, pages)
        view.message = await self.send(view=view)
        return view.message

    async def confirm(self, text: str) -> bool:
        """Ask the author to confirm a dangerous action."""
        view = Confirm(self.author, text)
        message = await self.send(view=view)
        await view.wait()
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        return bool(view.value)
