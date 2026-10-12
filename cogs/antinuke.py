import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

from core import theme, ui

WINDOW = 60  # seconds
WATCHED = {
    discord.AuditLogAction.ban: "mass banning",
    discord.AuditLogAction.kick: "mass kicking",
    discord.AuditLogAction.channel_delete: "deleting channels",
    discord.AuditLogAction.role_delete: "deleting roles",
    discord.AuditLogAction.webhook_create: "creating webhooks",
}
PUNISHMENTS = ("ban", "kick", "strip")


def guild_owner_only():
    async def predicate(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if ctx.author.id == ctx.guild.owner_id or await ctx.bot.is_owner(ctx.author):
            return True
        raise commands.CheckFailure("only the lord of this castle may touch its wards")
    return commands.check(predicate)


class Antinuke(commands.Cog):
    """wards against those who would raze your server"""

    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id, action) -> timestamps
        self.actions = defaultdict(deque)

    async def _config(self, guild_id: int):
        row = await self.bot.db.fetchone("SELECT enabled, threshold, punishment FROM antinuke WHERE guild_id = ?", guild_id)
        return row

    async def _ensure_row(self, guild_id: int):
        await self.bot.db.execute("INSERT OR IGNORE INTO antinuke (guild_id) VALUES (?)", guild_id)

    async def _trusted(self, guild: discord.Guild, user_id: int) -> bool:
        if user_id in (guild.owner_id, self.bot.user.id):
            return True
        return bool(await self.bot.db.fetchval(
            "SELECT 1 FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", guild.id, user_id
        ))

    # ------------------------------------------------------------ commands

    @commands.group(aliases=["an"], invoke_without_command=True)
    @guild_owner_only()
    async def antinuke(self, ctx):
        """view the server's antinuke wards"""
        row = await self._config(ctx.guild.id)
        whitelisted = await self.bot.db.fetchall("SELECT user_id FROM antinuke_whitelist WHERE guild_id = ?", ctx.guild.id)
        enabled = bool(row and row["enabled"])
        trusted = ", ".join(f"<@{r['user_id']}>" for r in whitelisted)[:1500] or "none"
        await ctx.send_card(ui.Card(
            ui.heading("🛡️ antinuke wards", "the wards are raised" if enabled else "the wards are down"),
            ui.sep(),
            ui.lines([
                f"{'🟢' if enabled else '🔴'} **status** {'warded' if enabled else 'unwarded'}",
                f"⚖️ **threshold** {row['threshold'] if row else 3} actions / {WINDOW}s",
                f"🗡️ **punishment** {row['punishment'] if row else 'ban'}",
            ]),
            ui.sep(),
            "👁️ **watching for**\n" + ", ".join([*WATCHED.values(), "adding bots"]),
            f"🤝 **trusted ({len(whitelisted)})**\n{trusted}",
            ui.small(f"{ctx.clean_prefix}help antinuke for configuration • {theme.FOOTER}"),
            accent=theme.APPROVE if enabled else theme.DENY,
        ))

    @antinuke.command(name="enable", aliases=["on"])
    @guild_owner_only()
    async def antinuke_enable(self, ctx):
        """raise the wards"""
        if not ctx.guild.me.guild_permissions.administrator:
            return await ctx.warn("i need **administrator** to guard this castle")
        await self._ensure_row(ctx.guild.id)
        await self.bot.db.execute("UPDATE antinuke SET enabled = 1 WHERE guild_id = ?", ctx.guild.id)
        await ctx.approve("the wards have been raised — move my role to the top so i can strike anyone")

    @antinuke.command(name="disable", aliases=["off"])
    @guild_owner_only()
    async def antinuke_disable(self, ctx):
        """lower the wards"""
        await self._ensure_row(ctx.guild.id)
        await self.bot.db.execute("UPDATE antinuke SET enabled = 0 WHERE guild_id = ?", ctx.guild.id)
        await ctx.approve("the wards have been lowered")

    @antinuke.command(name="threshold")
    @guild_owner_only()
    async def antinuke_threshold(self, ctx, amount: int):
        """how many destructive actions in 60s trigger punishment"""
        if not 1 <= amount <= 20:
            return await ctx.warn("the threshold must be between **1** and **20**")
        await self._ensure_row(ctx.guild.id)
        await self.bot.db.execute("UPDATE antinuke SET threshold = ? WHERE guild_id = ?", amount, ctx.guild.id)
        await ctx.approve(f"the wards will strike after **{amount}** actions")

    @antinuke.command(name="punishment")
    @guild_owner_only()
    async def antinuke_punishment(self, ctx, punishment: str):
        """ban, kick, or strip (remove their roles)"""
        punishment = punishment.lower()
        if punishment not in PUNISHMENTS:
            return await ctx.warn(f"choose one of: {', '.join(f'`{p}`' for p in PUNISHMENTS)}")
        await self._ensure_row(ctx.guild.id)
        await self.bot.db.execute("UPDATE antinuke SET punishment = ? WHERE guild_id = ?", punishment, ctx.guild.id)
        await ctx.approve(f"nukers will now be met with **{punishment}**")

    @antinuke.command(name="whitelist", aliases=["wl", "trust"])
    @guild_owner_only()
    async def antinuke_whitelist(self, ctx, user: discord.User):
        """toggle whether a user (or bot) is trusted by the wards"""
        removed = await self.bot.db.execute(
            "DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", ctx.guild.id, user.id
        )
        if removed:
            return await ctx.approve(f"**{user}** is no longer trusted by the wards")
        await self.bot.db.execute("INSERT INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)", ctx.guild.id, user.id)
        await ctx.approve(f"**{user}** is now trusted by the wards")

    # ------------------------------------------------------------ listener

    async def _punish(self, guild: discord.Guild, user_id: int, punishment: str, why: str):
        reason = f"antinuke: {why}"
        member = guild.get_member(user_id)
        try:
            if punishment == "ban":
                await guild.ban(discord.Object(id=user_id), reason=reason)
            elif punishment == "kick" and member:
                await member.kick(reason=reason)
            elif punishment == "strip" and member:
                keep = [r for r in member.roles if r.is_default() or r.managed or r >= guild.me.top_role]
                await member.edit(roles=keep, reason=reason)
        except discord.HTTPException:
            return
        if guild.owner:
            try:
                await guild.owner.send(view=ui.Card(
                    ui.heading("🛡️ the wards have struck", guild.name, level=3),
                    f"<@{user_id}> (`{user_id}`) was met with **{punishment}** for {why}",
                    accent=theme.DENY,
                ))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        if entry.user_id is None:
            return
        if entry.action not in WATCHED and entry.action != discord.AuditLogAction.bot_add:
            return
        config = await self._config(guild.id)
        if not config or not config["enabled"]:
            return
        if await self._trusted(guild, entry.user_id):
            return

        if entry.action == discord.AuditLogAction.bot_add:
            # unauthorised bot: remove the bot and punish whoever added it
            target = entry.target
            if target is not None:
                try:
                    await guild.ban(discord.Object(id=target.id), reason="antinuke: unauthorised bot")
                except discord.HTTPException:
                    pass
            await self._punish(guild, entry.user_id, config["punishment"], "adding an untrusted bot")
            return

        key = (guild.id, entry.user_id, entry.action)
        now = time.monotonic()
        stamps = self.actions[key]
        stamps.append(now)
        while stamps and now - stamps[0] > WINDOW:
            stamps.popleft()
        if len(stamps) >= config["threshold"]:
            stamps.clear()
            await self._punish(guild, entry.user_id, config["punishment"], WATCHED[entry.action])


async def setup(bot):
    await bot.add_cog(Antinuke(bot))
