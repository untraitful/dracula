# 🦇 dracula

*the night is eternal, and so am i.*

A gothic-themed multipurpose Discord bot modelled on [bleed](https://bleed.bot): the same style of
approve / warn / deny replies, embed scripts, greetings, voicemaster, antinuke, jail and snipes,
dressed in crimson and candlelight. The default prefix is **`$`**; each server can change it.

## setup

1. Create an application at <https://discord.com/developers/applications>, add a bot, and copy its token.
2. Under **Bot → Privileged Gateway Intents**, enable **Server Members Intent** and **Message Content Intent**.
3. Install and run (Python 3.10+):

   ```sh
   pip install -r requirements.txt
   cp .env.example .env   # paste your token into DISCORD_TOKEN
   python main.py
   ```

4. Invite it with the `bot` scope and Administrator (or run `$invite` once it is online).

Data is stored in `dracula.db` (SQLite) next to the bot; set `DATABASE_PATH` to move it.

## commands

`$help` opens the grimoire with a category dropdown; `$help <command>` shows usage.
Editing a message re-runs the command, like bleed.

| category | commands |
| --- | --- |
| 🗡️ moderation | `ban` `unban` `softban` `kick` `timeout` `untimeout` `purge` (`bots` `contains` `links` `images`) `botclear` `lock` `unlock` `hide` `unhide` `slowmode` `nuke` `nickname` `warn` `warnings` `clearwarns` `removewarn` `setupjail` `jail` `unjail` `jailed` |
| 🔮 utility | `snipe` `editsnipe` `reactionsnipe` `clearsnipe` `afk` `avatar` `serveravatar` `banner` `servericon` `serverbanner` `userinfo` `serverinfo` `roleinfo` `inrole` `membercount` `firstmessage` `bots` `enlarge` `steal` `choose` `8ball` |
| 🏰 servers | `prefix` (`set` `reset`) `welcome` / `goodbye` / `boost` (`add` `remove` `list` `view` `test`) `autorole` `autoresponder` `reactionrole` `createembed` `variables` |
| 🩸 roles | `role <member> <role>` (toggle) `role create/delete/color/rename/hoist/mentionable/humans/bots/removeall` `stripstaff` `roles` |
| 🦇 voicemaster | `voicemaster setup/reset`, `voice lock/unlock/hide/reveal/rename/limit/permit/reject/claim/transfer/info` |
| 🛡️ antinuke | `antinuke` `antinuke enable/disable/threshold/punishment/whitelist` (server owner only) |
| 📜 information | `help` `ping` `uptime` `botinfo` `invite` |

## embed scripts

Greetings, autoresponders and `$createembed` accept plain text or a bleed-style embed script:

```
{embed}$v{title: welcome, {user.name}}$v{description: the night welcomes you to {guild.name}. you are our {guild.count.format} soul.}$v{color: #8a0303}$v{thumbnail: {user.avatar}}$v{content: {user.mention}}
```

Run `$variables` for every variable and part.

## examples

```
$welcome add #gate {embed}$v{description: 🦇 {user.mention} has risen}$v{color: #8a0303}
$autorole add @mortal
$ar add good morning, there are no mornings here
$timeout @someone 1h spamming
$voicemaster setup
$antinuke enable
```
