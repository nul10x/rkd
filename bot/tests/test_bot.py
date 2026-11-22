"""Bot tests: thin handlers driven by fake interactions; one real subprocess run on offline fixtures."""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot import handlers, main

GRAD = "FiVRbrKNxzVotLBc8QMrhEJSK9qtF3uu5QkY3GcHpump"
FX = Path(__file__).resolve().parents[2] / "tools" / "token_scanner" / "tests" / "fixtures" / "graduate"


class Role:
    def __init__(self, i):
        self.id = i


class User:
    def __init__(self, i, roles=()):
        self.id = i
        self.roles = [Role(r) for r in roles]


class Interaction:
    def __init__(self, user):
        self.user = user
        self.log = []
        self.response = self
        self.followup = self

    async def send_message(self, text, ephemeral=False):
        self.log.append(("message", text, ephemeral))

    async def defer(self, thinking=False, ephemeral=False):
        self.log.append(("defer",))

    async def send(self, text, ephemeral=False):
        if ephemeral:
            self.log.append(("private", text))
            return
        if len(text) > 2000:  # what Discord does: HTTP 400, code 50035
            raise RuntimeError("400 Bad Request (error code: 50035): content must be 2000 or fewer in length")
        self.log.append(("followup", text))


def cfg(**env):
    return handlers.Config(env)


async def fake_runner(mint):
    return 0, "**Scan** `{}`\nfacts".format(mint), ""


class ConfigTest(unittest.TestCase):
    def test_deny_by_default_and_allow_lists(self):
        self.assertFalse(cfg().allowed(User(1)))
        c = cfg(DISCORD_ALLOWED_USER_IDS="1, 2", DISCORD_ALLOWED_ROLE_IDS="77", DISCORD_GUILD_ID="5")
        self.assertTrue(c.allowed(User(2)))
        self.assertTrue(c.allowed(User(9, roles=[77])))
        self.assertFalse(c.allowed(User(9, roles=[78])))
        self.assertFalse(c.allowed(None))
        self.assertEqual(c.guild_id, 5)


class HandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_denied_user_gets_ephemeral_refusal_and_no_run(self):
        called = []

        async def runner(m):
            called.append(m)
            return 0, "x", ""
        i = Interaction(User(9))
        self.assertEqual(await handlers.handle_scan(i, GRAD, cfg(DISCORD_ALLOWED_USER_IDS="1"), runner), "denied")
        self.assertEqual(called, [])
        self.assertTrue(i.log[0][2])

    async def test_invalid_mint_rejected_before_defer(self):
        i = Interaction(User(1))
        r = await handlers.handle_scan(i, "hello @everyone", cfg(DISCORD_ALLOWED_USER_IDS="1"), fake_runner)
        self.assertEqual(r, "invalid")
        self.assertEqual(i.log[0][0], "message")

    async def test_defer_then_followup(self):
        i = Interaction(User(1))
        self.assertEqual(await handlers.handle_scan(i, GRAD, cfg(DISCORD_ALLOWED_USER_IDS="1"), fake_runner), "ok")
        self.assertEqual([e[0] for e in i.log], ["defer", "followup"])
        self.assertIn(GRAD, i.log[1][1])

    async def test_scans_run_one_at_a_time(self):
        running, peak = [0], [0]

        async def slow(m):
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            await asyncio.sleep(0.05)
            running[0] -= 1
            return 0, "done", ""
        c = cfg(DISCORD_ALLOWED_USER_IDS="1")
        a, b = Interaction(User(1)), Interaction(User(1))
        await asyncio.gather(handlers.handle_scan(a, GRAD, c, slow), handlers.handle_scan(b, GRAD, c, slow))
        self.assertEqual(peak[0], 1)
        self.assertTrue(any("waited" in e[1] for e in a.log + b.log if e[0] == "followup"))

    async def test_real_subprocess_on_fixtures(self):
        """End to end through a real child process, offline: the CLI replays recorded responses."""
        d = tempfile.mkdtemp()
        env = dict(os.environ, RKD_EXPORTS=d)

        async def runner(m):
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "tools.token_scanner.cli", m, "--text", "--fixtures", str(FX),
                cwd=str(handlers.ROOT), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            return proc.returncode, out.decode(), err.decode()
        i = Interaction(User(1))
        self.assertEqual(await handlers.handle_scan(i, GRAD, cfg(DISCORD_ALLOWED_USER_IDS="1"), runner), "ok")
        text = i.log[-1][1]
        self.assertIn("Risk flags", text)
        self.assertIn("creation slot", text)
        self.assertLessEqual(len(text), 4096)

    async def test_timeout_kills_child_and_reports_stop(self):
        t = asyncio.get_running_loop().time()
        code, out, err = await handlers.run_scanner(GRAD, timeout=0.5,
                                                    argv=[sys.executable, "-c", "import time; time.sleep(30)"])
        self.assertLess(asyncio.get_running_loop().time() - t, 10)
        self.assertIsNone(code)
        self.assertIn("stopped (timeout)", handlers.format_result(GRAD, code, out, err)[0])
        self.assertIn("timed out after 0.5 s", handlers.private_detail(code, out, err)[0])


