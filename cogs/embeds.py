"""Interactive embed forge, saved embed templates and embed scripts — all components v2."""

import copy
import io
import time
from typing import List, Optional, Tuple

import discord
from discord.ext import commands

from core import theme, ui
from core.scripting import MAX_BUTTONS, MAX_FIELDS, VARIABLE_HELP, Draft, parse_hex, replace_variables, send_script

MAX_SAVED = 50
MAX_TEXT = 4000  # discord's limit on all text in one v2 message (preview + panel)
SET = "✠"
UNSET = "◦"


def _url_ok(value: str) -> bool:
    return not value or value.startswith(("http://", "https://", "{"))


# ----------------------------------------------------------- apply funcs
# each takes the draft plus the modal's values, mutates the draft and
# returns an error message (or None when the change is fine)

def apply_body(d: Draft, title: str, description: str, color: str, url: str):
    parsed = parse_hex(color) if color else theme.CRIMSON
    if parsed is None:
        return f"`{color}` is not a hex colour — try something like `#8a0303`"
    if not _url_ok(url):
        return "the title link must start with `http://` or `https://`"
    if url and not title:
        return "a title link needs a title"
    d.title, d.description, d.color, d.url = title, description, parsed, url


def apply_author(d: Draft, author: str):
    d.author = author


def apply_footer(d: Draft, footer: str):
    d.footer = footer


def apply_images(d: Draft, thumbnail: str, image: str):
    if not _url_ok(thumbnail) or not _url_ok(image):
        return "images must be links starting with `https://` (or a variable like `{user.avatar}`)"
    d.thumbnail, d.image = thumbnail, image


def apply_content(d: Draft, content: str):
    d.content = content


def apply_add_field(d: Draft, name: str, value: str):
    if len(d.fields) >= MAX_FIELDS:
        return f"a card can only hold **{MAX_FIELDS}** fields"
    d.fields.append((name, value))


def apply_add_button(d: Draft, label: str, url: str):
    if len(d.buttons) >= MAX_BUTTONS:
        return f"a card can only carry **{MAX_BUTTONS}** buttons"
    if not url.startswith(("http://", "https://")):
        return "button links must start with `http://` or `https://`"
    d.buttons.append((label, url))


def apply_remove(d: Draft, field_number: str, button_number: str):
    if not field_number and not button_number:
        return "tell me which field or button to remove"
    for raw, items, kind in ((field_number, d.fields, "field"), (button_number, d.buttons, "button")):
        if raw and (not raw.isdigit() or not 1 <= int(raw) <= len(items)):
            if not items:
                return f"there are no {kind}s to remove"
            return f"choose a {kind} number between **1** and **{len(items)}**"
    if field_number:
        d.fields.pop(int(field_number) - 1)
    if button_number:
        d.buttons.pop(int(button_number) - 1)


def apply_import(d: Draft, script: str):
    imported = Draft.from_script(script)
    for name in Draft.__dataclass_fields__:
        setattr(d, name, getattr(imported, name))


def text_input(label: str, default: str = "", *, long: bool = False, required: bool = False,
               max_length: int = 256, placeholder: Optional[str] = None) -> discord.ui.TextInput:
    return discord.ui.TextInput(
        label=label,
        default=default or None,
        style=discord.TextStyle.paragraph if long else discord.TextStyle.short,
        required=required,
        max_length=max_length,
        placeholder=placeholder,
    )


class DraftModal(discord.ui.Modal):
    """Applies its inputs to the forge's draft with `apply`, then re-renders the forge."""

    def __init__(self, forge: "Forge", title: str, inputs: List[discord.ui.TextInput], apply):
        super().__init__(title=title, timeout=600)
        self.forge = forge
        self.apply = apply
        for item in inputs:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        backup = copy.deepcopy(self.forge.draft)
        error = self.apply(self.forge.draft, *[item.value.strip() for item in self.children])
        if error:
            self.forge.draft = backup
            return await interaction.response.send_message(view=ui.deny(interaction.user, error), ephemeral=True)
        await self.forge.refresh(interaction, backup)


