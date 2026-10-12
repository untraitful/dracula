"""Custom context with bleed-style approve / warn / deny replies and a paginator."""

from typing import List, Optional

import discord
from discord.ext import commands

from core import theme


class Paginator(discord.ui.View):
    def __init__(self, author_id: int, embeds: List[discord.Embed]):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.embeds = embeds
        self.index = 0
        self.message: Optional[discord.Message] = None
        for i, embed in enumerate(embeds):
            text = f"page {i + 1}/{len(embeds)}"
            if embed.footer and embed.footer.text:
                text = f"{embed.footer.text} • {text}"
            embed.set_footer(text=text)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                f"{theme.DENY_EMOJI} these pages are not yours to turn", ephemeral=True
            )
            return False
        return True

    async def _show(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _):
        self.index = (self.index - 1) % len(self.embeds)
        await self._show(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        self.index = (self.index + 1) % len(self.embeds)
        await self._show(interaction)

    @discord.ui.button(emoji="✖️", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await interaction.delete_original_response()
        self.stop()

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class Context(commands.Context):
    async def _reply(self, emoji: str, color: int, text: str, **kwargs) -> discord.Message:
        embed = discord.Embed(color=color, description=f"{emoji} {self.author.mention}: {text}")
        return await self.send(embed=embed, **kwargs)

    async def approve(self, text: str, **kwargs) -> discord.Message:
        return await self._reply(theme.APPROVE_EMOJI, theme.APPROVE, text, **kwargs)

    async def warn(self, text: str, **kwargs) -> discord.Message:
        return await self._reply(theme.WARN_EMOJI, theme.WARN, text, **kwargs)

    async def deny(self, text: str, **kwargs) -> discord.Message:
        return await self._reply(theme.DENY_EMOJI, theme.DENY, text, **kwargs)

    async def neutral(self, text: str, **kwargs) -> discord.Message:
        embed = discord.Embed(color=theme.NEUTRAL, description=text)
        return await self.send(embed=embed, **kwargs)

    async def paginate(
        self,
        lines: List[str],
        title: str,
        per_page: int = 10,
        numbered: bool = True,
    ) -> discord.Message:
        """Split `lines` into embeds and send them with page buttons."""
        if not lines:
            return await self.warn("nothing lurks here")
        if numbered:
            lines = [f"`{i + 1}` {line}" for i, line in enumerate(lines)]
        embeds = []
        for i in range(0, len(lines), per_page):
            embed = discord.Embed(color=theme.CRIMSON, title=title, description="\n".join(lines[i:i + per_page]))
            embed.set_author(name=self.author.display_name, icon_url=self.author.display_avatar.url)
            embeds.append(embed)
        if len(embeds) == 1:
            return await self.send(embed=embeds[0])
        view = Paginator(self.author.id, embeds)
        view.message = await self.send(embed=embeds[0], view=view)
        return view.message

    async def confirm(self, text: str) -> bool:
        """Ask the author to confirm a dangerous action."""
        view = Confirm(self.author.id)
        embed = discord.Embed(color=theme.WARN, description=f"{theme.WARN_EMOJI} {self.author.mention}: {text}")
        message = await self.send(embed=embed, view=view)
        await view.wait()
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        return bool(view.value)


class Confirm(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.value: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="seal it", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, _):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="spare it", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, _):
        self.value = False
        await interaction.response.defer()
        self.stop()
