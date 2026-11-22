"""Discord command handlers, kept free of discord.py so they test offline with fake interactions.

The bot is only the front door (docs/BOT_ARCHITECTURE.md): check who asked, validate input, defer,
run the tool in its own process, post the result. No analysis happens here.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

from tools.token_scanner import token_scanner as ts

ROOT = Path(__file__).resolve().parents[1]
SCAN_TIMEOUT_S = 120
DISCORD_LIMIT = 4000  # embed description limit is 4096

_locks = {}


def _one_job():
    """One tool process at a time. Created per event loop (Python 3.9 locks bind to the loop that made them)."""
    loop = asyncio.get_running_loop()
    if loop not in _locks:
        _locks.clear()
        _locks[loop] = asyncio.Lock()
    return _locks[loop]


class Config:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        ids = lambda k: {int(x) for x in env.get(k, "").replace(" ", "").split(",") if x.isdigit()}
        self.allowed_users = ids("DISCORD_ALLOWED_USER_IDS")
        self.allowed_roles = ids("DISCORD_ALLOWED_ROLE_IDS")
        self.guild_id = int(env["DISCORD_GUILD_ID"]) if env.get("DISCORD_GUILD_ID", "").isdigit() else None

    def allowed(self, user):
        """Deny by default: with no allow-list configured, nobody can run commands."""
        if user is None:
            return False
        if user.id in self.allowed_users:
            return True
        roles = {r.id for r in (getattr(user, "roles", None) or [])}
        return bool(roles & self.allowed_roles)


async def run_scanner(mint, timeout=SCAN_TIMEOUT_S, env=None, argv=None):
    """Run the scanner CLI in a subprocess. Returns (exit_code, stdout, stderr); exit_code None on timeout."""
    argv = argv or [sys.executable, "-m", "tools.token_scanner.cli", mint, "--text"]
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None, "", "timed out after {} s".format(timeout)
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def format_result(mint, code, out, err):
    """Map the tool's exit code to a message. Never invent content: failures say what failed."""
    if code == 0 and out.strip():
        text = out.strip()
    elif code == 2:
        text = "Not a valid Solana address: `{}`".format(mint[:60])
    elif code == 3:
        text = "Scan of `{}` fetched nothing (all sources failed or are paused).\n{}".format(
            mint, (out.strip() or err.strip())[-1500:])
    elif code is None:
        text = "Scan of `{}` stopped: {}.".format(mint, err.strip())
    else:
        last = err.strip().splitlines()[-1:] or ["no error output"]
        text = "Scan of `{}` failed (exit {}): {}".format(mint, code, last[0][:500])
    return text if len(text) <= DISCORD_LIMIT else text[:DISCORD_LIMIT - 15] + "\n…(truncated)"


async def handle_scan(interaction, mint, cfg, runner=run_scanner, send_text=None):
    """/scan <mint>. interaction needs .user, .response.defer(ephemeral=..), .followup.send(..)."""
    if not cfg.allowed(interaction.user):
        await interaction.response.send_message("You are not on this bot's allow-list.", ephemeral=True)
        return "denied"
    mint = (mint or "").strip()
    if not ts.valid_mint(mint):
        await interaction.response.send_message("Not a valid Solana address: `{}`".format(mint[:60]), ephemeral=True)
        return "invalid"
    await interaction.response.defer(thinking=True)  # 3 s -> 15 min to answer
    lock = _one_job()
    busy = lock.locked()
    async with lock:
        code, out, err = await runner(mint)
    text = format_result(mint, code, out, err)
    if busy:
        text = "(waited for an earlier scan to finish)\n" + text
    await (send_text or interaction.followup.send)(text)
    return "ok" if code == 0 else "failed"


def status_text(started_at, raw_dir=None):
    raw = Path(raw_dir or os.environ.get("RKD_RAW") or ROOT / "data" / "raw")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    usage = raw / "usage_token_scanner_{}.json".format(day)
    calls = "0"
    if usage.exists():
        import json
        try:
            calls = str(json.loads(usage.read_text(encoding="utf-8")).get("calls", "?"))
        except ValueError:
            calls = "unreadable"
    return ("Bot up since <t:{}:R>. Scanner v{}. API calls today (UTC {}): {} of {}. Helius key: {}.".format(
        int(started_at), ts.VERSION, day, calls, os.environ.get("RKD_SCANNER_DAILY_BUDGET", "300"),
        "set" if os.environ.get("HELIUS_API_KEY") else "MISSING"))
