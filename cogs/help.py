from typing import Dict, List, Mapping, Optional

import discord
from discord.ext import commands

from core import theme, ui


def usage(prefix: str, command: commands.Command) -> str:
    return f"{prefix}{command.qualified_name} {command.signature}".strip()


class HelpMenu(discord.ui.LayoutView):
    """The grimoire: a home page plus one page per category, switched with a select menu."""

    def __init__(self, help_command: "DraculaHelp", mapping: Dict[commands.Cog, List[commands.Command]]):
        super().__init__(timeout=120)
        self.help_command = help_command
        self.ctx = help_command.context
        self.mapping = mapping
        self.message: Optional[discord.Message] = None
        self.build(None)

    def _select(self, current: Optional[str]) -> discord.ui.ActionRow:
        options = [discord.SelectOption(label="home", emoji="🦇", description="back to the grimoire's cover",
                                        value="home", default=current is None)]
        for cog in self.mapping:
            emoji, description = theme.CATEGORIES[cog.qualified_name]
            options.append(discord.SelectOption(label=cog.qualified_name, emoji=emoji, description=description[:100],
                                                default=current == cog.qualified_name))
        select = discord.ui.Select(placeholder="choose a tome...", options=options)
        select.callback = self._on_select
        return discord.ui.ActionRow(select)

    def build(self, category: Optional[str], active: bool = True):
        self.clear_items()
        prefix = self.help_command.prefix
        container = discord.ui.Container(accent_colour=theme.CRIMSON)
        if category is None:
            bot = self.ctx.bot
            total = len([c for c in bot.walk_commands() if not c.hidden])
            intro = (
                "## 🦇 dracula's grimoire\n"
                "*the night is eternal, and so am i.*\n"
                f"prefix `{prefix}` • **{total}** commands • `{prefix}help <command>` for details"
            )
            container.add_item(ui.section(intro, thumbnail=bot.user.display_avatar.url if bot.user else None))
            container.add_item(ui.sep(large=True))
            container.add_item(discord.ui.TextDisplay("\n".join(
                f"{theme.CATEGORIES[c.qualified_name][0]} **{c.qualified_name}** — {theme.CATEGORIES[c.qualified_name][1]}"
                for c in self.mapping
            )))
        else:
            cog = next(c for c in self.mapping if c.qualified_name == category)
            emoji, description = theme.CATEGORIES[category]
            container.add_item(discord.ui.TextDisplay(ui.heading(f"{emoji} {category}", description)))
            container.add_item(ui.sep())
            names = []
            for command in sorted(self.mapping[cog], key=lambda c: c.qualified_name):
                names.append(f"`{command.name}`")
                if isinstance(command, commands.Group):
                    names.extend(f"`{command.name} {sub.name}`" for sub in sorted(command.commands, key=lambda c: c.name))
            container.add_item(discord.ui.TextDisplay(", ".join(names)))
        container.add_item(ui.sep())
        container.add_item(discord.ui.TextDisplay(ui.small(f"{prefix}help <command> for usage • {theme.FOOTER}")))
        if active:
            container.add_item(self._select(category))
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(view=ui.deny(interaction.user, "summon your own grimoire"), ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        self.build(None if value == "home" else value)
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        if self.message:
            self.build(None, active=False)
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class DraculaHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__(command_attrs={"help": "open the grimoire of commands", "aliases": ["h", "commands"]})

    @property
    def prefix(self) -> str:
        return self.context.clean_prefix

    async def _filtered_mapping(self, mapping) -> Dict[commands.Cog, List[commands.Command]]:
        filtered = {}
        for cog, cmds in mapping.items():
            if cog is None or cog.qualified_name not in theme.CATEGORIES:
                continue
            cmds = await self.filter_commands(cmds)
            if cmds:
                filtered[cog] = cmds
        order = list(theme.CATEGORIES)
        return dict(sorted(filtered.items(), key=lambda kv: order.index(kv[0].qualified_name)))

    async def send_bot_help(self, mapping: Mapping[Optional[commands.Cog], List[commands.Command]]):
        view = HelpMenu(self, await self._filtered_mapping(mapping))
        view.message = await self.get_destination().send(view=view)

    async def send_cog_help(self, cog: commands.Cog):
        mapping = await self._filtered_mapping(self.get_bot_mapping())
        if cog not in mapping:
            return await self.send_error_message(cog.qualified_name)
        view = HelpMenu(self, mapping)
        view.build(cog.qualified_name)
        view.message = await self.get_destination().send(view=view)

    def command_card(self, command: commands.Command) -> ui.Card:
        details = [f"```\n{usage(self.prefix, command)}\n```"]
        if command.aliases:
            details.append("**aliases** " + ", ".join(f"`{a}`" for a in command.aliases))
        category = command.cog.qualified_name if command.cog else "dracula"
        return ui.Card(
            ui.heading(f"🦇 {command.qualified_name}", category),
            command.help or "no description... only darkness",
            ui.sep(),
            "\n".join(details),
        )

    async def send_command_help(self, command: commands.Command):
        await self.get_destination().send(view=self.command_card(command).extend(ui.footer()))

    async def send_group_help(self, group: commands.Group):
        card = self.command_card(group)
        subs = await self.filter_commands(group.commands, sort=True)
        if subs:
            card.extend(
                ui.sep(),
                "**subcommands**\n" + "\n".join(f"`{usage(self.prefix, c)}` — {c.short_doc or '...'}" for c in subs),
            )
        await self.get_destination().send(view=card.extend(ui.footer()))

    async def command_not_found(self, string: str) -> str:
        return string

    async def subcommand_not_found(self, command, string: str) -> str:
        return f"{command.qualified_name} {string}"

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
