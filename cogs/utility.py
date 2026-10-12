import random
import re
import time
from collections import defaultdict, deque
from typing import Optional, Union

import discord
from discord.ext import commands

from core import theme

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
        embed = discord.Embed(color=theme.CRIMSON, description=data["content"] or "*no text*", timestamp=data["time"])
        embed.set_author(name=data["author"].display_name, icon_url=data["author"].display_avatar.url)
        if data["attachment"]:
            embed.set_image(url=data["attachment"])
        embed.set_footer(text=f"👻 ghost {index}/{total}")
        await ctx.send(embed=embed)

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
        embed = discord.Embed(color=theme.CRIMSON, timestamp=data["time"])
        embed.set_author(name=data["author"].display_name, icon_url=data["author"].display_avatar.url)
        embed.add_field(name="before", value=(data["before"] or "*no text*")[:1024], inline=False)
        embed.add_field(name="after", value=(data["after"] or "*no text*")[:1024], inline=False)
        embed.set_footer(text=f"👻 ghost {index}/{total}")
        await ctx.send(embed=embed)

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
            await message.channel.send(embed=discord.Embed(
                color=theme.APPROVE,
                description=f"🌅 {message.author.mention}: welcome back from the grave, you slept since <t:{since}:R>",
            ))

        seen = set()
        for user in message.mentions:
            if user.id in self.afk_cache and user.id not in seen:
                seen.add(user.id)
                reason, since = self.afk_cache[user.id]
                await message.channel.send(embed=discord.Embed(
                    color=theme.NEUTRAL,
                    description=f"⚰️ {user.mention} is slumbering: **{reason}** — since <t:{since}:R>",
                ))

    # ------------------------------------------------------------- avatars

    @commands.command(aliases=["av", "pfp"])
    async def avatar(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        """gaze upon a user's avatar"""
        user = user or ctx.author
        embed = discord.Embed(color=theme.CRIMSON, title=f"{user.name}'s avatar", url=user.display_avatar.url)
        embed.set_image(url=user.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(aliases=["sav"])
    @commands.guild_only()
    async def serveravatar(self, ctx, member: Optional[discord.Member] = None):
        """a member's server-specific avatar"""
        member = member or ctx.author
        if not member.guild_avatar:
            return await ctx.warn(f"**{member}** wears no server avatar")
        embed = discord.Embed(color=theme.CRIMSON, title=f"{member.name}'s server avatar", url=member.guild_avatar.url)
        embed.set_image(url=member.guild_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    async def banner(self, ctx, user: Optional[discord.User] = None):
        """gaze upon a user's banner"""
        user = await self.bot.fetch_user((user or ctx.author).id)
        if not user.banner:
            return await ctx.warn(f"**{user}** has no banner")
        embed = discord.Embed(color=theme.CRIMSON, title=f"{user.name}'s banner", url=user.banner.url)
        embed.set_image(url=user.banner.url)
        await ctx.send(embed=embed)

    @commands.command(aliases=["sicon"])
    @commands.guild_only()
    async def servericon(self, ctx):
        """the server's icon"""
        if not ctx.guild.icon:
            return await ctx.warn("this castle has no crest")
        embed = discord.Embed(color=theme.CRIMSON, title=f"{ctx.guild.name}'s icon", url=ctx.guild.icon.url)
        embed.set_image(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    @commands.command(aliases=["sbanner"])
    @commands.guild_only()
    async def serverbanner(self, ctx):
        """the server's banner"""
        if not ctx.guild.banner:
            return await ctx.warn("this castle flies no banner")
        embed = discord.Embed(color=theme.CRIMSON, title=f"{ctx.guild.name}'s banner", url=ctx.guild.banner.url)
        embed.set_image(url=ctx.guild.banner.url)
        await ctx.send(embed=embed)

    # ---------------------------------------------------------------- info

    @commands.command(aliases=["ui", "whois"])
    async def userinfo(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        """read a soul's records"""
        user = user or ctx.author
        embed = discord.Embed(color=theme.CRIMSON, title=f"{user} {'🤖' if user.bot else ''}")
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="created", value=f"{discord.utils.format_dt(user.created_at, 'D')}\n{discord.utils.format_dt(user.created_at, 'R')}")
        if isinstance(user, discord.Member):
            embed.add_field(name="joined", value=f"{discord.utils.format_dt(user.joined_at, 'D')}\n{discord.utils.format_dt(user.joined_at, 'R')}")
            if user.premium_since:
                embed.add_field(name="boosted", value=discord.utils.format_dt(user.premium_since, "R"))
            position = sorted(ctx.guild.members, key=lambda m: m.joined_at or discord.utils.utcnow()).index(user) + 1
            roles = [r.mention for r in reversed(user.roles) if not r.is_default()]
            shown = ", ".join(roles[:15]) + (f" (+{len(roles) - 15})" if len(roles) > 15 else "")
            embed.add_field(name=f"roles ({len(roles)})", value=shown or "none", inline=False)
            embed.set_footer(text=f"join position: {position} • id: {user.id}")
        else:
            embed.set_footer(text=f"id: {user.id}")
        await ctx.send(embed=embed)

    @commands.command(aliases=["si", "guildinfo"])
    @commands.guild_only()
    async def serverinfo(self, ctx):
        """read the castle's records"""
        g = ctx.guild
        embed = discord.Embed(color=theme.CRIMSON, title=g.name, description=g.description or None)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        if g.banner:
            embed.set_image(url=g.banner.with_size(1024).url)
        bots = sum(1 for m in g.members if m.bot)
        embed.add_field(name="owner", value=g.owner.mention if g.owner else f"<@{g.owner_id}>")
        embed.add_field(name="created", value=discord.utils.format_dt(g.created_at, "R"))
        embed.add_field(name="members", value=f"{g.member_count:,} total\n{(g.member_count or 0) - bots:,} humans\n{bots:,} bots")
        embed.add_field(name="channels", value=f"{len(g.text_channels)} text\n{len(g.voice_channels)} voice\n{len(g.categories)} categories")
        embed.add_field(name="boosts", value=f"{g.premium_subscription_count} (level {g.premium_tier})")
        embed.add_field(name="other", value=f"{len(g.roles)} roles\n{len(g.emojis)} emojis\n{len(g.stickers)} stickers")
        embed.set_footer(text=f"id: {g.id}")
        await ctx.send(embed=embed)

    @commands.command(aliases=["ri"])
    @commands.guild_only()
    async def roleinfo(self, ctx, *, role: discord.Role):
        """read a bloodline's records"""
        embed = discord.Embed(color=role.color.value or theme.CRIMSON, title=role.name)
        embed.add_field(name="id", value=f"`{role.id}`")
        embed.add_field(name="color", value=str(role.color))
        embed.add_field(name="members", value=str(len(role.members)))
        embed.add_field(name="created", value=discord.utils.format_dt(role.created_at, "R"))
        embed.add_field(name="position", value=str(role.position))
        embed.add_field(name="hoisted / mentionable", value=f"{role.hoist} / {role.mentionable}")
        perms = [p.replace("_", " ") for p, v in role.permissions if v]
        if perms:
            embed.add_field(name="permissions", value=", ".join(perms)[:1024], inline=False)
        if role.display_icon and isinstance(role.display_icon, discord.Asset):
            embed.set_thumbnail(url=role.display_icon.url)
        await ctx.send(embed=embed)

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
        embed = discord.Embed(color=theme.CRIMSON)
        embed.set_author(name=f"{g.name} statistics", icon_url=g.icon.url if g.icon else None)
        embed.add_field(name="souls", value=f"{g.member_count:,}")
        embed.add_field(name="humans", value=f"{(g.member_count or 0) - bots:,}")
        embed.add_field(name="bots", value=f"{bots:,}")
        await ctx.send(embed=embed)

    @commands.command(aliases=["firstmsg"])
    @commands.guild_only()
    async def firstmessage(self, ctx, channel: Optional[discord.TextChannel] = None):
        """jump to the first message ever sent in a channel"""
        channel = channel or ctx.channel
        async for message in channel.history(limit=1, oldest_first=True):
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="descend", emoji="🕯️", url=message.jump_url))
            return await ctx.neutral(f"the first words ever spoken in {channel.mention}, by **{message.author}**", view=view)
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
        embed = discord.Embed(color=theme.CRIMSON, title=name, url=url)
        embed.set_image(url=url)
        await ctx.send(embed=embed)

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