class FormatTest(unittest.TestCase):
    def test_exit_codes(self):
        self.assertIn("Not a valid", handlers.format_result("x", 2, "", "")[0])
        self.assertIn("fetched nothing", handlers.format_result(GRAD, 3, "", "all paused")[0])
        self.assertIn("failed (exit 1)", handlers.format_result(GRAD, 1, "", "Traceback\nKeyError: 'x'")[0])
        self.assertIn("KeyError: 'x'", handlers.private_detail(1, "", "Traceback\nKeyError: 'x'")[0])
        parts = handlers.format_result(GRAD, 0, "a" * 9000, "")
        self.assertLessEqual(len(parts), handlers.MAX_MESSAGES)
        self.assertTrue(all(len(x) <= 2000 for x in parts))

    def test_review_1_every_message_fits_discord_content_limit(self):
        """Regression (review finding 1): 2001-3900 char reports raised HTTP 400 50035 in followup.send."""
        report = "\n".join("- [fact] line {} ".format(i) + "x" * 60 for i in range(30))  # ~2400 chars
        self.assertGreater(len(report), 2000)
        parts = handlers.format_result(GRAD, 0, report, "")
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(x) <= 2000 for x in parts), [len(x) for x in parts])
        self.assertEqual("\n".join(parts), report)  # nothing lost when it fits in MAX_MESSAGES

    def test_review_5_exit_3_posts_reasons_not_paths(self):
        """Regression (review finding 5): exit 3 posted the JSON tail with local raw paths."""
        rep = {"missing": [{"field": "market", "reason": "not fetched: RateLimited: dexscreener paused"}],
               "sources": [{"raw_path": "/Users/someone/data/raw/helius/live/x.json"}], "mint": GRAD}
        msg = "\n".join(handlers.private_detail(3, json.dumps(rep), ""))
        self.assertIn("market: not fetched: RateLimited", msg)
        self.assertNotIn("/Users/", msg)
        self.assertNotIn("raw_path", msg)
        text = "**Scan** x\n\n**Missing or unreliable**\n- mint: fetch failed: boom\n\nSources: helius /Users/a"
        msg = "\n".join(handlers.private_detail(3, text, ""))
        self.assertIn("mint: fetch failed: boom", msg)
        self.assertNotIn("/Users/", msg)


