import platform
import time

import discord
from discord.ext import commands

from core import theme
from core.utils import human_delta


class Information(commands.Cog):
    """about dracula itself"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # help cog loads before this one, attach it now
        if self.bot.help_command:
            self.bot.help_command.cog = self

    @commands.command(aliases=["latency"])
    async def ping(self, ctx):
        """see how fast dracula's heart beats"""
        start = time.perf_counter()
        message = await ctx.neutral(f"{theme.LOADING_EMOJI} listening for a heartbeat...")
        rest = (time.perf_counter() - start) * 1000
        await message.edit(embed=discord.Embed(
            color=theme.NEUTRAL,
            description=f"🩸 heartbeat: `{self.bot.latency * 1000:.0f}ms` • edit: `{rest:.0f}ms`",
        ))

    @commands.command(aliases=["up"])
    async def uptime(self, ctx):
        """how long dracula has walked the night"""
        from datetime import timedelta
        await ctx.neutral(f"🕰️ risen from the coffin **{human_delta(timedelta(seconds=time.time() - self.bot.started))}** ago")

    @commands.command(aliases=["bi", "about"])
    async def botinfo(self, ctx):
        """information about dracula"""
        embed = discord.Embed(
            color=theme.CRIMSON,
            title="🦇 dracula",
            description="*a gothic multipurpose bot, risen from the grave to guard your server.*",
        )
        embed.add_field(name="servers", value=f"{len(self.bot.guilds):,}")
        embed.add_field(name="members", value=f"{sum(g.member_count or 0 for g in self.bot.guilds):,}")
        embed.add_field(name="commands", value=str(len([c for c in self.bot.walk_commands() if not c.hidden])))
        embed.add_field(name="latency", value=f"{self.bot.latency * 1000:.0f}ms")
        embed.add_field(name="python", value=platform.python_version())
        embed.add_field(name="discord.py", value=discord.__version__)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=theme.FOOTER)
        await ctx.send(embed=embed)

    @commands.command(aliases=["inv"])
    async def invite(self, ctx):
        """invite dracula into another castle"""
        url = discord.utils.oauth_url(self.bot.user.id, permissions=discord.Permissions(administrator=True))
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="invite dracula", emoji="🦇", url=url))
        await ctx.neutral("🏰 open your gates to me...", view=view)


async def setup(bot):
    await bot.add_cog(Information(bot))
