import discord
from discord.ext import commands

from core import ui


class VoiceMaster(commands.Cog):
    """temporary voice crypts owned by their creators"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # --------------------------------------------------------------- setup

    @commands.group(aliases=["vm"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def voicemaster(self, ctx):
        """set up join-to-create voice channels"""
        await ctx.send_help(ctx.command)

    @voicemaster.command(name="setup")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True, move_members=True)
    async def vm_setup(self, ctx):
        """create the voicemaster category and join channel"""
        row = await self.bot.db.fetchone("SELECT channel_id FROM voicemaster WHERE guild_id = ?", ctx.guild.id)
        if row and ctx.guild.get_channel(row["channel_id"]):
            return await ctx.warn(f"voicemaster already rises here — use `{ctx.clean_prefix}vm reset` first")
        category = await ctx.guild.create_category("🦇 crypts", reason=f"voicemaster setup by {ctx.author}")
        channel = await category.create_voice_channel("➕ open a crypt", reason=f"voicemaster setup by {ctx.author}")
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO voicemaster (guild_id, channel_id, category_id) VALUES (?, ?, ?)",
            ctx.guild.id, channel.id, category.id,
        )
        await ctx.approve(f"voicemaster has risen — join {channel.mention} to open your own crypt")

    @voicemaster.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def vm_reset(self, ctx):
        """tear down voicemaster"""
        row = await self.bot.db.fetchone("SELECT channel_id, category_id FROM voicemaster WHERE guild_id = ?", ctx.guild.id)
        if not row:
            return await ctx.warn("voicemaster is not set up")
        temp = await self.bot.db.fetchall("SELECT channel_id FROM vm_channels WHERE guild_id = ?", ctx.guild.id)
        for channel_id in [row["channel_id"], *(r["channel_id"] for r in temp), row["category_id"]]:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete(reason=f"voicemaster reset by {ctx.author}")
                except discord.HTTPException:
                    pass
        await self.bot.db.execute("DELETE FROM voicemaster WHERE guild_id = ?", ctx.guild.id)
        await self.bot.db.execute("DELETE FROM vm_channels WHERE guild_id = ?", ctx.guild.id)
        await ctx.approve("voicemaster has been laid to rest")

    # ------------------------------------------------------------- listener

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel:
            return
        guild = member.guild

        if after.channel:
            row = await self.bot.db.fetchone("SELECT channel_id, category_id FROM voicemaster WHERE guild_id = ?", guild.id)
            if row and after.channel.id == row["channel_id"]:
                category = guild.get_channel(row["category_id"]) or after.channel.category
                try:
                    channel = await guild.create_voice_channel(
                        f"{member.display_name}'s crypt"[:100],
                        category=category,
                        overwrites={member: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True)},
                        reason="voicemaster",
                    )
                    await self.bot.db.execute(
                        "INSERT INTO vm_channels (channel_id, guild_id, owner_id) VALUES (?, ?, ?)", channel.id, guild.id, member.id
                    )
                    await member.move_to(channel)
                except discord.HTTPException:
                    pass

        if before.channel and not before.channel.members:
            owner = await self.bot.db.fetchval("SELECT owner_id FROM vm_channels WHERE channel_id = ?", before.channel.id)
            if owner is not None:
                try:
                    await before.channel.delete(reason="voicemaster: crypt emptied")
                except discord.HTTPException:
                    pass
                await self.bot.db.execute("DELETE FROM vm_channels WHERE channel_id = ?", before.channel.id)

    # -------------------------------------------------------------- control

    async def _owned_channel(self, ctx):
        channel = ctx.author.voice.channel if ctx.author.voice else None
        if channel is None:
            await ctx.warn("you are not inside a crypt")
            return None
        owner = await self.bot.db.fetchval("SELECT owner_id FROM vm_channels WHERE channel_id = ?", channel.id)
        if owner is None:
            await ctx.warn("this is not a voicemaster crypt")
            return None
        if owner != ctx.author.id:
            await ctx.warn("you do not own this crypt")
            return None
        return channel

    @commands.group(aliases=["vc"], invoke_without_command=True)
    async def voice(self, ctx):
        """control your voicemaster crypt"""
        await ctx.send_help(ctx.command)

    @voice.command(name="lock")
    async def voice_lock(self, ctx):
        """seal your crypt so no one can join"""
        if channel := await self._owned_channel(ctx):
            await channel.set_permissions(ctx.guild.default_role, connect=False)
            await ctx.approve(f"{channel.mention} has been sealed 🔒")

    @voice.command(name="unlock")
    async def voice_unlock(self, ctx):
        """unseal your crypt"""
        if channel := await self._owned_channel(ctx):
            await channel.set_permissions(ctx.guild.default_role, connect=None)
            await ctx.approve(f"{channel.mention} has been unsealed 🔓")

    @voice.command(name="hide", aliases=["ghost"])
    async def voice_hide(self, ctx):
        """make your crypt invisible"""
        if channel := await self._owned_channel(ctx):
            await channel.set_permissions(ctx.guild.default_role, view_channel=False)
            await ctx.approve(f"{channel.mention} has vanished into the mist")

    @voice.command(name="reveal", aliases=["unhide", "unghost"])
    async def voice_reveal(self, ctx):
        """make your crypt visible again"""
        if channel := await self._owned_channel(ctx):
            await channel.set_permissions(ctx.guild.default_role, view_channel=None)
            await ctx.approve(f"{channel.mention} has emerged from the mist")

    @voice.command(name="rename", aliases=["name"])
    async def voice_rename(self, ctx, *, name: str):
        """rename your crypt"""
        if channel := await self._owned_channel(ctx):
            await channel.edit(name=name[:100])
            await ctx.approve(f"your crypt is now named **{name[:100]}**")

    @voice.command(name="limit")
    async def voice_limit(self, ctx, limit: int):
        """set a member limit (0 for none)"""
        if not 0 <= limit <= 99:
            return await ctx.warn("the limit must be between **0** and **99**")
        if channel := await self._owned_channel(ctx):
            await channel.edit(user_limit=limit)
            await ctx.approve(f"your crypt now holds {'unlimited' if not limit else f'**{limit}**'} souls")

    @voice.command(name="permit", aliases=["allow"])
    async def voice_permit(self, ctx, member: discord.Member):
        """allow a member into your sealed crypt"""
        if channel := await self._owned_channel(ctx):
            await channel.set_permissions(member, connect=True, view_channel=True)
            await ctx.approve(f"**{member}** may now enter your crypt")

    @voice.command(name="reject", aliases=["deny"])
    async def voice_reject(self, ctx, member: discord.Member):
        """bar a member from your crypt (and kick them out)"""
        if member == ctx.author:
            return await ctx.warn("you cannot bar yourself")
        if channel := await self._owned_channel(ctx):
            await channel.set_permissions(member, connect=False)
            if member.voice and member.voice.channel == channel:
                await member.move_to(None)
            await ctx.approve(f"**{member}** has been barred from your crypt")

    @voice.command(name="claim")
    async def voice_claim(self, ctx):
        """claim a crypt whose owner has left"""
        channel = ctx.author.voice.channel if ctx.author.voice else None
        if channel is None:
            return await ctx.warn("you are not inside a crypt")
        owner_id = await self.bot.db.fetchval("SELECT owner_id FROM vm_channels WHERE channel_id = ?", channel.id)
        if owner_id is None:
            return await ctx.warn("this is not a voicemaster crypt")
        if owner_id == ctx.author.id:
            return await ctx.warn("you already own this crypt")
        if any(m.id == owner_id for m in channel.members):
            return await ctx.warn("the owner still lingers here")
        await self.bot.db.execute("UPDATE vm_channels SET owner_id = ? WHERE channel_id = ?", ctx.author.id, channel.id)
        await channel.set_permissions(ctx.author, connect=True, manage_channels=True, move_members=True)
        await ctx.approve(f"you have claimed {channel.mention}")

    @voice.command(name="transfer")
    async def voice_transfer(self, ctx, member: discord.Member):
        """give your crypt to someone inside it"""
        if channel := await self._owned_channel(ctx):
            if member not in channel.members or member.bot:
                return await ctx.warn(f"**{member}** is not inside your crypt")
            await self.bot.db.execute("UPDATE vm_channels SET owner_id = ? WHERE channel_id = ?", member.id, channel.id)
            await channel.set_permissions(ctx.author, overwrite=None)
            await channel.set_permissions(member, connect=True, manage_channels=True, move_members=True)
            await ctx.approve(f"**{member}** now owns {channel.mention}")

    @voice.command(name="info")
    async def voice_info(self, ctx):
        """see who owns the crypt you are in"""
        channel = ctx.author.voice.channel if ctx.author.voice else None
        if channel is None:
            return await ctx.warn("you are not inside a crypt")
        owner_id = await self.bot.db.fetchval("SELECT owner_id FROM vm_channels WHERE channel_id = ?", channel.id)
        if owner_id is None:
            return await ctx.warn("this is not a voicemaster crypt")
        locked = channel.overwrites_for(ctx.guild.default_role).connect is False
        await ctx.send_card(ui.Card(
            ui.heading(f"🦇 {channel.name}", "a voicemaster crypt", level=3),
            ui.sep(),
            ui.lines([
                f"👑 **owner** <@{owner_id}>",
                f"👥 **souls** {len(channel.members)}/{channel.user_limit or '∞'}",
                f"{'🔒' if locked else '🔓'} **{'sealed' if locked else 'open'}**",
                f"🕯️ **opened** {discord.utils.format_dt(channel.created_at, 'R')}",
            ]),
        ))


async def setup(bot):
    await bot.add_cog(VoiceMaster(bot))