class SecurityReviewTest(unittest.IsolatedAsyncioTestCase):
    """Regressions for the Security Reviewer's two Low findings on master 6bbdeca (2026-11-22)."""

    async def test_sec_1_bot_token_not_passed_to_scanner_child(self):
        probe = ("import os,json;print(json.dumps({k: k in os.environ for k in "
                 "('DISCORD_BOT_TOKEN','DISCORD_BOT_TOKEN_FILE','HELIUS_API_KEY')}))")
        with mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN_FILE": "/x",
                                          "HELIUS_API_KEY": "k"}):
            code, out, err = await handlers.run_scanner(GRAD, argv=[sys.executable, "-c", probe])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"DISCORD_BOT_TOKEN": False, "DISCORD_BOT_TOKEN_FILE": False,
                                           "HELIUS_API_KEY": True})

    async def test_sec_2_failure_detail_never_posted_publicly(self):
        secret_bits = ("/Users/someone/data/raw", "helius HTTP 401", "Traceback")

        async def crash(m):
            return 1, "", "Traceback (most recent call last):\n  File \"/Users/someone/data/raw/x.py\"\n" \
                          "ApiError: helius HTTP 401 on getAccountInfo: {\"error\": \"bad key\"}"

        async def nothing(m):
            return 3, "**Scan** x\n\n**Missing or unreliable**\n- mint: fetch failed: helius HTTP 401 on " \
                      "getAccountInfo: /Users/someone/data/raw\n", ""

        async def slow(m):
            return None, "", "timed out after 120 s; /Users/someone/data/raw"
        c = cfg(DISCORD_ALLOWED_USER_IDS="1")
        for runner in (crash, nothing, slow):
            i = Interaction(User(1))
            with mock.patch("sys.stderr", io.StringIO()):
                await handlers.handle_scan(i, GRAD, c, runner)
            public = "\n".join(e[1] for e in i.log if e[0] == "followup")
            private = "\n".join(e[1] for e in i.log if e[0] == "private")
            for bit in secret_bits:
                self.assertNotIn(bit, public, (runner.__name__, public))
            self.assertTrue(private, runner.__name__)  # the caller still gets the detail, privately

    async def test_sec_2_crash_detail_goes_to_bot_log(self):
        async def crash(m):
            return 1, "", "Traceback\nKeyError: 'boom'"
        log = io.StringIO()
        with mock.patch("sys.stderr", log):
            await handlers.handle_scan(Interaction(User(1)), GRAD, cfg(DISCORD_ALLOWED_USER_IDS="1"), crash)
        self.assertIn("KeyError: 'boom'", log.getvalue())


class StartupTest(unittest.TestCase):
    def test_env_file_does_not_override_environment(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# comment\nDISCORD_GUILD_ID=123\nDISCORD_BOT_TOKEN='abc'\nBAD LINE\n", encoding="utf-8")
            env = main.load_env_file(p, {"DISCORD_GUILD_ID": "999"})
            self.assertEqual(env, {"DISCORD_GUILD_ID": "999", "DISCORD_BOT_TOKEN": "abc"})

    def test_key_file(self):
        with tempfile.TemporaryDirectory() as d:
            k = Path(d) / "k"
            k.write_text("KEY\n", encoding="utf-8")
            self.assertEqual(main.load_key_files({"HELIUS_API_KEY_FILE": str(k)})["HELIUS_API_KEY"], "KEY")

    def test_second_instance_cannot_take_lock(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bot.lock"
            first = main.take_lock(p)
            self.assertIsNotNone(first)
            # a second process must fail to lock
            import subprocess
            code = subprocess.run([sys.executable, "-c", "import sys;from pathlib import Path;from bot import main;"
                                   "sys.exit(0 if main.take_lock(Path(sys.argv[1])) is None else 1)", str(p)],
                                  cwd=str(handlers.ROOT)).returncode
            self.assertEqual(code, 0)
            first.close()

    def test_review_6_lock_path_read_after_env_file(self):
        """Regression (review finding 6): LOCK was read at import, so RKD_BOT_LOCK from the env file was ignored."""
        with tempfile.TemporaryDirectory() as d:
            want = Path(d) / "custom.lock"
            envf = Path(d) / "bot.env"
            envf.write_text("RKD_BOT_LOCK={}\n".format(want), encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RKD_BOT_LOCK", None)
                main.load_env_file(envf)
                f = main.take_lock()
                try:
                    self.assertIsNotNone(f)
                    self.assertEqual(Path(f.name), want)
                    self.assertTrue(want.exists())
                finally:
                    f.close()

    def test_main_refuses_without_token(self):
        old = dict(os.environ)
        try:
            for k in ("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "RKD_BOT_ENV_FILE"):
                os.environ.pop(k, None)
            err = io.StringIO()
            sys.stderr, saved = err, sys.stderr
            try:
                self.assertEqual(main.main(), 2)
            finally:
                sys.stderr = saved
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
