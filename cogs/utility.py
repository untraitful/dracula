import random
import re
import time
from collections import defaultdict, deque
from typing import Optional, Union

import discord
from discord.ext import commands

from core import theme, ui

SNIPE_LIMIT = 25
CUSTOM_EMOJI = re.compile(r"<(a?):(\w+):(\d+)>")


class Utility(commands.Cog):
    """scrying tools for members, servers and messages"""

    def __init__(self, bot):
        self.bot = bot
        # channel_id -> deque of snapshots (newest first)
        self.snipes = defaultdict(lambda: deque(maxlen=SNIPE_LIMIT))
        self.edit_snipes = defaultdict(lambda: deque(maxlen=SNIPE_LIMIT))
        self.reaction_snipes = defaultdict(lambda: deque(maxlen=SNIPE_LIMIT))
        self.afk_cache: dict[int, tuple[str, int]] = {}

    async def cog_load(self):
        for row in await self.bot.db.fetchall("SELECT user_id, reason, since FROM afk"):
            self.afk_cache[row["user_id"]] = (row["reason"], row["since"])

    # -------------------------------------------------------------- snipes

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        self.snipes[message.channel.id].appendleft({
            "author": message.author,
            "content": message.content,
            "attachment": message.attachments[0].proxy_url if message.attachments else None,
            "time": message.created_at,
        })

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        self.edit_snipes[before.channel.id].appendleft({
            "author": before.author,
            "before": before.content,
            "after": after.content,
            "time": after.edited_at or discord.utils.utcnow(),
        })

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        if member is None or member.bot:
            return
        self.reaction_snipes[payload.channel_id].appendleft({
            "author": member,
            "emoji": str(payload.emoji),
            "message_id": payload.message_id,
            "time": discord.utils.utcnow(),
        })

    def _snipe_pick(self, ctx, store, index: int):
        entries = store.get(ctx.channel.id)
        if not entries:
            return None
        if not 1 <= index <= len(entries):
            return False
        return entries[index - 1], len(entries)

    @commands.command(aliases=["s"])
    @commands.guild_only()
    async def snipe(self, ctx, index: int = 1):
        """see the last deleted message in this channel"""
        picked = self._snipe_pick(ctx, self.snipes, index)
        if picked is None:
            return await ctx.warn("no deleted messages haunt this channel")
        if picked is False:
            return await ctx.warn("there are not that many ghosts here")
        data, total = picked
        author = data["author"]
        await ctx.send_card(ui.Card(
            ui.section(
                f"### {author.display_name}\n{data['content'] or '*no text*'}",
                thumbnail=author.display_avatar.url,
            ),
            ui.gallery(data["attachment"]),
            ui.small(f"👻 ghost {index}/{total} • deleted message sent {discord.utils.format_dt(data['time'], 'R')}"),
        ))

    @commands.command(aliases=["es"])
    @commands.guild_only()
    async def editsnipe(self, ctx, index: int = 1):
        """see the last edited message in this channel"""
        picked = self._snipe_pick(ctx, self.edit_snipes, index)
        if picked is None:
            return await ctx.warn("no edited messages haunt this channel")
        if picked is False:
            return await ctx.warn("there are not that many ghosts here")
        data, total = picked
        author = data["author"]
        await ctx.send_card(ui.Card(
            ui.section(f"### {author.display_name}\n-# edited {discord.utils.format_dt(data['time'], 'R')}",
                       thumbnail=author.display_avatar.url),
            ui.sep(),
            f"**before**\n{(data['before'] or '*no text*')[:1500]}",
            f"**after**\n{(data['after'] or '*no text*')[:1500]}",
            ui.small(f"👻 ghost {index}/{total}"),
        ))

    @commands.command(aliases=["rs"])
    @commands.guild_only()
    async def reactionsnipe(self, ctx, index: int = 1):
        """see the last removed reaction in this channel"""
        picked = self._snipe_pick(ctx, self.reaction_snipes, index)
        if picked is None:
            return await ctx.warn("no removed reactions haunt this channel")
        if picked is False:
            return await ctx.warn("there are not that many ghosts here")
        data, total = picked
        link = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/{data['message_id']}"
        await ctx.neutral(
            f"**{data['author'].display_name}** removed {data['emoji']} from [this message]({link}) "
            f"{discord.utils.format_dt(data['time'], 'R')} • {index}/{total}"
        )

    @commands.command(aliases=["cs"])
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx):
        """exorcise every snipe in this channel"""
        for store in (self.snipes, self.edit_snipes, self.reaction_snipes):
            store.pop(ctx.channel.id, None)
        await ctx.approve("the ghosts of this channel have been exorcised")

    # ----------------------------------------------------------------- afk

    @commands.command()
    async def afk(self, ctx, *, reason: str = "slumbering in the coffin"):
        """go afk — anyone who mentions you will be told"""
        reason = discord.utils.escape_mentions(reason)[:200]
        since = int(time.time())
        self.afk_cache[ctx.author.id] = (reason, since)
        await self.bot.db.execute("INSERT OR REPLACE INTO afk (user_id, reason, since) VALUES (?, ?, ?)", ctx.author.id, reason, since)
        await ctx.approve(f"you descend into slumber: **{reason}**")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid and ctx.command.name == "afk":
            return

        if message.author.id in self.afk_cache:
            _, since = self.afk_cache.pop(message.author.id)
            await self.bot.db.execute("DELETE FROM afk WHERE user_id = ?", message.author.id)
            await message.channel.send(view=ui.Card(
                f"🌅 {message.author.mention}: welcome back from the grave, you slept since <t:{since}:R>",
                accent=theme.APPROVE,
            ))

        seen = set()
        for user in message.mentions:
            if user.id in self.afk_cache and user.id not in seen:
                seen.add(user.id)
                reason, since = self.afk_cache[user.id]
                await message.channel.send(view=ui.Card(
                    f"⚰️ {user.mention} is slumbering: **{reason}** — since <t:{since}:R>",
                    accent=theme.NEUTRAL,
                ))

    # ------------------------------------------------------------- avatars

    @commands.command(aliases=["av", "pfp"])
    async def avatar(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        """gaze upon a user's avatar"""
        user = user or ctx.author
        await ctx.send_card(ui.media_card(f"{user.name}'s avatar", user.display_avatar.url))

    @commands.command(aliases=["sav"])
    @commands.guild_only()
    async def serveravatar(self, ctx, member: Optional[discord.Member] = None):
        """a member's server-specific avatar"""
        member = member or ctx.author
        if not member.guild_avatar:
            return await ctx.warn(f"**{member}** wears no server avatar")
        await ctx.send_card(ui.media_card(f"{member.name}'s server avatar", member.guild_avatar.url))

    @commands.command()
    async def banner(self, ctx, user: Optional[discord.User] = None):
        """gaze upon a user's banner"""
        user = await self.bot.fetch_user((user or ctx.author).id)
        if not user.banner:
            return await ctx.warn(f"**{user}** has no banner")
        await ctx.send_card(ui.media_card(f"{user.name}'s banner", user.banner.url))

    @commands.command(aliases=["sicon"])
    @commands.guild_only()
    async def servericon(self, ctx):
        """the server's icon"""
        if not ctx.guild.icon:
            return await ctx.warn("this castle has no crest")
        await ctx.send_card(ui.media_card(f"{ctx.guild.name}'s crest", ctx.guild.icon.url))

    @commands.command(aliases=["sbanner"])
    @commands.guild_only()
    async def serverbanner(self, ctx):
        """the server's banner"""
        if not ctx.guild.banner:
            return await ctx.warn("this castle flies no banner")
        await ctx.send_card(ui.media_card(f"{ctx.guild.name}'s banner", ctx.guild.banner.url))

    # ---------------------------------------------------------------- info

    @commands.command(aliases=["ui", "whois"])
    async def userinfo(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        """read a soul's records"""
        user = user or ctx.author
        fmt = discord.utils.format_dt
        info = [f"🕯️ **created** {fmt(user.created_at, 'D')} ({fmt(user.created_at, 'R')})"]
        extra = []
        footer = f"id {user.id}"
        if isinstance(user, discord.Member):
            info.append(f"🦇 **joined** {fmt(user.joined_at, 'D')} ({fmt(user.joined_at, 'R')})")
            if user.premium_since:
                info.append(f"💎 **boosting since** {fmt(user.premium_since, 'R')}")
            position = sorted(ctx.guild.members, key=lambda m: m.joined_at or discord.utils.utcnow()).index(user) + 1
            roles = [r.mention for r in reversed(user.roles) if not r.is_default()]
            shown = " ".join(roles[:20]) + (f" *+{len(roles) - 20} more*" if len(roles) > 20 else "")
            extra = [ui.sep(), f"🩸 **bloodlines ({len(roles)})**\n{shown or 'none'}"]
            footer = f"join position {position} • {footer}"
        accent = user.color.value if isinstance(user, discord.Member) and user.color.value else theme.CRIMSON
        await ctx.send_card(ui.Card(
            ui.section(
                f"## {user.display_name} {'🤖' if user.bot else ''}\n-# @{user.name}",
                thumbnail=user.display_avatar.url,
            ),
            ui.sep(),
            "\n".join(info),
            *extra,
            ui.small(footer),
            accent=accent,
        ))

    @commands.command(aliases=["si", "guildinfo"])
    @commands.guild_only()
    async def serverinfo(self, ctx):
        """read the castle's records"""
        g = ctx.guild
        bots = sum(1 for m in g.members if m.bot)
        humans = (g.member_count or 0) - bots
        owner = g.owner.mention if g.owner else f"<@{g.owner_id}>"
        await ctx.send_card(ui.Card(
            ui.section(
                f"## {g.name}\n{g.description or '*a castle in the dark*'}\n-# lorded over by {owner} • built {discord.utils.format_dt(g.created_at, 'R')}",
                thumbnail=g.icon.url if g.icon else None,
            ),
            ui.sep(),
            ui.lines([
                f"👥 **souls** {g.member_count:,} — {humans:,} humans, {bots:,} bots",
                f"🕯️ **chambers** {len(g.text_channels)} text, {len(g.voice_channels)} voice, {len(g.categories)} categories",
                f"💎 **boosts** {g.premium_subscription_count} (level {g.premium_tier})",
                f"🩸 **other** {len(g.roles)} roles, {len(g.emojis)} emojis, {len(g.stickers)} stickers",
            ]),
            ui.gallery(g.banner.with_size(1024).url if g.banner else None),
            ui.small(f"id {g.id}"),
        ))

    @commands.command(aliases=["ri"])
    @commands.guild_only()
    async def roleinfo(self, ctx, *, role: discord.Role):
        """read a bloodline's records"""
        perms = [p.replace("_", " ") for p, v in role.permissions if v]
        icon = role.display_icon.url if isinstance(role.display_icon, discord.Asset) else None
        await ctx.send_card(ui.Card(
            ui.section(
                f"## {role.name}\n-# {role.mention} • `{role.id}`",
                thumbnail=icon,
            ),
            ui.sep(),
            ui.lines([
                f"🎨 **colour** `{role.color}`",
                f"👥 **members** {len(role.members)}",
                f"🕯️ **created** {discord.utils.format_dt(role.created_at, 'R')}",
                f"🏰 **position** {role.position}",
                f"📌 **hoisted** {'yes' if role.hoist else 'no'} • **mentionable** {'yes' if role.mentionable else 'no'}",
            ]),
            (ui.sep() if perms else None),
            (f"🗝️ **permissions**\n{', '.join(perms)[:1500]}" if perms else None),
            accent=role.color.value or theme.CRIMSON,
        ))

    @commands.command()
    @commands.guild_only()
    async def inrole(self, ctx, *, role: discord.Role):
        """list members with a role"""
        await ctx.paginate([f"{m.mention} (`{m.id}`)" for m in role.members], f"members in {role.name}")

    @commands.command(aliases=["mc"])
    @commands.guild_only()
    async def membercount(self, ctx):
        """count the souls in this castle"""
        g = ctx.guild
        bots = sum(1 for m in g.members if m.bot)
        await ctx.send_card(ui.Card(
            ui.section(
                f"### {g.name}\n👥 **{g.member_count:,}** souls • 🧛 **{(g.member_count or 0) - bots:,}** humans • 🤖 **{bots:,}** bots",
                thumbnail=g.icon.url if g.icon else None,
            ),
        ))

    @commands.command(aliases=["firstmsg"])
    @commands.guild_only()
    async def firstmessage(self, ctx, channel: Optional[discord.TextChannel] = None):
        """jump to the first message ever sent in a channel"""
        channel = channel or ctx.channel
        async for message in channel.history(limit=1, oldest_first=True):
            return await ctx.send_card(ui.Card(
                ui.section(
                    f"📜 the first words ever spoken in {channel.mention}, by **{message.author}** "
                    f"{discord.utils.format_dt(message.created_at, 'R')}",
                    button=ui.link("descend", message.jump_url, "🕯️"),
                ),
                accent=theme.NEUTRAL,
            ))
        await ctx.warn("this channel has never heard a word")

    @commands.command()
    @commands.guild_only()
    async def bots(self, ctx):
        """list every bot in the server"""
        await ctx.paginate([f"{m.mention} (`{m.id}`)" for m in ctx.guild.members if m.bot], "bots in the castle")

    # --------------------------------------------------------------- emojis

    @commands.command(aliases=["e", "jumbo"])
    async def enlarge(self, ctx, emoji: str):
        """enlarge a custom emoji"""
        match = CUSTOM_EMOJI.match(emoji)
        if not match:
            return await ctx.warn("that is not a custom emoji")
        animated, name, emoji_id = match.groups()
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if animated else 'png'}?size=1024"
        await ctx.send_card(ui.media_card(f":{name}:", url))

    @commands.command(aliases=["addemoji"])
    @commands.guild_only()
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def steal(self, ctx, emoji: str, name: Optional[str] = None):
        """steal a custom emoji into this server"""
        match = CUSTOM_EMOJI.match(emoji)
        if not match:
            return await ctx.warn("that is not a custom emoji")
        animated, original, emoji_id = match.groups()
        partial = discord.PartialEmoji(name=original, id=int(emoji_id), animated=bool(animated))
        data = await partial.read()
        try:
            new = await ctx.guild.create_custom_emoji(name=name or original, image=data, reason=f"stolen by {ctx.author}")
        except discord.HTTPException as e:
            return await ctx.warn(f"the theft failed: {e.text}")
        await ctx.approve(f"stole {new} as **{new.name}**")

    # ------------------------------------------------------------------ fun

    @commands.command()
    async def choose(self, ctx, *, options: str):
        """let fate choose between options separated by commas"""
        choices = [o.strip() for o in options.split(",") if o.strip()]
        if len(choices) < 2:
            return await ctx.warn("give me at least two choices, separated by commas")
        await ctx.neutral(f"🔮 the spirits choose: **{discord.utils.escape_markdown(random.choice(choices))}**")

    @commands.command(aliases=["8ball"])
    async def eightball(self, ctx, *, question: str):
        """consult the crystal ball"""
        answers = [
            "the spirits say yes", "it is written in blood", "without a doubt", "the bats agree",
            "the mist is too thick, ask again", "the dead are silent on this", "ask again at midnight",
            "the omens say no", "the candle flickers out... no", "do not count on it, mortal",
        ]
        await ctx.neutral(f"🔮 {random.choice(answers)}")


async def setup(bot):
    await bot.add_cog(Utility(bot))
