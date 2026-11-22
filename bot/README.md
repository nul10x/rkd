# RKD Discord bot

The front door for RKD tools (design: `docs/BOT_ARCHITECTURE.md`). It checks who asked, validates the
input, defers the reply, runs the tool as a separate process, and posts the result. No analysis in the bot.
Read-only: no trading, no wallets.

## Commands (registered to one server only)
- `/scan mint:<address>`: runs `tools/token_scanner` and posts facts and risk flags (see its README).
  One scan at a time; others wait their turn. 120 s timeout per scan.
- `/status`: uptime, scanner version, today's API calls against the daily budget, whether the Helius key is set.

## Safety
- Deny by default: only user ids in `DISCORD_ALLOWED_USER_IDS` or members with a role in
  `DISCORD_ALLOWED_ROLE_IDS` can run commands. Refusals are private (ephemeral).
- All mentions are turned off, so no output can ping @everyone, roles or users.
- Inputs are validated as base58 addresses before anything runs.
- The token is read from a key file named in the env file. It is never in the repo, the Logbook or logs.
- A lock file (`~/.rkd/bot.lock`) makes a second copy exit, so replies never double.
- Tool processes get the bot's environment minus `DISCORD_BOT_TOKEN` and `DISCORD_BOT_TOKEN_FILE`.
- Failure details (provider error bodies, local paths, stderr) never go to the channel. The channel gets
  a short status line; the caller gets the details privately (ephemeral), and the bot log keeps them.

## Setup (macOS)
1. Discord Developer Portal → New Application → Bot → copy the token. Under OAuth2 → URL Generator pick
   scopes `bot` and `applications.commands`, permission "Send Messages", and invite it to your server.
   No privileged intents are needed.
2. `python3 -m venv ~/.rkd/bot-venv && ~/.rkd/bot-venv/bin/pip install -r bot/requirements.txt`
3. Copy `bot/bot.env.example` to `~/.rkd/bot.env`, `chmod 600`, and fill in the server id, your user id and
   the key-file paths.
4. Test in the foreground: `RKD_BOT_ENV_FILE=~/.rkd/bot.env ~/.rkd/bot-venv/bin/python -m bot.main`
5. Supervise: fill in `bot/launchd/com.rkd.discordbot.plist.template`, copy it to
   `~/Library/LaunchAgents/com.rkd.discordbot.plist`, then
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.rkd.discordbot.plist`.
   Stop: `launchctl bootout gui/$(id -u)/com.rkd.discordbot`. Log: the `StandardOutPath` file.

Windows: same venv steps with `py`; supervise with Task Scheduler ("At log on", "Restart on failure").
Not tested on Windows yet.

While the laptop sleeps the bot is offline and commands fail in Discord. It reconnects on wake.

## Tests
`python3 -m unittest bot.tests.test_bot` (stdlib only; discord.py is not needed): allow-lists, invalid
input, defer-then-follow-up, one-at-a-time, a real child process on recorded fixtures, timeout kill,
env and key files, the single-instance lock. The live Discord connection is checked by hand once per release.

## Version history
- 0.1.1 (2026-11-22): bot token kept out of tool processes; failure details private (Security Reviewer, 2 Low).
- 0.1.0 (2026-11-22): `/scan`, `/status`.