class SaveModal(discord.ui.Modal, title="entomb this card"):
    name = discord.ui.TextInput(label="name", placeholder="welcome", max_length=32)

    def __init__(self, forge: "Forge"):
        super().__init__(timeout=600)
        self.forge = forge

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip().lower()
        if not name:
            return await interaction.response.send_message(view=ui.deny(interaction.user, "the tomb needs a name"), ephemeral=True)
        ok, message = await save_embed(self.forge.ctx, name, self.forge.draft.to_script())
        card = ui.approve(interaction.user, message) if ok else ui.deny(interaction.user, message)
        await interaction.response.send_message(view=card, ephemeral=True)


# ----------------------------------------------------------------- forge

class Forge(discord.ui.LayoutView):
    """The builder message: a live preview of the card, then the control panel.

    The whole layout is rebuilt on every change. Worst case it uses 38 of
    discord's 40 components, so keep that in mind before adding controls.
    """

    def __init__(self, ctx: commands.Context, draft: Optional[Draft] = None):
        super().__init__(timeout=900)
        self.ctx = ctx
        self.draft = draft or Draft()
        self.destination: Optional[discord.abc.GuildChannel] = None
        self.message: Optional[discord.Message] = None
        self.build()

    # ---- layout

    def _button(self, label: str, emoji: str, callback, *, style=discord.ButtonStyle.secondary,
                disabled: bool = False) -> discord.ui.Button:
        button = discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled)
        button.callback = callback
        return button

    def preview_items(self) -> List[discord.ui.Item]:
        rendered = Draft.from_script(replace_variables(self.draft.to_script(), self.ctx.author, self.ctx.guild))
        items = rendered.render_items()
        if not rendered.has_card:
            items.append(discord.ui.Container(
                discord.ui.TextDisplay("*an empty tomb... nothing has been written yet.*\n-# shape your card with the forge below"),
                accent_colour=self.draft.color,
            ))
        return items

    def status_text(self) -> str:
        d = self.draft

        def mark(value, label: str) -> str:
            return f"{SET} {label}" if value else f"{UNSET} ~~{label}~~"

        fields = ", ".join(f"`{i + 1}` {name[:20]}" for i, (name, _) in enumerate(d.fields[:8]))
        if len(d.fields) > 8:
            fields += f" *+{len(d.fields) - 8}*"
        buttons = ", ".join(f"`{i + 1}` {label[:20]}" for i, (label, _) in enumerate(d.buttons))
        where = self.destination.mention if self.destination else "this channel"
        return "\n".join([
            "## 🕯️ the embed forge",
            ui.small("shape your card in the dark — the preview above changes as you work"),
            "",
            f"📜 **body** {mark(d.title, 'title')} · {mark(d.description, 'description')} · colour `#{d.color:06x}`",
            f"🧛 **author** {mark(d.author, 'author')} · 🕯️ **footer** {mark(d.footer, 'footer')} · {mark(d.timestamp, 'timestamp')}",
            f"🪞 **images** {mark(d.thumbnail, 'thumbnail')} · {mark(d.image, 'image')} · 💬 {mark(d.content, 'message text')}",
            f"🗝️ **fields** {len(d.fields)}/{MAX_FIELDS}" + (f" — {fields}" if fields else ""),
            f"🔗 **buttons** {len(d.buttons)}/{MAX_BUTTONS}" + (f" — {buttons}" if buttons else ""),
            f"🦇 **sending to** {where}",
        ])

    def build(self, active: bool = True):
        self.clear_items()
        for item in self.preview_items():
            self.add_item(item)

        panel = discord.ui.Container(accent_colour=theme.NEUTRAL)
        if not active:
            panel.add_item(discord.ui.TextDisplay(f"## 🕯️ the embed forge\n{ui.small('the forge has gone cold')}"))
            self.add_item(panel)
            return
        d = self.draft
        panel.add_item(discord.ui.TextDisplay(self.status_text()))
        panel.add_item(discord.ui.ActionRow(
            self._button("body", "📜", self.on_body),
            self._button("author", "🧛", self.on_author),
            self._button("footer", "🕯️", self.on_footer),
            self._button("images", "🪞", self.on_images),
            self._button("message", "💬", self.on_content),
        ))
        panel.add_item(discord.ui.ActionRow(
            self._button("field", "🗝️", self.on_add_field, disabled=len(d.fields) >= MAX_FIELDS),
            self._button("button", "🔗", self.on_add_button, disabled=len(d.buttons) >= MAX_BUTTONS),
            self._button("remove", "✂️", self.on_remove, disabled=not (d.fields or d.buttons)),
            self._button(f"timestamp {'on' if d.timestamp else 'off'}", "⏳", self.on_timestamp,
                         style=discord.ButtonStyle.primary if d.timestamp else discord.ButtonStyle.secondary),
            self._button("import", "📥", self.on_import),
        ))
        destination = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            placeholder="🦇 choose a channel to send it to...",
            default_values=[self.destination] if self.destination else [],
        )
        destination.callback = self.on_destination
        panel.add_item(discord.ui.ActionRow(destination))
        panel.add_item(discord.ui.ActionRow(
            self._button("send", "🩸", self.on_send, style=discord.ButtonStyle.danger, disabled=d.empty),
            self._button("save", "⚰️", self.on_save, style=discord.ButtonStyle.success, disabled=d.empty),
            self._button("script", "📤", self.on_export),
            self._button("reset", "🔥", self.on_reset),
            self._button("close", "✖️", self.on_close),
        ))
        self.add_item(panel)

    async def refresh(self, interaction: discord.Interaction, backup: Optional[Draft] = None):
        self.build()
        if backup is not None and self.content_length() > MAX_TEXT:
            excess = self.content_length() - MAX_TEXT
            self.draft = backup
            self.build()
            return await interaction.response.send_message(
                view=ui.deny(interaction.user, f"that card is too long by **{excess}** characters — "
                                               f"a card holds about {MAX_TEXT - 600} characters of text in total"),
                ephemeral=True,
            )
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException as e:
            if backup is None:
                raise
            self.draft = backup
            self.build()
            await interaction.response.send_message(
                view=ui.deny(interaction.user, f"discord rejected that change: `{e.text[:200]}`"), ephemeral=True
            )

    def _modal(self, title: str, inputs, apply) -> DraftModal:
        return DraftModal(self, title, inputs, apply)

    # ---- lifecycle

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                view=ui.deny(interaction.user, f"this forge is not yours — light your own with `{self.ctx.clean_prefix}embedbuilder`"),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        if self.message:
            self.build(active=False)
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # ---- editing

    async def on_body(self, interaction: discord.Interaction):
        d = self.draft
        await interaction.response.send_modal(self._modal("body", [
            text_input("title", d.title),
            text_input("description", d.description, long=True, max_length=3000),
            text_input("accent colour (hex)", f"#{d.color:06x}", max_length=7, placeholder="#8a0303"),
            text_input("title link", d.url, max_length=512, placeholder="https://..."),
        ], apply_body))

    async def on_author(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self._modal("author", [
            text_input("small text above the title", self.draft.author, placeholder="{user.name} has arrived"),
        ], apply_author))

    async def on_footer(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self._modal("footer", [
            text_input("small text at the bottom", self.draft.footer, long=True, max_length=500,
                       placeholder="{guild.name} • you are our {guild.count.format} soul"),
        ], apply_footer))

    async def on_images(self, interaction: discord.Interaction):
        d = self.draft
        await interaction.response.send_modal(self._modal("images", [
            text_input("thumbnail (beside the title)", d.thumbnail, max_length=512, placeholder="https://... or {user.avatar}"),
            text_input("image (full width)", d.image, max_length=512, placeholder="https://..."),
        ], apply_images))

    async def on_content(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self._modal("message text", [
            text_input("text above the card", self.draft.content, long=True, max_length=2000,
                       placeholder="{user.mention} welcome..."),
        ], apply_content))

    async def on_add_field(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self._modal("add a field", [
            text_input("name", required=True),
            text_input("value", long=True, required=True, max_length=1024),
        ], apply_add_field))

    async def on_add_button(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self._modal("add a link button", [
            text_input("label", required=True, max_length=80),
            text_input("url", required=True, max_length=512, placeholder="https://..."),
        ], apply_add_button))

    async def on_remove(self, interaction: discord.Interaction):
        d = self.draft
        await interaction.response.send_modal(self._modal("remove a field or button", [
            text_input(f"field number (1-{len(d.fields)})" if d.fields else "field number (none yet)", max_length=2),
            text_input(f"button number (1-{len(d.buttons)})" if d.buttons else "button number (none yet)", max_length=1),
        ], apply_remove))

    async def on_timestamp(self, interaction: discord.Interaction):
        backup = copy.deepcopy(self.draft)
        self.draft.timestamp = not self.draft.timestamp
        await self.refresh(interaction, backup)

    async def on_import(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self._modal("import an embed script", [
            text_input("script", long=True, required=True, max_length=4000, placeholder="{embed}$v{title: ...}"),
        ], apply_import))

    async def on_destination(self, interaction: discord.Interaction):
        self.destination = self.ctx.guild.get_channel(int(interaction.data["values"][0]))
        await self.refresh(interaction)

    # ---- finishing

    async def on_send(self, interaction: discord.Interaction):
        channel = self.destination or self.ctx.channel
        author_perms = channel.permissions_for(interaction.user)
        bot_perms = channel.permissions_for(self.ctx.guild.me)
        if not author_perms.send_messages:
            return await interaction.response.send_message(view=ui.deny(interaction.user, f"you cannot speak in {channel.mention}"), ephemeral=True)
        if not (bot_perms.send_messages and bot_perms.embed_links):
            return await interaction.response.send_message(view=ui.deny(interaction.user, f"i cannot send cards in {channel.mention}"), ephemeral=True)
        try:
            sent = await send_script(channel, self.draft.to_script(), self.ctx.author, self.ctx.guild)
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                view=ui.deny(interaction.user, f"discord rejected the card: `{e.text[:200]}`"), ephemeral=True
            )
        if sent is None:
            return await interaction.response.send_message(view=ui.deny(interaction.user, "you cannot send an empty tomb"), ephemeral=True)
        card = ui.approve(interaction.user, f"your card has risen in {channel.mention}")
        card.extend(discord.ui.ActionRow(ui.link("view it", sent.jump_url, "🦇")))
        await interaction.response.send_message(view=card, ephemeral=True)

    async def on_save(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SaveModal(self))

    async def on_export(self, interaction: discord.Interaction):
        script = self.draft.to_script()
        if len(script) > 3500:
            file = discord.File(io.BytesIO(script.encode()), filename="embed.txt")
            return await interaction.response.send_message(
                view=ui.Card("📤 your embed script is attached", accent=theme.NEUTRAL), file=file, ephemeral=True
            )
        await interaction.response.send_message(view=ui.Card(
            ui.heading("📤 your embed script", level=3),
            f"```\n{script}\n```",
            ui.small(f"use it with {self.ctx.clean_prefix}embed, greetings or autoresponders"),
            accent=theme.NEUTRAL,
        ), ephemeral=True)

    async def on_reset(self, interaction: discord.Interaction):
        self.draft = Draft()
        await self.refresh(interaction)

    async def on_close(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(view=ui.Card("🕯️ the forge has gone cold.", accent=theme.NEUTRAL))


async def save_embed(ctx: commands.Context, name: str, script: str) -> Tuple[bool, str]:
    db = ctx.bot.db
    exists = await db.fetchval("SELECT 1 FROM embeds WHERE guild_id = ? AND name = ?", ctx.guild.id, name)
    if not exists:
        count = await db.fetchval("SELECT COUNT(*) FROM embeds WHERE guild_id = ?", ctx.guild.id)
        if count >= MAX_SAVED:
            return False, f"this crypt already holds **{MAX_SAVED}** cards — delete one first"
    await db.execute(
        "INSERT OR REPLACE INTO embeds (guild_id, name, script, author_id, created) VALUES (?, ?, ?, ?, ?)",
        ctx.guild.id, name, script, ctx.author.id, int(time.time()),
    )
    verb = "re-entombed" if exists else "entombed"
    return True, f"{verb} as **{name}** — send it with `{ctx.clean_prefix}embed send {name}`"


# ------------------------------------------------------------------- cog

class Embeds(commands.Cog):
    """forge, entomb and summon embeds"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    async def _saved(self, ctx, name: str) -> Optional[str]:
        script = await self.bot.db.fetchval("SELECT script FROM embeds WHERE guild_id = ? AND name = ?", ctx.guild.id, name.lower())
        if script is None:
            await ctx.warn(f"no card named **{name}** rests here — see `{ctx.clean_prefix}embed list`")
        return script

    @commands.command(aliases=["eb", "builder", "forge"])
    @commands.has_permissions(manage_messages=True)
    async def embedbuilder(self, ctx, name: Optional[str] = None):
        """open the interactive embed forge (optionally from a saved card)"""
        draft = None
        if name:
            script = await self._saved(ctx, name)
            if script is None:
                return
            draft = Draft.from_script(script)
        view = Forge(ctx, draft)
        view.message = await ctx.send(view=view)

    @commands.group(aliases=["ce", "createembed"], invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def embed(self, ctx, *, script: str):
        """send a card from a script — see `$variables`, or use `$embedbuilder`"""
        sent = await send_script(ctx.channel, script, ctx.author)
        if sent is None:
            await ctx.warn("that script summoned nothing")

    @embed.command(name="save")
    @commands.has_permissions(manage_messages=True)
    async def embed_save(self, ctx, name: str, *, script: str):
        """entomb a script under a name"""
        ok, message = await save_embed(ctx, name.lower()[:32], script)
        await (ctx.approve(message) if ok else ctx.warn(message))

    @embed.command(name="send", aliases=["summon"])
    @commands.has_permissions(manage_messages=True)
    async def embed_send(self, ctx, name: str, channel: Optional[discord.TextChannel] = None):
        """send a saved card"""
        script = await self._saved(ctx, name)
        if script is None:
            return
        channel = channel or ctx.channel
        if not channel.permissions_for(ctx.author).send_messages:
            return await ctx.warn(f"you cannot speak in {channel.mention}")
        await send_script(channel, script, ctx.author)
        if channel != ctx.channel:
            await ctx.approve(f"**{name}** has risen in {channel.mention}")

    @embed.command(name="edit")
    @commands.has_permissions(manage_messages=True)
    async def embed_edit(self, ctx, name: str):
        """open a saved card in the forge"""
        await ctx.invoke(self.embedbuilder, name=name)

    @embed.command(name="view", aliases=["script"])
    @commands.has_permissions(manage_messages=True)
    async def embed_view(self, ctx, name: str):
        """see a saved card's script"""
        script = await self._saved(ctx, name)
        if script is None:
            return
        if len(script) > 3500:
            return await ctx.send(file=discord.File(io.BytesIO(script.encode()), filename=f"{name}.txt"))
        await ctx.send_card(ui.Card(ui.heading(f"📜 {name.lower()}", level=3), f"```\n{script}\n```", accent=theme.NEUTRAL))

    @embed.command(name="delete", aliases=["remove", "del"])
    @commands.has_permissions(manage_messages=True)
    async def embed_delete(self, ctx, name: str):
        """destroy a saved card"""
        removed = await self.bot.db.execute("DELETE FROM embeds WHERE guild_id = ? AND name = ?", ctx.guild.id, name.lower())
        if not removed:
            return await ctx.warn(f"no card named **{name}** rests here")
        await ctx.approve(f"**{name.lower()}** has been laid to rest for good")

    @embed.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def embed_list(self, ctx):
        """list saved cards"""
        rows = await self.bot.db.fetchall(
            "SELECT name, author_id, created FROM embeds WHERE guild_id = ? ORDER BY name", ctx.guild.id
        )
        await ctx.paginate(
            [f"**{r['name']}** — by <@{r['author_id']}> <t:{r['created']}:R>" for r in rows],
            "⚰️ entombed cards",
        )

    @commands.command(aliases=["vars"])
    async def variables(self, ctx):
        """list variables and embed script syntax"""
        await ctx.send_card(ui.Card(
            ui.heading("📜 variables & embed scripts", "variables are filled in when the card is sent"),
            ui.sep(),
            "\n".join(f"`{k}` — {v}" for k, v in VARIABLE_HELP.items()),
            ui.sep(),
            "**embed scripts** start with `{embed}` and separate parts with `$v`:\n"
            "```{embed}$v{title: welcome {user.name}}$v{description: the night welcomes you}"
            "$v{color: #8a0303}$v{thumbnail: {user.avatar}}$v{content: {user.mention}}```"
            "parts: `content` `author` `title` `url` `description` `color` `thumbnail` "
            "`field: name && value` `image` `footer` `timestamp` `button: label && url`",
            ui.small(f"rather click than type? {ctx.clean_prefix}embedbuilder writes the script for you"),
        ))


async def setup(bot):
    await bot.add_cog(Embeds(bot))
