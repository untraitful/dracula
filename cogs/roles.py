import asyncio

import discord
from discord.ext import commands

from core import theme
from core.utils import can_manage_role, can_moderate


class Roles(commands.Cog):
    """manage the bloodlines of your server"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    @commands.group(aliases=["r"], invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role(self, ctx, member: discord.Member, *, role: discord.Role):
        """give or take a role from a member"""
        if not await can_manage_role(ctx, role):
            return
        if member != ctx.author and ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
            return await ctx.warn(f"{member.mention}'s bloodline outranks yours")
        if role in member.roles:
            await member.remove_roles(role, reason=f"role by {ctx.author}")
            await ctx.approve(f"stripped {role.mention} from **{member}**")
        else:
            await member.add_roles(role, reason=f"role by {ctx.author}")
            await ctx.approve(f"bestowed {role.mention} upon **{member}**")

    @role.command(name="create", aliases=["make"])
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_create(self, ctx, *, name: str):
        """forge a new role"""
        role = await ctx.guild.create_role(name=name[:100], reason=f"created by {ctx.author}")
        await ctx.approve(f"a new bloodline is born: {role.mention}")

    @role.command(name="delete", aliases=["del"])
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_delete(self, ctx, *, role: discord.Role):
        """end a bloodline"""
        if not await can_manage_role(ctx, role):
            return
        name = role.name
        await role.delete(reason=f"deleted by {ctx.author}")
        await ctx.approve(f"the **{name}** bloodline has ended")

    @role.command(name="color", aliases=["colour"])
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_color(self, ctx, role: discord.Role, color: discord.Color):
        """change a role's color (hex like #8a0303)"""
        if not await can_manage_role(ctx, role):
            return
        await role.edit(color=color, reason=f"color by {ctx.author}")
        await ctx.approve(f"{role.mention} now bleeds `{color}`")

    @role.command(name="rename", aliases=["name"])
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_rename(self, ctx, role: discord.Role, *, name: str):
        """rename a role"""
        if not await can_manage_role(ctx, role):
            return
        old = role.name
        await role.edit(name=name[:100], reason=f"rename by {ctx.author}")
        await ctx.approve(f"**{old}** shall now be known as {role.mention}")

    @role.command(name="hoist")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_hoist(self, ctx, *, role: discord.Role):
        """toggle whether a role is shown separately"""
        if not await can_manage_role(ctx, role):
            return
        await role.edit(hoist=not role.hoist, reason=f"hoist by {ctx.author}")
        await ctx.approve(f"{role.mention} is {'now' if not role.hoist else 'no longer'} displayed separately")

    @role.command(name="mentionable")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_mentionable(self, ctx, *, role: discord.Role):
        """toggle whether a role can be mentioned"""
        if not await can_manage_role(ctx, role):
            return
        await role.edit(mentionable=not role.mentionable, reason=f"mentionable by {ctx.author}")
        await ctx.approve(f"{role.mention} is {'now' if not role.mentionable else 'no longer'} mentionable")

    async def _mass(self, ctx, role: discord.Role, targets, add: bool, label: str):
        if not await can_manage_role(ctx, role):
            return
        if add:
            targets = [m for m in targets if role not in m.roles]
        else:
            targets = [m for m in targets if role in m.roles]
        if not targets:
            return await ctx.warn(f"no {label} need changing")
        verb = "bestow" if add else "strip"
        if not await ctx.confirm(f"{verb} {role.mention} {'upon' if add else 'from'} **{len(targets)}** {label}?"):
            return await ctx.warn("the ritual was abandoned")
        message = await ctx.neutral(f"{theme.LOADING_EMOJI} performing the ritual on **{len(targets)}** {label}...")
        done = 0
        for member in targets:
            try:
                if add:
                    await member.add_roles(role, reason=f"mass role by {ctx.author}")
                else:
                    await member.remove_roles(role, reason=f"mass role by {ctx.author}")
                done += 1
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.5)
        await message.delete()
        await ctx.approve(f"the ritual is complete: {role.mention} {'given to' if add else 'taken from'} **{done}** {label}")

    @role.command(name="humans")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_humans(self, ctx, *, role: discord.Role):
        """give a role to every human"""
        await self._mass(ctx, role, [m for m in ctx.guild.members if not m.bot], True, "humans")

    @role.command(name="bots")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_bots(self, ctx, *, role: discord.Role):
        """give a role to every bot"""
        await self._mass(ctx, role, [m for m in ctx.guild.members if m.bot], True, "bots")

    @role.command(name="removeall", aliases=["strip"])
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_removeall(self, ctx, *, role: discord.Role):
        """take a role from everyone who has it"""
        await self._mass(ctx, role, list(role.members), False, "members")

    @commands.command(aliases=["strip"])
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def stripstaff(self, ctx, member: discord.Member):
        """strip every role with dangerous permissions from a member"""
        if not await can_moderate(ctx, member, "strip"):
            return
        dangerous = [
            r for r in member.roles
            if not r.is_default() and not r.managed and r < ctx.guild.me.top_role and (
                r.permissions.administrator or r.permissions.ban_members or r.permissions.kick_members
                or r.permissions.manage_guild or r.permissions.manage_roles or r.permissions.manage_channels
                or r.permissions.manage_messages or r.permissions.mention_everyone or r.permissions.moderate_members
            )
        ]
        if not dangerous:
            return await ctx.warn(f"**{member}** wields no dangerous roles")
        await member.remove_roles(*dangerous, reason=f"stripstaff by {ctx.author}")
        await ctx.approve(f"stripped **{len(dangerous)}** roles of power from **{member}**")

    @commands.command()
    async def roles(self, ctx):
        """list every role in the server"""
        roles = [r for r in reversed(ctx.guild.roles) if not r.is_default()]
        await ctx.paginate([f"{r.mention} (`{r.id}`) — {len(r.members)} members" for r in roles], f"bloodlines of {ctx.guild.name}")


async def setup(bot):
    await bot.add_cog(Roles(bot))
