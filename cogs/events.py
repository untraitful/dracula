"""Background listeners: greetings, autoroles, autoresponders, reaction roles, jail persistence."""

import logging

import discord
from discord.ext import commands

from core.scripting import send_script

log = logging.getLogger("dracula.events")


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # guild_id -> {trigger: response}
        self.autoresponders: dict[int, dict[str, str]] = {}

    async def cog_load(self):
        await self._load_autoresponders()

    async def _load_autoresponders(self, guild_id: int = None):
        if guild_id is None:
            self.autoresponders.clear()
            rows = await self.bot.db.fetchall("SELECT guild_id, trigger, response FROM autoresponders")
        else:
            self.autoresponders.pop(guild_id, None)
            rows = await self.bot.db.fetchall("SELECT guild_id, trigger, response FROM autoresponders WHERE guild_id = ?", guild_id)
        for row in rows:
            self.autoresponders.setdefault(row["guild_id"], {})[row["trigger"]] = row["response"]

    @commands.Cog.listener()
    async def on_autoresponders_changed(self, guild_id: int):
        await self._load_autoresponders(guild_id)

    async def _send_greetings(self, member: discord.Member, kind: str):
        rows = await self.bot.db.fetchall(
            "SELECT channel_id, message FROM greetings WHERE guild_id = ? AND kind = ?", member.guild.id, kind
        )
        for row in rows:
            channel = member.guild.get_channel(row["channel_id"])
            if channel is None:
                continue
            try:
                await send_script(channel, row["message"], member)
            except discord.HTTPException as e:
                log.warning("failed %s message in %s: %s", kind, channel.id, e)

    # -------------------------------------------------------------- members

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        me = guild.me

        # re-jail anyone who left to dodge the dungeon
        jailed = await self.bot.db.fetchone("SELECT 1 FROM jailed WHERE guild_id = ? AND user_id = ?", guild.id, member.id)
        jail_role_id = await self.bot.db.fetchval("SELECT role_id FROM jail WHERE guild_id = ?", guild.id)
        jail_role = guild.get_role(jail_role_id) if jail_role_id else None
        if jailed and jail_role and jail_role < me.top_role:
            try:
                await member.add_roles(jail_role, reason="rejoined while jailed")
            except discord.HTTPException:
                pass
        elif not member.bot:
            rows = await self.bot.db.fetchall("SELECT role_id FROM autoroles WHERE guild_id = ?", guild.id)
            roles = [guild.get_role(r["role_id"]) for r in rows]
            roles = [r for r in roles if r and r < me.top_role]
            if roles:
                try:
                    await member.add_roles(*roles, reason="autorole")
                except discord.HTTPException:
                    pass

        await self._send_greetings(member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._send_greetings(member, "goodbye")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.premium_since is None and after.premium_since is not None:
            await self._send_greetings(after, "boost")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        role_id = await self.bot.db.fetchval("SELECT role_id FROM jail WHERE guild_id = ?", channel.guild.id)
        role = channel.guild.get_role(role_id) if role_id else None
        if role is None:
            return
        try:
            await channel.set_permissions(role, view_channel=False, reason="keep the jailed in the dungeon")
        except discord.HTTPException:
            pass

    # ------------------------------------------------------- autoresponders

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        responders = self.autoresponders.get(message.guild.id)
        if not responders:
            return
        content = message.content.lower()
        words = set(content.split())
        for trigger, response in responders.items():
            hit = trigger in words if " " not in trigger else trigger in content
            if hit:
                try:
                    await send_script(message.channel, response, message.author)
                except discord.HTTPException:
                    pass
                break

    # ------------------------------------------------------- reaction roles

    async def _reaction_role(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return None, None
        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM reactionroles WHERE message_id = ? AND emoji = ?", payload.message_id, str(payload.emoji)
        )
        if not role_id:
            return None, None
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return None, None
        member = guild.get_member(payload.user_id)
        role = guild.get_role(role_id)
        if member is None or member.bot or role is None or role >= guild.me.top_role:
            return None, None
        return member, role

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        member, role = await self._reaction_role(payload)
        if member and role not in member.roles:
            try:
                await member.add_roles(role, reason="reaction role")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        member, role = await self._reaction_role(payload)
        if member and role in member.roles:
            try:
                await member.remove_roles(role, reason="reaction role")
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Events(bot))
