import platform
import time
from datetime import timedelta

import discord
from discord.ext import commands

from core import theme, ui
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
        await message.edit(view=ui.Card(
            f"🩸 heartbeat `{self.bot.latency * 1000:.0f}ms` • reply `{rest:.0f}ms`",
            accent=theme.NEUTRAL,
        ))

    @commands.command(aliases=["up"])
    async def uptime(self, ctx):
        """how long dracula has walked the night"""
        risen = human_delta(timedelta(seconds=time.time() - self.bot.started))
        await ctx.neutral(f"🕰️ risen from the coffin **{risen}** ago (<t:{int(self.bot.started)}:R>)")

    @commands.command(aliases=["bi", "about"])
    async def botinfo(self, ctx):
        """information about dracula"""
        members = sum(g.member_count or 0 for g in self.bot.guilds)
        commands_count = len([c for c in self.bot.walk_commands() if not c.hidden])
        url = discord.utils.oauth_url(self.bot.user.id, permissions=discord.Permissions(administrator=True))
        await ctx.send_card(ui.Card(
            ui.section(
                "## 🦇 dracula\n*a gothic multipurpose bot, risen from the grave to guard your server.*",
                thumbnail=self.bot.user.display_avatar.url,
            ),
            ui.sep(large=True),
            ui.lines([
                f"🏰 **{len(self.bot.guilds):,}** servers • 👥 **{members:,}** souls • 📜 **{commands_count}** commands",
                f"🩸 heartbeat `{self.bot.latency * 1000:.0f}ms` • risen <t:{int(self.bot.started)}:R>",
                f"🐍 python `{platform.python_version()}` • discord.py `{discord.__version__}`",
            ]),
            discord.ui.ActionRow(ui.link("invite dracula", url, "🦇")),
            ui.footer(),
        ))

    @commands.command(aliases=["inv"])
    async def invite(self, ctx):
        """invite dracula into another castle"""
        url = discord.utils.oauth_url(self.bot.user.id, permissions=discord.Permissions(administrator=True))
        await ctx.send_card(ui.Card(
            ui.section("🏰 open your gates to me...", button=ui.link("invite", url, "🦇")),
            accent=theme.NEUTRAL,
        ))


async def setup(bot):
    await bot.add_cog(Information(bot))
