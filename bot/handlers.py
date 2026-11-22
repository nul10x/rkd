"""Discord command handlers, kept free of discord.py so they test offline with fake interactions.

The bot is only the front door (docs/BOT_ARCHITECTURE.md): check who asked, validate input, defer,
run the tool in its own process, post the result. No analysis happens here.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from tools.token_scanner import token_scanner as ts

ROOT = Path(__file__).resolve().parents[1]
SCAN_TIMEOUT_S = 120
DISCORD_LIMIT = 1900  # plain message content is capped at 2000 chars by Discord; keep a margin
MAX_MESSAGES = 3      # a long report is split on line breaks into at most this many messages

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


def failure_reasons(out):
    """The 'missing' reasons from the tool output (JSON or --text), without paths or raw data."""
    out = (out or "").strip()
    try:
        rep = json.loads(out)
        items = ["{}: {}".format(m.get("field"), m.get("reason")) for m in rep.get("missing") or []]
    except ValueError:
        lines = out.splitlines()
        start = next((i for i, l in enumerate(lines) if l.startswith("**Missing")), None)
        items = [l[2:] for l in lines[start + 1:] if l.startswith("- ")] if start is not None else []
        items = [i for i in items if not i.startswith("Sources")]
    return items


def split_message(text, limit=DISCORD_LIMIT, max_parts=MAX_MESSAGES):
    """Split on line breaks into parts of at most `limit` chars; the last part is cut if needed."""
    parts, cur = [], ""
    for line in text.splitlines():
        while len(line) > limit:  # a single over-long line
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur or not parts:
        parts.append(cur)
    if len(parts) > max_parts:
        parts = parts[:max_parts]
        tail = "\n…(truncated; full report saved in data/exports/token_scanner/)"
        parts[-1] = parts[-1][:limit - len(tail)] + tail
    return parts


def format_result(mint, code, out, err):
    """Map the tool's exit code to a message. Never invent content: failures say what failed.
    Returns a list of Discord-sized messages."""
    if code == 0 and out.strip():
        text = out.strip()
    elif code == 2:
        text = "Not a valid Solana address: `{}`".format(mint[:60])
    elif code == 3:
        reasons = failure_reasons(out) or ["no reason reported"]
        text = "Scan of `{}` fetched nothing (all sources failed or are paused):\n{}".format(
            mint, "\n".join("- " + r[:300] for r in reasons[:10]))
    elif code is None:
        text = "Scan of `{}` stopped: {}.".format(mint, err.strip())
    else:
        last = err.strip().splitlines()[-1:] or ["no error output"]
        text = "Scan of `{}` failed (exit {}): {}".format(mint, code, last[0][:500])
    return split_message(text)


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
    parts = format_result(mint, code, out, err)
    if busy:
        parts = split_message("(waited for an earlier scan to finish)\n" + "\n".join(parts))
    send = send_text or interaction.followup.send
    for part in parts:
        await send(part)
    return "ok" if code == 0 else "failed"


def status_text(started_at, raw_dir=None):
    raw = Path(raw_dir or os.environ.get("RKD_RAW") or ROOT / "data" / "raw")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    usage = raw / "usage_token_scanner_{}.json".format(day)
    calls = "0"
    if usage.exists():
        try:
            calls = str(json.loads(usage.read_text(encoding="utf-8")).get("calls", "?"))
        except ValueError:
            calls = "unreadable"
    return ("Bot up since <t:{}:R>. Scanner v{}. API calls today (UTC {}): {} of {}. Helius key: {}.".format(
        int(started_at), ts.VERSION, day, calls, os.environ.get("RKD_SCANNER_DAILY_BUDGET", "300"),
        "set" if os.environ.get("HELIUS_API_KEY") else "MISSING"))
