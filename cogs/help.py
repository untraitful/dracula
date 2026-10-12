from typing import List, Mapping, Optional

import discord
from discord.ext import commands

from core import theme


def usage(prefix: str, command: commands.Command) -> str:
    return f"{prefix}{command.qualified_name} {command.signature}".strip()


class CategorySelect(discord.ui.Select):
    def __init__(self, help_command: "DraculaHelp", mapping):
        self.help_command = help_command
        self.mapping = mapping
        options = []
        for cog in mapping:
            name = cog.qualified_name
            emoji, description = theme.CATEGORIES[name]
            options.append(discord.SelectOption(label=name, emoji=emoji, description=description[:100]))
        super().__init__(placeholder="choose a tome...", options=options)

    async def callback(self, interaction: discord.Interaction):
        cog = next(c for c in self.mapping if c.qualified_name == self.values[0])
        embed = self.help_command.category_embed(cog, self.mapping[cog])
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self, author_id: int, select: CategorySelect):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(f"{theme.DENY_EMOJI} summon your own grimoire", ephemeral=True)
            return False
        return True


class DraculaHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__(command_attrs={"help": "open the grimoire of commands", "aliases": ["h", "commands"]})

    @property
    def prefix(self) -> str:
        return self.context.clean_prefix

    def category_embed(self, cog: commands.Cog, cmds: List[commands.Command]) -> discord.Embed:
        emoji, description = theme.CATEGORIES.get(cog.qualified_name, ("📜", ""))
        names = []
        for command in sorted(cmds, key=lambda c: c.qualified_name):
            names.append(f"`{command.name}`")
            if isinstance(command, commands.Group):
                names.extend(f"`{command.name} {sub.name}`" for sub in sorted(command.commands, key=lambda c: c.name))
        embed = discord.Embed(color=theme.CRIMSON, title=f"{emoji} {cog.qualified_name}", description=f"*{description}*\n\n" + ", ".join(names))
        embed.set_footer(text=f"{self.prefix}help <command> for details • {theme.FOOTER}")
        return embed

    async def send_bot_help(self, mapping: Mapping[Optional[commands.Cog], List[commands.Command]]):
        filtered = {}
        for cog, cmds in mapping.items():
            if cog is None or cog.qualified_name not in theme.CATEGORIES:
                continue
            cmds = await self.filter_commands(cmds)
            if cmds:
                filtered[cog] = cmds
        order = list(theme.CATEGORIES)
        filtered = dict(sorted(filtered.items(), key=lambda kv: order.index(kv[0].qualified_name)))

        bot = self.context.bot
        total = len([c for c in bot.walk_commands() if not c.hidden])
        embed = discord.Embed(
            color=theme.CRIMSON,
            title="🦇 dracula's grimoire",
            description=(
                f"*the night is eternal, and so am i.*\n\n"
                f"prefix: `{self.prefix}` • **{total}** commands\n"
                f"use `{self.prefix}help <command>` to read a spell\n"
                f"choose a tome below to browse a category"
            ),
        )
        for cog in filtered:
            emoji, description = theme.CATEGORIES[cog.qualified_name]
            embed.add_field(name=f"{emoji} {cog.qualified_name}", value=description, inline=False)
        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.set_footer(text=theme.FOOTER)
        view = HelpView(self.context.author.id, CategorySelect(self, filtered))
        await self.get_destination().send(embed=embed, view=view)

    async def send_cog_help(self, cog: commands.Cog):
        cmds = await self.filter_commands(cog.get_commands())
        await self.get_destination().send(embed=self.category_embed(cog, cmds))

    def command_embed(self, command: commands.Command) -> discord.Embed:
        embed = discord.Embed(
            color=theme.CRIMSON,
            title=f"🦇 {command.qualified_name}",
            description=command.help or "no description... only darkness",
        )
        embed.add_field(name="usage", value=f"```{usage(self.prefix, command)}```", inline=False)
        if command.aliases:
            embed.add_field(name="aliases", value=", ".join(f"`{a}`" for a in command.aliases), inline=True)
        if command.cog:
            embed.set_footer(text=f"{command.cog.qualified_name} • {theme.FOOTER}")
        return embed

    async def send_command_help(self, command: commands.Command):
        await self.get_destination().send(embed=self.command_embed(command))

    async def send_group_help(self, group: commands.Group):
        embed = self.command_embed(group)
        subs = await self.filter_commands(group.commands, sort=True)
        if subs:
            embed.add_field(
                name="subcommands",
                value="\n".join(f"`{usage(self.prefix, c)}` — {c.short_doc or '...'}" for c in subs)[:1024],
                inline=False,
            )
        await self.get_destination().send(embed=embed)

    async def command_not_found(self, string: str) -> str:
        return string

    async def send_error_message(self, error: str):
        await self.context.warn(f"no spell named **{error}** exists in the grimoire")


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._original = bot.help_command
        bot.help_command = DraculaHelp()
        bot.help_command.cog = bot.get_cog("Information")

    async def cog_unload(self):
        self.bot.help_command = self._original


async def setup(bot):
    await bot.add_cog(Help(bot))
