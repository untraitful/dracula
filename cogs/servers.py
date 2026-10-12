import discord
from discord.ext import commands

from core import theme
from core.scripting import VARIABLE_HELP, send_script
from core.utils import can_manage_role

GREETING_WORDS = {
    "welcome": "welcome",
    "goodbye": "farewell",
    "boost": "boost",
}


class Servers(commands.Cog):
    """configure the castle: prefix, greetings, autoroles and more"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # --------------------------------------------------------------- prefix

    @commands.group(invoke_without_command=True)
    async def prefix(self, ctx):
        """view the server's prefix"""
        current = self.bot.prefixes.get(ctx.guild.id, "$")
        await ctx.neutral(f"🕯️ this castle answers to `{current}`")

    @prefix.command(name="set")
    @commands.has_permissions(manage_guild=True)
    async def prefix_set(self, ctx, prefix: str):
        """change the server's prefix"""
        if len(prefix) > 10:
            return await ctx.warn("a prefix cannot be longer than **10** characters")
        self.bot.prefixes[ctx.guild.id] = prefix
        await self.bot.db.execute("INSERT OR REPLACE INTO prefixes (guild_id, prefix) VALUES (?, ?)", ctx.guild.id, prefix)
        await ctx.approve(f"this castle now answers to `{prefix}`")

    @prefix.command(name="reset", aliases=["remove"])
    @commands.has_permissions(manage_guild=True)
    async def prefix_reset(self, ctx):
        """reset the prefix back to `$`"""
        self.bot.prefixes.pop(ctx.guild.id, None)
        await self.bot.db.execute("DELETE FROM prefixes WHERE guild_id = ?", ctx.guild.id)
        await ctx.approve("the prefix has returned to `$`")

    # ------------------------------------------------------------ greetings

    async def _greet_add(self, ctx, kind: str, channel: discord.TextChannel, message: str):
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO greetings (guild_id, kind, channel_id, message) VALUES (?, ?, ?, ?)",
            ctx.guild.id, kind, channel.id, message,
        )
        await ctx.approve(f"{GREETING_WORDS[kind]} messages will now be sent in {channel.mention}")

    async def _greet_remove(self, ctx, kind: str, channel: discord.TextChannel):
        removed = await self.bot.db.execute(
            "DELETE FROM greetings WHERE guild_id = ? AND kind = ? AND channel_id = ?", ctx.guild.id, kind, channel.id
        )
        if not removed:
            return await ctx.warn(f"no {GREETING_WORDS[kind]} message is set for {channel.mention}")
        await ctx.approve(f"the {GREETING_WORDS[kind]} message in {channel.mention} has been buried")

    async def _greet_list(self, ctx, kind: str):
        rows = await self.bot.db.fetchall("SELECT channel_id FROM greetings WHERE guild_id = ? AND kind = ?", ctx.guild.id, kind)
        await ctx.paginate([f"<#{r['channel_id']}>" for r in rows], f"{GREETING_WORDS[kind]} channels")

    async def _greet_view(self, ctx, kind: str, channel: discord.TextChannel):
        message = await self.bot.db.fetchval(
            "SELECT message FROM greetings WHERE guild_id = ? AND kind = ? AND channel_id = ?", ctx.guild.id, kind, channel.id
        )
        if message is None:
            return await ctx.warn(f"no {GREETING_WORDS[kind]} message is set for {channel.mention}")
        await ctx.neutral(f"```\n{discord.utils.escape_markdown(message)[:4000]}\n```")

    async def _greet_test(self, ctx, kind: str):
        rows = await self.bot.db.fetchall("SELECT channel_id, message FROM greetings WHERE guild_id = ? AND kind = ?", ctx.guild.id, kind)
        if not rows:
            return await ctx.warn(f"no {GREETING_WORDS[kind]} messages are set")
        for row in rows:
            channel = ctx.guild.get_channel(row["channel_id"])
            if channel:
                await send_script(channel, row["message"], ctx.author)
        await ctx.approve(f"summoned **{len(rows)}** {GREETING_WORDS[kind]} message(s)")

    @commands.group(aliases=["welc"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def welcome(self, ctx):
        """greet new souls as they enter — supports variables and embed scripts"""
        await ctx.send_help(ctx.command)

    @welcome.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def welcome_add(self, ctx, channel: discord.TextChannel, *, message: str):
        """set a welcome message for a channel"""
        await self._greet_add(ctx, "welcome", channel, message)

    @welcome.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def welcome_remove(self, ctx, channel: discord.TextChannel):
        """remove a channel's welcome message"""
        await self._greet_remove(ctx, "welcome", channel)

    @welcome.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def welcome_list(self, ctx):
        """list welcome channels"""
        await self._greet_list(ctx, "welcome")

    @welcome.command(name="view")
    @commands.has_permissions(manage_guild=True)
    async def welcome_view(self, ctx, channel: discord.TextChannel):
        """view a channel's raw welcome message"""
        await self._greet_view(ctx, "welcome", channel)

    @welcome.command(name="test")
    @commands.has_permissions(manage_guild=True)
    async def welcome_test(self, ctx):
        """send every welcome message as if you just joined"""
        await self._greet_test(ctx, "welcome")

    @commands.group(aliases=["bye", "farewell"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def goodbye(self, ctx):
        """mourn souls as they leave — supports variables and embed scripts"""
        await ctx.send_help(ctx.command)

    @goodbye.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def goodbye_add(self, ctx, channel: discord.TextChannel, *, message: str):
        """set a goodbye message for a channel"""
        await self._greet_add(ctx, "goodbye", channel, message)

    @goodbye.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def goodbye_remove(self, ctx, channel: discord.TextChannel):
        """remove a channel's goodbye message"""
        await self._greet_remove(ctx, "goodbye", channel)

    @goodbye.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def goodbye_list(self, ctx):
        """list goodbye channels"""
        await self._greet_list(ctx, "goodbye")

    @goodbye.command(name="view")
    @commands.has_permissions(manage_guild=True)
    async def goodbye_view(self, ctx, channel: discord.TextChannel):
        """view a channel's raw goodbye message"""
        await self._greet_view(ctx, "goodbye", channel)

    @goodbye.command(name="test")
    @commands.has_permissions(manage_guild=True)
    async def goodbye_test(self, ctx):
        """send every goodbye message as if you just left"""
        await self._greet_test(ctx, "goodbye")

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def boost(self, ctx):
        """thank members who boost — supports variables and embed scripts"""
        await ctx.send_help(ctx.command)

    @boost.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def boost_add(self, ctx, channel: discord.TextChannel, *, message: str):
        """set a boost message for a channel"""
        await self._greet_add(ctx, "boost", channel, message)

    @boost.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def boost_remove(self, ctx, channel: discord.TextChannel):
        """remove a channel's boost message"""
        await self._greet_remove(ctx, "boost", channel)

    @boost.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def boost_list(self, ctx):
        """list boost channels"""
        await self._greet_list(ctx, "boost")

    @boost.command(name="view")
    @commands.has_permissions(manage_guild=True)
    async def boost_view(self, ctx, channel: discord.TextChannel):
        """view a channel's raw boost message"""
        await self._greet_view(ctx, "boost", channel)

    @boost.command(name="test")
    @commands.has_permissions(manage_guild=True)
    async def boost_test(self, ctx):
        """send every boost message as if you just boosted"""
        await self._greet_test(ctx, "boost")

    # ------------------------------------------------------------ autorole

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def autorole(self, ctx):
        """give roles to new members automatically"""
        await ctx.send_help(ctx.command)

    @autorole.command(name="add")
    @commands.has_permissions(manage_roles=True)
    async def autorole_add(self, ctx, *, role: discord.Role):
        """add an autorole"""
        if not await can_manage_role(ctx, role):
            return
        if role.permissions.administrator or role.permissions.ban_members or role.permissions.manage_guild:
            return await ctx.warn(f"{role.mention} holds dangerous powers and cannot be an autorole")
        await self.bot.db.execute("INSERT OR IGNORE INTO autoroles (guild_id, role_id) VALUES (?, ?)", ctx.guild.id, role.id)
        await ctx.approve(f"new souls will now receive {role.mention}")

    @autorole.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def autorole_remove(self, ctx, *, role: discord.Role):
        """remove an autorole"""
        removed = await self.bot.db.execute("DELETE FROM autoroles WHERE guild_id = ? AND role_id = ?", ctx.guild.id, role.id)
        if not removed:
            return await ctx.warn(f"{role.mention} is not an autorole")
        await ctx.approve(f"{role.mention} is no longer an autorole")

    @autorole.command(name="list")
    @commands.has_permissions(manage_roles=True)
    async def autorole_list(self, ctx):
        """list autoroles"""
        rows = await self.bot.db.fetchall("SELECT role_id FROM autoroles WHERE guild_id = ?", ctx.guild.id)
        await ctx.paginate([f"<@&{r['role_id']}>" for r in rows], "autoroles")

    # ------------------------------------------------------- autoresponder

    @commands.group(aliases=["ar"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def autoresponder(self, ctx):
        """reply automatically when a trigger is said"""
        await ctx.send_help(ctx.command)

    @autoresponder.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def autoresponder_add(self, ctx, *, text: str):
        """add an autoresponder: `trigger, response`"""
        if "," not in text:
            return await ctx.warn(f"separate the trigger and response with a comma: `{ctx.clean_prefix}ar add hello, good evening`")
        trigger, response = (part.strip() for part in text.split(",", 1))
        if not trigger or not response:
            return await ctx.warn("both a trigger and a response are required")
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO autoresponders (guild_id, trigger, response) VALUES (?, ?, ?)",
            ctx.guild.id, trigger.lower(), response,
        )
        self.bot.dispatch("autoresponders_changed", ctx.guild.id)
        await ctx.approve(f"i will now answer **{trigger}**")

    @autoresponder.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def autoresponder_remove(self, ctx, *, trigger: str):
        """remove an autoresponder"""
        removed = await self.bot.db.execute(
            "DELETE FROM autoresponders WHERE guild_id = ? AND trigger = ?", ctx.guild.id, trigger.lower()
        )
        if not removed:
            return await ctx.warn(f"no autoresponder for **{trigger}** exists")
        self.bot.dispatch("autoresponders_changed", ctx.guild.id)
        await ctx.approve(f"i will no longer answer **{trigger}**")

    @autoresponder.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def autoresponder_list(self, ctx):
        """list autoresponders"""
        rows = await self.bot.db.fetchall("SELECT trigger, response FROM autoresponders WHERE guild_id = ?", ctx.guild.id)
        await ctx.paginate([f"**{r['trigger']}** → {r['response'][:60]}" for r in rows], "autoresponders")

    # --------------------------------------------------------- reactionrole

    @commands.group(aliases=["rr"], invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def reactionrole(self, ctx):
        """give roles when members react to a message"""
        await ctx.send_help(ctx.command)

    @reactionrole.command(name="add")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, add_reactions=True)
    async def reactionrole_add(self, ctx, message: discord.Message, emoji: str, *, role: discord.Role):
        """bind an emoji on a message to a role"""
        if message.guild != ctx.guild:
            return await ctx.warn("that message lies in another castle")
        if not await can_manage_role(ctx, role):
            return
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            return await ctx.warn(f"i cannot react with **{emoji}**")
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO reactionroles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)",
            ctx.guild.id, message.channel.id, message.id, emoji, role.id,
        )
        await ctx.approve(f"reacting with {emoji} on [that message]({message.jump_url}) now grants {role.mention}")

    @reactionrole.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_remove(self, ctx, message: discord.Message, emoji: str):
        """unbind an emoji from a message"""
        removed = await self.bot.db.execute("DELETE FROM reactionroles WHERE message_id = ? AND emoji = ?", message.id, emoji)
        if not removed:
            return await ctx.warn("no reaction role is bound there")
        await ctx.approve(f"{emoji} on that message no longer grants a role")

    @reactionrole.command(name="list")
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_list(self, ctx):
        """list reaction roles"""
        rows = await self.bot.db.fetchall(
            "SELECT channel_id, message_id, emoji, role_id FROM reactionroles WHERE guild_id = ?", ctx.guild.id
        )
        lines = [
            f"{r['emoji']} → <@&{r['role_id']}> on [message](https://discord.com/channels/{ctx.guild.id}/{r['channel_id']}/{r['message_id']})"
            for r in rows
        ]
        await ctx.paginate(lines, "reaction roles")

    # --------------------------------------------------------------- embeds

    @commands.command(aliases=["ce", "embed"])
    @commands.has_permissions(manage_messages=True)
    async def createembed(self, ctx, *, script: str):
        """send an embed from a script — see `$variables`"""
        sent = await send_script(ctx.channel, script, ctx.author)
        if sent is None:
            await ctx.warn("that script summoned nothing")

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
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Servers(bot))
