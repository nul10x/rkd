"""RKD Discord bot: the front door for tools. Run with the bot venv:  ~/.rkd/bot-venv/bin/python -m bot.main

Commands (registered to one server only): /scan <mint>, /status.
Settings come from the environment, or from a git-ignored env file named by RKD_BOT_ENV_FILE (KEY=VALUE lines):
  DISCORD_BOT_TOKEN          required, never logged
  DISCORD_GUILD_ID           required: the server to register commands in
  DISCORD_ALLOWED_USER_IDS   comma-separated user ids allowed to run commands
  DISCORD_ALLOWED_ROLE_IDS   comma-separated role ids allowed to run commands (deny by default)
  HELIUS_API_KEY             for the on-chain parts of /scan
  HELIUS_API_KEY_FILE, DISCORD_BOT_TOKEN_FILE   alternative: path of a file holding the secret
A lock file (~/.rkd/bot.lock) makes a second copy exit instead of double-replying.
"""
import os
import sys
import time
from pathlib import Path

from bot import handlers

def lock_path(env=None):
    """Read at call time, after RKD_BOT_ENV_FILE is loaded, so RKD_BOT_LOCK in that file applies."""
    env = os.environ if env is None else env
    return Path(env.get("RKD_BOT_LOCK") or str(Path.home() / ".rkd" / "bot.lock"))


def load_env_file(path, env=None):
    """KEY=VALUE lines; '#' comments; existing environment values win."""
    env = os.environ if env is None else env
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def load_key_files(env=None):
    """<NAME>_FILE points at a file holding the secret (e.g. an OpenBot vault file); the value is never logged."""
    env = os.environ if env is None else env
    for name in ("HELIUS_API_KEY", "DISCORD_BOT_TOKEN"):
        f = env.get(name + "_FILE")
        if f and not env.get(name) and Path(f).exists():
            env[name] = Path(f).read_text(encoding="utf-8").strip()
    return env


def take_lock(path=None):
    """Exclusive, released by the OS when the process dies. Returns the open file or None if held."""
    path = Path(path) if path else lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def build_client(cfg):
    import discord
    from discord import app_commands

    intents = discord.Intents.none()
    intents.guilds = True  # needed to see the member's roles for the allow-list
    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())
    tree = app_commands.CommandTree(client)
    guild = discord.Object(id=cfg.guild_id)
    started = time.time()

    @tree.command(name="scan", description="Facts and risk flags for a Solana token (read-only, not advice)",
                  guild=guild)
    @app_commands.describe(mint="Token mint address")
    async def scan(interaction: discord.Interaction, mint: str):
        await handlers.handle_scan(interaction, mint, cfg)

    @tree.command(name="status", description="Bot uptime and today's API usage", guild=guild)
    async def status(interaction: discord.Interaction):
        if not cfg.allowed(interaction.user):
            await interaction.response.send_message("You are not on this bot's allow-list.", ephemeral=True)
            return
        await interaction.response.send_message(handlers.status_text(started), ephemeral=True)

    @client.event
    async def setup_hook():
        await tree.sync(guild=guild)  # server-only registration: instant, no global commands

    @client.event
    async def on_ready():
        print("ready as {} in guild {}".format(client.user, cfg.guild_id), flush=True)

    return client


def main():
    if os.environ.get("RKD_BOT_ENV_FILE"):
        load_env_file(os.environ["RKD_BOT_ENV_FILE"])
    load_key_files()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    cfg = handlers.Config()
    if not token or not cfg.guild_id:
        print("DISCORD_BOT_TOKEN and DISCORD_GUILD_ID must be set", file=sys.stderr)
        return 2
    if not (cfg.allowed_users or cfg.allowed_roles):
        print("warning: no DISCORD_ALLOWED_USER_IDS / _ROLE_IDS set; every command will be refused", file=sys.stderr)
    lock = take_lock()
    if lock is None:
        print("another bot instance holds {}; exiting".format(lock_path()), file=sys.stderr)
        return 0
    build_client(cfg).run(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
