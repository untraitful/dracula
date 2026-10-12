"""Interactive embed builder, saved embed templates and embed scripts."""

import copy
import io
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import discord
from discord.ext import commands

from core import theme
from core.scripting import VARIABLE_HELP, is_script, iter_parts, parse_script, replace_variables, send_script

MAX_FIELDS = 25
MAX_BUTTONS = 5
MAX_SAVED = 50
SET = "✠"
UNSET = "◦"


def _url_ok(value: str) -> bool:
    return not value or value.startswith(("http://", "https://", "{"))


def _parse_hex(value: str) -> Optional[int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


@dataclass
class Draft:
    """Everything the builder is editing. Serialises to / from an embed script."""

    content: str = ""
    title: str = ""
    description: str = ""
    url: str = ""
    color: int = theme.CRIMSON
    author_name: str = ""
    author_icon: str = ""
    footer_text: str = ""
    footer_icon: str = ""
    thumbnail: str = ""
    image: str = ""
    timestamp: bool = False
    fields: List[Tuple[str, str, bool]] = field(default_factory=list)
    buttons: List[Tuple[str, str]] = field(default_factory=list)

    def to_script(self) -> str:
        parts = ["{embed}"]

        def add(key: str, *values: str):
            parts.append(f"{{{key}: {' && '.join(values)}}}")

        if self.content:
            add("content", self.content)
        if self.title:
            add("title", self.title)
        if self.url:
            add("url", self.url)
        if self.description:
            add("description", self.description)
        add("color", f"#{self.color:06x}")
        if self.author_name:
            add("author", self.author_name, *([self.author_icon] if self.author_icon else []))
        for name, value, inline in self.fields:
            add("field", name, value, *(["inline"] if inline else []))
        if self.thumbnail:
            add("thumbnail", self.thumbnail)
        if self.image:
            add("image", self.image)
        if self.footer_text:
            add("footer", self.footer_text, *([self.footer_icon] if self.footer_icon else []))
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
            second = args[1] if len(args) > 1 else ""
            if key == "content":
                draft.content = value
            elif key == "title":
                draft.title = value[:256]
            elif key == "description":
                draft.description = value[:4000]
            elif key in ("color", "colour"):
                draft.color = _parse_hex(value) or theme.CRIMSON
            elif key == "url":
                draft.url = value
            elif key == "author":
                draft.author_name, draft.author_icon = args[0][:256], second
            elif key == "footer":
                draft.footer_text, draft.footer_icon = args[0][:2048], second
            elif key == "thumbnail":
                draft.thumbnail = value
            elif key == "image":
                draft.image = value
            elif key == "timestamp":
                draft.timestamp = True
            elif key == "field" and len(args) >= 2 and len(draft.fields) < MAX_FIELDS:
                inline = len(args) > 2 and args[2].lower() in ("true", "yes", "inline")
                draft.fields.append((args[0][:256], args[1][:1024], inline))
            elif key == "button" and len(args) >= 2 and len(draft.buttons) < MAX_BUTTONS:
                draft.buttons.append((args[0][:80], second))
        return draft

    @property
    def empty(self) -> bool:
        return self == Draft(color=self.color)


# ---------------------------------------------------------------- modals

class DraftModal(discord.ui.Modal):
    """A modal whose inputs are applied to the draft by `apply`.

    `apply(draft, *values)` mutates the draft and returns an error string, or None on success.
    """

    def __init__(self, builder: "EmbedBuilder", title: str, inputs: List[discord.ui.TextInput], apply):
        super().__init__(title=title, timeout=600)
        self.builder = builder
        self.apply = apply
        for item in inputs:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        backup = copy.deepcopy(self.builder.draft)
        error = self.apply(self.builder.draft, *[item.value.strip() for item in self.children])
        if error:
            self.builder.draft = backup
            return await interaction.response.send_message(embed=deny(interaction.user, error), ephemeral=True)
        await self.builder.refresh(interaction, backup)


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


def deny(user: discord.abc.User, text: str) -> discord.Embed:
    return discord.Embed(color=theme.DENY, description=f"{theme.DENY_EMOJI} {user.mention}: {text}")


def approve(user: discord.abc.User, text: str) -> discord.Embed:
    return discord.Embed(color=theme.APPROVE, description=f"{theme.APPROVE_EMOJI} {user.mention}: {text}")


# ----------------------------------------------------------- apply funcs

def apply_body(d: Draft, title: str, description: str, color: str, url: str):
    parsed = _parse_hex(color) if color else theme.CRIMSON
    if parsed is None:
        return f"`{color}` is not a hex colour — try something like `#8a0303`"
    if not _url_ok(url):
        return "the title link must start with `http://` or `https://`"
    d.title, d.description, d.color, d.url = title, description, parsed, url


def apply_author(d: Draft, name: str, icon: str):
    if icon and not name:
        return "an author icon needs an author name"
    if not _url_ok(icon):
        return "the icon must be a link starting with `https://` (or a variable like `{user.avatar}`)"
    d.author_name, d.author_icon = name, icon


def apply_footer(d: Draft, text: str, icon: str):
    if icon and not text:
        return "a footer icon needs footer text"
    if not _url_ok(icon):
        return "the icon must be a link starting with `https://` (or a variable like `{user.avatar}`)"
    d.footer_text, d.footer_icon = text, icon


def apply_images(d: Draft, thumbnail: str, image: str):
    if not _url_ok(thumbnail) or not _url_ok(image):
        return "images must be links starting with `https://` (or a variable like `{user.avatar}`)"
    d.thumbnail, d.image = thumbnail, image


def apply_content(d: Draft, content: str):
    d.content = content


def apply_add_field(d: Draft, name: str, value: str, inline: str):
    if len(d.fields) >= MAX_FIELDS:
        return f"an embed can only hold **{MAX_FIELDS}** fields"
    d.fields.append((name, value, inline.lower() in ("yes", "y", "true", "inline", "1")))


def apply_remove_field(d: Draft, number: str):
    if not number.isdigit() or not 1 <= int(number) <= len(d.fields):
        return f"choose a field number between **1** and **{len(d.fields)}**"
    d.fields.pop(int(number) - 1)


def apply_add_button(d: Draft, label: str, url: str):
    if len(d.buttons) >= MAX_BUTTONS:
        return f"an embed can only carry **{MAX_BUTTONS}** buttons"
    if not url.startswith(("http://", "https://")):
        return "button links must start with `http://` or `https://`"
    d.buttons.append((label, url))


def apply_import(d: Draft, script: str):
    imported = Draft.from_script(script)
    for name in Draft.__dataclass_fields__:
        setattr(d, name, getattr(imported, name))


# ------------------------------------------------------------------ view

class EmbedBuilder(discord.ui.View):
    def __init__(self, ctx: commands.Context, draft: Optional[Draft] = None):
        super().__init__(timeout=900)
        self.ctx = ctx
        self.draft = draft or Draft()
        self.destination: Optional[discord.TextChannel] = None
        self.message: Optional[discord.Message] = None
        self._sync_labels()

    # ---- rendering

    def _sync_labels(self):
        self.timestamp_button.label = f"timestamp: {'on' if self.draft.timestamp else 'off'}"
        self.remove_field_button.disabled = not self.draft.fields
        self.clear_buttons_button.disabled = not self.draft.buttons
        self.add_field_button.disabled = len(self.draft.fields) >= MAX_FIELDS
        self.add_button_button.disabled = len(self.draft.buttons) >= MAX_BUTTONS

    def panel(self) -> discord.Embed:
        d = self.draft

        def mark(value, label: str) -> str:
            return f"{SET} {label}" if value else f"{UNSET} ~~{label}~~"

        embed = discord.Embed(
            color=theme.NEUTRAL,
            title="🕯️ the embed forge",
            description=(
                "*shape your embed in the dark — the preview below changes as you work.*\n"
                f"sending to: {self.destination.mention if self.destination else '**this channel** (pick another below)'}"
            ),
        )
        embed.set_author(name=f"{self.ctx.author.display_name}'s forge", icon_url=self.ctx.author.display_avatar.url)
        embed.add_field(name="📜 body", value="\n".join([
            mark(d.title, "title"), mark(d.description, "description"), f"{SET} colour `#{d.color:06x}`",
        ]))
        embed.add_field(name="🧛 author", value="\n".join([mark(d.author_name, "name"), mark(d.author_icon, "icon")]))
        embed.add_field(name="🕯️ footer", value="\n".join([
            mark(d.footer_text, "text"), mark(d.footer_icon, "icon"), mark(d.timestamp, "timestamp"),
        ]))
        embed.add_field(name="🪞 images", value="\n".join([mark(d.thumbnail, "thumbnail"), mark(d.image, "image")]))
        field_lines = [f"`{i + 1}` {name[:24]}" for i, (name, _, _) in enumerate(d.fields[:6])]
        if len(d.fields) > 6:
            field_lines.append(f"*+{len(d.fields) - 6} more*")
        embed.add_field(name=f"🗝️ fields ({len(d.fields)}/{MAX_FIELDS})", value="\n".join(field_lines) or f"{UNSET} none")
        embed.add_field(
            name=f"🔗 buttons ({len(d.buttons)}/{MAX_BUTTONS})",
            value="\n".join(f"[{label[:24]}]({url})" for label, url in d.buttons) or f"{UNSET} none",
        )
        if d.content:
            preview = replace_variables(d.content, self.ctx.author, self.ctx.guild)
            embed.add_field(name="💬 message", value=f">>> {preview[:1000]}", inline=False)
        embed.set_footer(text=f"variables like {{user.mention}} work • {self.ctx.clean_prefix}variables • {theme.FOOTER}")
        return embed

    def preview(self) -> discord.Embed:
        _, embed, _ = parse_script(replace_variables(self.draft.to_script(), self.ctx.author, self.ctx.guild))
        if embed is None:
            embed = discord.Embed(
                color=self.draft.color,
                description="*an empty tomb... nothing has been written yet.*\nuse the buttons below to begin.",
            )
        return embed

    def render(self) -> List[discord.Embed]:
        self._sync_labels()
        return [self.panel(), self.preview()]

    async def refresh(self, interaction: discord.Interaction, backup: Optional[Draft] = None):
        try:
            await interaction.response.edit_message(embeds=self.render(), view=self)
        except discord.HTTPException as e:
            if backup is None:
                raise
            self.draft = backup
            self._sync_labels()
            await interaction.response.send_message(
                embed=deny(interaction.user, f"discord rejected that change: `{e.text[:200]}`"), ephemeral=True
            )

    # ---- lifecycle

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                embed=deny(interaction.user, f"this forge is not yours — light your own with `{self.ctx.clean_prefix}embedbuilder`"),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def _modal(self, title: str, inputs, apply) -> DraftModal:
        return DraftModal(self, title, inputs, apply)

    # ---- row 0: the embed itself

    @discord.ui.button(label="body", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def body_button(self, interaction: discord.Interaction, _):
        d = self.draft
        await interaction.response.send_modal(self._modal("body", [
            text_input("title", d.title),
            text_input("description", d.description, long=True, max_length=4000),
            text_input("colour (hex)", f"#{d.color:06x}", max_length=7, placeholder="#8a0303"),
            text_input("title link", d.url, max_length=512, placeholder="https://..."),
        ], apply_body))

    @discord.ui.button(label="author", emoji="🧛", style=discord.ButtonStyle.secondary, row=0)
    async def author_button(self, interaction: discord.Interaction, _):
        d = self.draft
        await interaction.response.send_modal(self._modal("author", [
            text_input("name", d.author_name),
            text_input("icon url", d.author_icon, max_length=512, placeholder="https://... or {user.avatar}"),
        ], apply_author))

    @discord.ui.button(label="footer", emoji="🕯️", style=discord.ButtonStyle.secondary, row=0)
    async def footer_button(self, interaction: discord.Interaction, _):
        d = self.draft
        await interaction.response.send_modal(self._modal("footer", [
            text_input("text", d.footer_text, long=True, max_length=2048),
            text_input("icon url", d.footer_icon, max_length=512, placeholder="https://... or {guild.icon}"),
        ], apply_footer))

    @discord.ui.button(label="images", emoji="🪞", style=discord.ButtonStyle.secondary, row=0)
    async def images_button(self, interaction: discord.Interaction, _):
        d = self.draft
        await interaction.response.send_modal(self._modal("images", [
            text_input("thumbnail url", d.thumbnail, max_length=512, placeholder="https://... or {user.avatar}"),
            text_input("image url", d.image, max_length=512, placeholder="https://..."),
        ], apply_images))

    @discord.ui.button(label="message", emoji="💬", style=discord.ButtonStyle.secondary, row=0)
    async def content_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(self._modal("message text", [
            text_input("text sent above the embed", self.draft.content, long=True, max_length=2000,
                       placeholder="{user.mention} welcome..."),
        ], apply_content))

    # ---- row 1: fields, buttons, timestamp

    @discord.ui.button(label="field", emoji="🗝️", style=discord.ButtonStyle.secondary, row=1)
    async def add_field_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(self._modal("add a field", [
            text_input("name", required=True),
            text_input("value", long=True, required=True, max_length=1024),
            text_input("inline? (yes / no)", "no", max_length=5),
        ], apply_add_field))

    @discord.ui.button(label="remove field", emoji="✂️", style=discord.ButtonStyle.secondary, row=1)
    async def remove_field_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(self._modal("remove a field", [
            text_input("field number", str(len(self.draft.fields)), required=True, max_length=2),
        ], apply_remove_field))

    @discord.ui.button(label="link button", emoji="🔗", style=discord.ButtonStyle.secondary, row=1)
    async def add_button_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(self._modal("add a link button", [
            text_input("label", required=True, max_length=80),
            text_input("url", required=True, max_length=512, placeholder="https://..."),
        ], apply_add_button))

    @discord.ui.button(label="clear buttons", emoji="🧹", style=discord.ButtonStyle.secondary, row=1)
    async def clear_buttons_button(self, interaction: discord.Interaction, _):
        self.draft.buttons.clear()
        await self.refresh(interaction)

    @discord.ui.button(label="timestamp: off", emoji="⏳", style=discord.ButtonStyle.secondary, row=1)
    async def timestamp_button(self, interaction: discord.Interaction, _):
        self.draft.timestamp = not self.draft.timestamp
        await self.refresh(interaction)

    # ---- row 2: destination

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        placeholder="🦇 choose a channel to send it to...",
        row=2,
    )
    async def destination_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.destination = self.ctx.guild.get_channel(select.values[0].id)
        await self.refresh(interaction)

    # ---- row 3: finish

    @discord.ui.button(label="send", emoji="🩸", style=discord.ButtonStyle.danger, row=3)
    async def send_button(self, interaction: discord.Interaction, _):
        if self.draft.empty:
            return await interaction.response.send_message(embed=deny(interaction.user, "you cannot send an empty tomb"), ephemeral=True)
        channel = self.destination or self.ctx.channel
        author_perms = channel.permissions_for(interaction.user)
        bot_perms = channel.permissions_for(self.ctx.guild.me)
        if not (author_perms.send_messages and author_perms.embed_links):
            return await interaction.response.send_message(
                embed=deny(interaction.user, f"you cannot send embeds in {channel.mention}"), ephemeral=True
            )
        if not (bot_perms.send_messages and bot_perms.embed_links):
            return await interaction.response.send_message(
                embed=deny(interaction.user, f"i cannot send embeds in {channel.mention}"), ephemeral=True
            )
        try:
            sent = await send_script(channel, self.draft.to_script(), self.ctx.author, self.ctx.guild)
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                embed=deny(interaction.user, f"discord rejected the embed: `{e.text[:200]}`"), ephemeral=True
            )
        if sent is None:
            return await interaction.response.send_message(
                embed=deny(interaction.user, "a button cannot be sent alone — add some text or an embed"), ephemeral=True
            )
        await interaction.response.send_message(
            embed=approve(interaction.user, f"your embed has risen in {channel.mention} — [view it]({sent.jump_url})"),
            ephemeral=True,
        )

    @discord.ui.button(label="save", emoji="⚰️", style=discord.ButtonStyle.success, row=3)
    async def save_button(self, interaction: discord.Interaction, _):
        if self.draft.empty:
            return await interaction.response.send_message(embed=deny(interaction.user, "there is nothing to entomb yet"), ephemeral=True)
        await interaction.response.send_modal(SaveModal(self))

    @discord.ui.button(label="import", emoji="📥", style=discord.ButtonStyle.secondary, row=3)
    async def import_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(self._modal("import an embed script", [
            text_input("script", long=True, required=True, max_length=4000, placeholder="{embed}$v{title: ...}"),
        ], apply_import))

    @discord.ui.button(label="script", emoji="📤", style=discord.ButtonStyle.secondary, row=3)
    async def export_button(self, interaction: discord.Interaction, _):
        script = self.draft.to_script()
        if len(script) > 1900:
            file = discord.File(io.BytesIO(script.encode()), filename="embed.txt")
            return await interaction.response.send_message("📤 your script:", file=file, ephemeral=True)
        await interaction.response.send_message(
            embed=discord.Embed(
                color=theme.NEUTRAL,
                title="📤 your embed script",
                description=f"```\n{script}\n```\nuse it with `{self.ctx.clean_prefix}embed`, greetings or autoresponders",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="reset", emoji="🔥", style=discord.ButtonStyle.secondary, row=3)
    async def reset_button(self, interaction: discord.Interaction, _):
        self.draft = Draft()
        await self.refresh(interaction)

    @discord.ui.button(label="close the forge", emoji="✖️", style=discord.ButtonStyle.secondary, row=4)
    async def close_button(self, interaction: discord.Interaction, _):
        self.stop()
        await interaction.response.edit_message(
            embeds=[discord.Embed(color=theme.NEUTRAL, description="🕯️ the forge has gone cold.")], view=None
        )


class SaveModal(discord.ui.Modal, title="entomb this embed"):
    name = discord.ui.TextInput(label="name", placeholder="welcome", max_length=32)

    def __init__(self, builder: EmbedBuilder):
        super().__init__(timeout=600)
        self.builder = builder

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip().lower()
        if not name:
            return await interaction.response.send_message(embed=deny(interaction.user, "the tomb needs a name"), ephemeral=True)
        ok, message = await save_embed(self.builder.ctx, name, self.builder.draft.to_script())
        embed = approve(interaction.user, message) if ok else deny(interaction.user, message)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def save_embed(ctx: commands.Context, name: str, script: str) -> Tuple[bool, str]:
    db = ctx.bot.db
    exists = await db.fetchval("SELECT 1 FROM embeds WHERE guild_id = ? AND name = ?", ctx.guild.id, name)
    if not exists:
        count = await db.fetchval("SELECT COUNT(*) FROM embeds WHERE guild_id = ?", ctx.guild.id)
        if count >= MAX_SAVED:
            return False, f"this crypt already holds **{MAX_SAVED}** embeds — delete one first"
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
            await ctx.warn(f"no embed named **{name}** rests here — see `{ctx.clean_prefix}embed list`")
        return script

    @commands.command(aliases=["eb", "builder", "forge"])
    @commands.has_permissions(manage_messages=True)
    async def embedbuilder(self, ctx, name: Optional[str] = None):
        """open the interactive embed forge (optionally from a saved embed)"""
        draft = None
        if name:
            script = await self._saved(ctx, name)
            if script is None:
                return
            draft = Draft.from_script(script)
        view = EmbedBuilder(ctx, draft)
        view.message = await ctx.send(embeds=view.render(), view=view)

    @commands.group(aliases=["ce", "createembed"], invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def embed(self, ctx, *, script: str):
        """send an embed from a script — see `$variables`, or use `$embedbuilder`"""
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
        """send a saved embed"""
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
        """open a saved embed in the forge"""
        await ctx.invoke(self.embedbuilder, name=name)

    @embed.command(name="view", aliases=["script"])
    @commands.has_permissions(manage_messages=True)
    async def embed_view(self, ctx, name: str):
        """see a saved embed's script"""
        script = await self._saved(ctx, name)
        if script is None:
            return
        if len(script) > 3900:
            return await ctx.send(file=discord.File(io.BytesIO(script.encode()), filename=f"{name}.txt"))
        await ctx.neutral(f"📜 **{name.lower()}**\n```\n{script}\n```")

    @embed.command(name="delete", aliases=["remove", "del"])
    @commands.has_permissions(manage_messages=True)
    async def embed_delete(self, ctx, name: str):
        """destroy a saved embed"""
        removed = await self.bot.db.execute("DELETE FROM embeds WHERE guild_id = ? AND name = ?", ctx.guild.id, name.lower())
        if not removed:
            return await ctx.warn(f"no embed named **{name}** rests here")
        await ctx.approve(f"**{name.lower()}** has been laid to rest for good")

    @embed.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def embed_list(self, ctx):
        """list saved embeds"""
        rows = await self.bot.db.fetchall(
            "SELECT name, author_id, created FROM embeds WHERE guild_id = ? ORDER BY name", ctx.guild.id
        )
        await ctx.paginate(
            [f"**{r['name']}** — by <@{r['author_id']}> <t:{r['created']}:R>" for r in rows],
            "⚰️ entombed embeds",
        )

    @commands.command(aliases=["vars"])
    async def variables(self, ctx):
        """list variables and embed script syntax"""
        embed = discord.Embed(
            color=theme.CRIMSON,
            title="📜 variables & embed scripts",
            description="\n".join(f"`{k}` — {v}" for k, v in VARIABLE_HELP.items()),
        )
        embed.add_field(
            name="embed scripts",
            value=(
                "start with `{embed}` and separate parts with `$v`:\n"
                "```{embed}$v{title: welcome {user.name}}$v{description: the night welcomes you}"
                "$v{color: #8a0303}$v{thumbnail: {user.avatar}}$v{content: {user.mention}}```"
                "parts: `content` `title` `description` `color` `url` `author: name && icon` "
                "`footer: text && icon` `thumbnail` `image` `timestamp` `field: name && value && inline` "
                "`button: label && url`"
            ),
            inline=False,
        )
        embed.add_field(
            name="rather click than type?",
            value=f"`{ctx.clean_prefix}embedbuilder` opens the forge and writes the script for you",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Embeds(bot))
