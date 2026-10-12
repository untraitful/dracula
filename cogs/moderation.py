import json
import time
from datetime import timedelta
from typing import Optional, Union

import discord
from discord.ext import commands

from core import theme, ui
from core.utils import Duration, can_moderate, human_delta

MAX_TIMEOUT = timedelta(days=28)


def audit(ctx, reason: Optional[str]) -> str:
    return f"{ctx.author} ({ctx.author.id}): {reason or 'no reason given'}"


class Moderation(commands.Cog):
    """punish the wicked and keep the crypt in order"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # ------------------------------------------------------------------ bans

    @commands.command(aliases=["banish"])
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, user: Union[discord.Member, discord.User], *, reason: Optional[str] = None):
        """banish a soul from the castle forever"""
        if isinstance(user, discord.Member) and not await can_moderate(ctx, user, "ban"):
            return
        await ctx.guild.ban(user, reason=audit(ctx, reason), delete_message_seconds=0)
        await ctx.approve(f"**{user}** has been banished to the void")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason: Optional[str] = None):
        """let a banished soul return"""
        try:
            await ctx.guild.unban(user, reason=audit(ctx, reason))
        except discord.NotFound:
            return await ctx.warn(f"**{user}** was never banished")
        await ctx.approve(f"**{user}** has been allowed back from the void")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        """ban and immediately unban a member to wipe their recent messages"""
        if not await can_moderate(ctx, member, "softban"):
            return
        await ctx.guild.ban(member, reason=audit(ctx, reason), delete_message_seconds=7 * 86400)
        await ctx.guild.unban(member, reason=audit(ctx, "softban"))
        await ctx.approve(f"**{member}** was softbanned and their words burned")

    @commands.command()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        """cast a member out of the castle gates"""
        if not await can_moderate(ctx, member, "kick"):
            return
        await member.kick(reason=audit(ctx, reason))
        await ctx.approve(f"**{member}** has been cast out into the night")

    # -------------------------------------------------------------- timeouts

    @commands.command(aliases=["mute", "to", "silence"])
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: Optional[Duration] = None, *, reason: Optional[str] = None):
        """silence a member for a while (default 5m, max 28d)"""
        if not await can_moderate(ctx, member, "timeout"):
            return
        duration = duration or timedelta(minutes=5)
        if duration > MAX_TIMEOUT:
            return await ctx.warn("a timeout cannot last longer than **28 days**")
        await member.timeout(duration, reason=audit(ctx, reason))
        await ctx.approve(f"**{member}** has been sealed in silence for **{human_delta(duration)}**")

    @commands.command(aliases=["unmute", "uto"])
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        """lift a member's timeout"""
        if not member.is_timed_out():
            return await ctx.warn(f"**{member}** is not silenced")
        await member.timeout(None, reason=audit(ctx, reason))
        await ctx.approve(f"**{member}** may speak once more")

    # ---------------------------------------------------------------- purges

    async def _purge(self, ctx, amount: int, check=lambda m: True):
        if not 1 <= amount <= 1000:
            return await ctx.warn("choose an amount between **1** and **1000**")
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        deleted = await ctx.channel.purge(limit=amount, check=check, bulk=True)
        await ctx.approve(f"devoured **{len(deleted)}** messages", delete_after=4)

    @commands.group(aliases=["clear", "c"], invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int, member: Optional[discord.Member] = None):
        """delete a number of messages, optionally only from one member"""
        await self._purge(ctx, amount, (lambda m: m.author == member) if member else (lambda m: True))

    @purge.command(name="bots")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge_bots(self, ctx, amount: int = 100):
        """delete messages sent by bots"""
        await self._purge(ctx, amount, lambda m: m.author.bot)

    @purge.command(name="contains")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge_contains(self, ctx, word: str, amount: int = 100):
        """delete messages containing a word"""
        await self._purge(ctx, amount, lambda m: word.lower() in m.content.lower())

    @purge.command(name="links")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge_links(self, ctx, amount: int = 100):
        """delete messages containing links"""
        await self._purge(ctx, amount, lambda m: "http://" in m.content or "https://" in m.content)

    @purge.command(name="images", aliases=["files", "attachments"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge_images(self, ctx, amount: int = 100):
        """delete messages with attachments"""
        await self._purge(ctx, amount, lambda m: bool(m.attachments))

    @commands.command(aliases=["bc"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def botclear(self, ctx, amount: int = 100):
        """clear messages from bots and commands using my prefix"""
        prefix = ctx.clean_prefix
        await self._purge(ctx, amount, lambda m: m.author.bot or m.content.startswith(prefix))

    # -------------------------------------------------------------- channels

    async def _overwrite(self, ctx, channel, reason, **perms):
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.update(**perms)
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=audit(ctx, reason))

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: Optional[discord.TextChannel] = None, *, reason: Optional[str] = None):
        """seal a channel so @everyone cannot speak"""
        channel = channel or ctx.channel
        await self._overwrite(ctx, channel, reason, send_messages=False, add_reactions=False, create_public_threads=False)
        await ctx.approve(f"{channel.mention} has been sealed 🔒")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: Optional[discord.TextChannel] = None, *, reason: Optional[str] = None):
        """unseal a locked channel"""
        channel = channel or ctx.channel
        await self._overwrite(ctx, channel, reason, send_messages=None, add_reactions=None, create_public_threads=None)
        await ctx.approve(f"{channel.mention} has been unsealed 🔓")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def hide(self, ctx, channel: Optional[discord.abc.GuildChannel] = None, *, reason: Optional[str] = None):
        """shroud a channel from @everyone"""
        channel = channel or ctx.channel
        await self._overwrite(ctx, channel, reason, view_channel=False)
        await ctx.approve(f"{channel.mention} has been shrouded in darkness")

    @commands.command(aliases=["reveal"])
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unhide(self, ctx, channel: Optional[discord.abc.GuildChannel] = None, *, reason: Optional[str] = None):
        """reveal a hidden channel"""
        channel = channel or ctx.channel
        await self._overwrite(ctx, channel, reason, view_channel=None)
        await ctx.approve(f"{channel.mention} has emerged from the shadows")

    @commands.command(aliases=["slow", "sm"])
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx, duration: Optional[Duration] = None, channel: Optional[discord.TextChannel] = None):
        """set a channel's slowmode (omit duration to disable)"""
        channel = channel or ctx.channel
        seconds = int(duration.total_seconds()) if duration else 0
        if seconds > 21600:
            return await ctx.warn("slowmode cannot exceed **6 hours**")
        await channel.edit(slowmode_delay=seconds, reason=audit(ctx, "slowmode"))
        if seconds:
            await ctx.approve(f"{channel.mention} now crawls at one message per **{human_delta(duration)}**")
        else:
            await ctx.approve(f"slowmode lifted from {channel.mention}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def nuke(self, ctx):
        """burn this channel to ash and rebuild it fresh"""
        if not await ctx.confirm(f"are you sure you want to burn {ctx.channel.mention} to ash?"):
            return await ctx.warn("the channel was spared")
        new = await ctx.channel.clone(reason=audit(ctx, "nuke"))
        await new.edit(position=ctx.channel.position)
        await ctx.channel.delete(reason=audit(ctx, "nuke"))
        await new.send(view=ui.Card(f"🔥 this channel rose from the ashes, rebuilt by {ctx.author.mention}"))

    # --------------------------------------------------------------- members

    @commands.command(aliases=["nick"])
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nickname(self, ctx, member: discord.Member, *, nickname: Optional[str] = None):
        """rename a member (omit nickname to reset)"""
        if member != ctx.author and not await can_moderate(ctx, member, "rename"):
            return
        await member.edit(nick=nickname[:32] if nickname else None, reason=audit(ctx, "nickname"))
        if nickname:
            await ctx.approve(f"**{member}** shall now be known as **{nickname[:32]}**")
        else:
            await ctx.approve(f"**{member}**'s true name has been restored")

    # ----------------------------------------------------------------- warns

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        """mark a member with a warning"""
        if not await can_moderate(ctx, member, "warn"):
            return
        await self.bot.db.execute(
            "INSERT INTO warns (guild_id, user_id, moderator_id, reason, created) VALUES (?, ?, ?, ?, ?)",
            ctx.guild.id, member.id, ctx.author.id, reason or "no reason given", int(time.time()),
        )
        count = await self.bot.db.fetchval("SELECT COUNT(*) FROM warns WHERE guild_id = ? AND user_id = ?", ctx.guild.id, member.id)
        await ctx.approve(f"**{member}** has been marked — they now bear **{count}** warning{'s' if count != 1 else ''}")
        try:
            await member.send(view=ui.Card(
                ui.heading(f"{theme.WARN_EMOJI} you have been marked", f"in {ctx.guild.name}", level=3),
                reason or "no reason given",
                accent=theme.WARN,
            ))
        except discord.HTTPException:
            pass

    @commands.command(aliases=["warns"])
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx, member: discord.Member):
        """view a member's warnings"""
        rows = await self.bot.db.fetchall(
            "SELECT id, moderator_id, reason, created FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY id DESC",
            ctx.guild.id, member.id,
        )
        lines = [f"**#{r['id']}** <t:{r['created']}:R> by <@{r['moderator_id']}> — {r['reason']}" for r in rows]
        await ctx.paginate(lines, f"warnings for {member}", numbered=False)

    @commands.command(aliases=["clearwarnings"])
    @commands.has_permissions(moderate_members=True)
    async def clearwarns(self, ctx, member: discord.Member):
        """wipe all of a member's warnings"""
        removed = await self.bot.db.execute("DELETE FROM warns WHERE guild_id = ? AND user_id = ?", ctx.guild.id, member.id)
        if not removed:
            return await ctx.warn(f"**{member}** bears no warnings")
        await ctx.approve(f"washed away **{removed}** warnings from **{member}**")

    @commands.command(aliases=["delwarn"])
    @commands.has_permissions(moderate_members=True)
    async def removewarn(self, ctx, warn_id: int):
        """remove a single warning by its id"""
        removed = await self.bot.db.execute("DELETE FROM warns WHERE guild_id = ? AND id = ?", ctx.guild.id, warn_id)
        if not removed:
            return await ctx.warn(f"no warning **#{warn_id}** exists")
        await ctx.approve(f"warning **#{warn_id}** has been erased")

    # ------------------------------------------------------------------ jail

    @commands.command(aliases=["setjail"])
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def setupjail(self, ctx):
        """create the jail role and dungeon channel"""
        existing = await self.bot.db.fetchone("SELECT role_id, channel_id FROM jail WHERE guild_id = ?", ctx.guild.id)
        if existing and ctx.guild.get_role(existing["role_id"]) and ctx.guild.get_channel(existing["channel_id"]):
            return await ctx.warn("the dungeon has already been built")
        message = await ctx.neutral(f"{theme.LOADING_EMOJI} digging the dungeon...")
        role = await ctx.guild.create_role(name="jailed", color=discord.Color(theme.NEUTRAL), reason=audit(ctx, "setup jail"))
        for channel in ctx.guild.channels:
            try:
                await channel.set_permissions(role, view_channel=False, reason=audit(ctx, "setup jail"))
            except discord.HTTPException:
                continue
        channel = await ctx.guild.create_text_channel(
            "dungeon",
            overwrites={
                ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                ctx.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            },
            reason=audit(ctx, "setup jail"),
        )
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO jail (guild_id, role_id, channel_id) VALUES (?, ?, ?)", ctx.guild.id, role.id, channel.id
        )
        await message.delete()
        await ctx.approve(f"the dungeon is ready: {role.mention} and {channel.mention}")

    async def _jail_config(self, ctx):
        row = await self.bot.db.fetchone("SELECT role_id, channel_id FROM jail WHERE guild_id = ?", ctx.guild.id)
        role = ctx.guild.get_role(row["role_id"]) if row else None
        if role is None:
            await ctx.warn(f"no dungeon exists yet — run `{ctx.clean_prefix}setupjail`")
            return None, None
        return role, ctx.guild.get_channel(row["channel_id"])

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def jail(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        """throw a member into the dungeon"""
        if not await can_moderate(ctx, member, "jail"):
            return
        role, channel = await self._jail_config(ctx)
        if role is None:
            return
        if role in member.roles:
            return await ctx.warn(f"**{member}** already rots in the dungeon")
        removable = [r for r in member.roles if not r.is_default() and not r.managed and r < ctx.guild.me.top_role]
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO jailed (guild_id, user_id, roles) VALUES (?, ?, ?)",
            ctx.guild.id, member.id, json.dumps([r.id for r in removable]),
        )
        kept = [r for r in member.roles if r not in removable]
        await member.edit(roles=kept + [role], reason=audit(ctx, reason))
        await ctx.approve(f"**{member}** has been chained in the dungeon")
        if channel:
            await channel.send(
                view=ui.Card(
                    ui.heading("⛓️ welcome to the dungeon", level=3),
                    f"{member.mention}, you have been chained here: {reason or 'no reason given'}\nrot here until you are freed.",
                    accent=theme.NEUTRAL,
                ),
                allowed_mentions=discord.AllowedMentions(users=[member]),
            )

    @commands.command(aliases=["free"])
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unjail(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        """free a member from the dungeon"""
        role, _ = await self._jail_config(ctx)
        if role is None:
            return
        row = await self.bot.db.fetchone("SELECT roles FROM jailed WHERE guild_id = ? AND user_id = ?", ctx.guild.id, member.id)
        if row is None and role not in member.roles:
            return await ctx.warn(f"**{member}** is not in the dungeon")
        restored = [ctx.guild.get_role(i) for i in json.loads(row["roles"])] if row else []
        restored = [r for r in restored if r and r < ctx.guild.me.top_role]
        roles = [r for r in member.roles if r != role] + [r for r in restored if r not in member.roles]
        await member.edit(roles=roles, reason=audit(ctx, reason))
        await self.bot.db.execute("DELETE FROM jailed WHERE guild_id = ? AND user_id = ?", ctx.guild.id, member.id)
        await ctx.approve(f"**{member}** has been released from their chains")

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def jailed(self, ctx):
        """list everyone currently in the dungeon"""
        rows = await self.bot.db.fetchall("SELECT user_id FROM jailed WHERE guild_id = ?", ctx.guild.id)
        await ctx.paginate([f"<@{r['user_id']}> (`{r['user_id']}`)" for r in rows], "souls in the dungeon")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
