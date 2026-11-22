"""Regression tests for collectors/client.py: atomic files, per-provider pauses, shared throttle.

No network: urllib.request.urlopen is replaced by a fake. All files live in a temp dir.
"""
import email.message
import email.utils
import glob
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

from collectors import client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1795291094.236819  # the real GeckoTerminal 429 recorded in usage_xchain.json


class Clock:
    def __init__(self, t):
        self.t = t
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def ok(payload):
    r = mock.MagicMock()
    r.read.return_value = json.dumps(payload).encode()
    r.__enter__.return_value = r
    return r


def http_error(code, retry_after=None, body=b"slow down"):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.invalid", code, "err", h, io.BytesIO(body))


class ClientBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = self.tmp.name
        self.clock = Clock(T0 + 10000)
        self.patches = [
            mock.patch.object(client, "RAW", self.raw),
            mock.patch.object(client, "USAGE", os.path.join(self.raw, "usage.json")),
            mock.patch.object(client, "BUDGET", 100),
            mock.patch.object(client, "RPS", 2.0),
            mock.patch.object(client, "_now", self.clock.now),
            mock.patch.object(client, "_sleep", self.clock.sleep),
        ]
        for p in self.patches:
            p.start()
        self.responses = []
        self.urls = []
        self.net = mock.patch("urllib.request.urlopen", side_effect=self._urlopen)
        self.net.start()

    def tearDown(self):
        self.net.stop()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _urlopen(self, req, timeout=None):
        self.urls.append(req.full_url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return ok(r)

    def gt(self, n=0):
        return client.cached("geckoterminal", {"p": n}, "https://gt.invalid/%d" % n, None, "gt")

    def ds(self, n=0):
        return client.cached("dexscreener", {"tokens": [str(n)]}, "https://ds.invalid/%d" % n, None, "tokens/v1")

    def usage(self):
        with open(client.USAGE) as f:
            return json.load(f)


class AtomicFilesTest(ClientBase):
    def test_half_written_usage_file_does_not_crash_and_keeps_count(self):
        with open(client.USAGE, "w") as f:
            f.write('{\n "calls": 42,\n "by_provider": {\n  "helius": 4')  # killed mid-write
        self.assertEqual(client.calls_used(), 42)
        self.assertEqual(len(glob.glob(client.USAGE + ".corrupt-*")), 1)
        self.responses = [{"x": 1}]
        self.assertEqual(self.ds(), {"x": 1})
        u = self.usage()
        self.assertEqual(u["calls"], 43)
        self.assertTrue(u["recovered"]["calls_salvaged"])

    def test_empty_or_wrong_shape_usage_file(self):
        for text in ("", "[]", '{"calls": 3}'):
            with open(client.USAGE, "w") as f:
                f.write(text)
            self.assertIsInstance(client.calls_used(), int)
        self.responses = [{"x": 1}]
        self.ds()
        self.assertEqual(self.usage()["by_provider"], {"dexscreener": 1})

    def test_failed_write_keeps_old_file_and_leaves_no_temp(self):
        path = os.path.join(self.raw, "f.json")
        client._atomic_write_json(path, {"a": 1})
        with self.assertRaises(TypeError):
            client._atomic_write_json(path, {"a": object()})
        with open(path) as f:
            self.assertEqual(json.load(f), {"a": 1})
        self.assertEqual(os.listdir(self.raw), ["f.json"])

    def test_cache_layout_and_format_unchanged(self):
        self.responses = [{"pairs": []}]
        self.ds(7)
        h = hashlib.sha256(json.dumps({"tokens": ["7"]}, sort_keys=True).encode()).hexdigest()
        path = os.path.join(self.raw, "dexscreener", h + ".json")
        with open(path) as f:
            rec = json.load(f)
        self.assertEqual(sorted(rec), ["fetched_at", "request", "response"])
        self.assertEqual(rec["request"], {"tokens": ["7"]})
        self.assertEqual(os.listdir(os.path.dirname(path)), [h + ".json"])
        self.assertEqual(self.ds(7), {"pairs": []})  # cache hit: no second request
        self.assertEqual(len(self.urls), 1)


class PauseTest(ClientBase):
    def test_429_pauses_only_that_provider_until_retry_after(self):
        self.responses = [http_error(429, "120")]
        with self.assertRaises(client.RateLimited):
            self.ds(1)
        with self.assertRaises(client.RateLimited):
            self.ds(2)  # same provider: refused without a request
        self.assertEqual(len(self.urls), 1)
        self.responses = [{"ok": 1}]
        self.assertEqual(self.gt(1), {"ok": 1})  # other provider not blocked
        self.clock.t += 121
        self.responses = [{"ok": 2}]
        self.assertEqual(self.ds(3), {"ok": 2})
        self.assertEqual(self.usage()["calls"], 3)  # the rejected 429 request is counted

    def test_default_and_minimum_pauses(self):
        cases = [("dexscreener", None, 900), ("geckoterminal", None, 1800), ("geckoterminal", "60", 1800),
                 ("dexscreener", "60", 60)]
        for provider, ra, expect in cases:
            self.responses = [http_error(429, ra)]
            fn = self.gt if provider == "geckoterminal" else self.ds
            with self.assertRaises(client.RateLimited):
                fn(len(self.urls) + 100)
            self.assertAlmostEqual(client.paused_until(provider) - self.clock.t, expect, places=3, msg=(provider, ra))
            self.clock.t += expect + 1

    def test_retry_after_http_date(self):
        when = email.utils.formatdate(self.clock.t + 300, usegmt=True)
        self.responses = [http_error(429, when)]
        with self.assertRaises(client.RateLimited):
            self.ds()
        self.assertAlmostEqual(client.paused_until("dexscreener") - self.clock.t, 300, delta=1)

    def test_jsonrpc_rate_limit_pauses_provider(self):
        self.responses = [{"jsonrpc": "2.0", "error": {"code": -32005, "message": "rate limit exceeded"}}]
        with self.assertRaises(client.RateLimited):
            client.evm_rpc("eth_blockNumber", [], url="https://rpc.invalid")
        self.assertAlmostEqual(client.paused_until("robinhood_rpc") - self.clock.t, 900, places=3)
        self.assertEqual(client.paused_until("helius"), 0.0)

    def test_pause_is_shared_across_usage_files(self):
        self.responses = [http_error(429, "600")]
        with self.assertRaises(client.RateLimited):
            self.ds()
        with mock.patch.object(client, "USAGE", os.path.join(self.raw, "usage_other.json")):
            with self.assertRaises(client.RateLimited):
                self.ds(5)
        self.assertEqual(len(self.urls), 1)

    @mock.patch.object(client, "BUDGET", 1000)
    def test_old_global_rate_limited_record_migrates(self):
        old = {"calls": 693, "by_provider": {"geckoterminal": 12}, "errors": [{"provider": "x"}],
               "rate_limited": {"provider": "geckoterminal", "label": "/ohlcv/day", "at": T0}}
        with open(client.USAGE, "w") as f:
            json.dump(old, f)
        self.assertEqual(client.calls_used(), 693)
        self.assertAlmostEqual(client.paused_until("geckoterminal"), T0 + 1800, places=3)
        self.assertEqual(client.paused_until("helius"), 0.0)
        with open(client.USAGE) as f:
            self.assertEqual(json.load(f), old)  # reading does not rewrite the file
        self.clock.t = T0 + 100  # still paused for GeckoTerminal, not for others
        with self.assertRaises(client.RateLimited):
            self.gt()
        self.responses = [{"ok": 1}]
        self.ds()
        self.clock.t = T0 + 1801
        self.responses = [{"ok": 2}]
        self.assertEqual(self.gt(), {"ok": 2})
        u = self.usage()
        self.assertNotIn("rate_limited", u)
        self.assertTrue(u["paused"]["geckoterminal"]["migrated"])
        self.assertEqual((u["calls"], len(u["errors"])), (695, 1))


class IntervalTest(ClientBase):
    def test_min_interval_per_provider(self):
        self.responses = [{"a": 1}, {"a": 2}, {"a": 3}]
        self.gt(1)
        self.gt(2)
        self.assertAlmostEqual(self.clock.slept[-1], 15.0, places=3)
        self.ds(1)  # another provider waits only for the global 1/RPS gap, not GeckoTerminal's 15 s
        self.assertAlmostEqual(self.clock.slept[-1], 0.5, places=3)

    def test_global_rps_ceiling(self):
        self.responses = [{"a": 1}, {"a": 2}]
        with mock.patch.dict(client.MIN_INTERVAL, {"dexscreener": 0.0}):
            self.ds(1)
            self.ds(2)
        self.assertAlmostEqual(self.clock.slept[-1], 0.5, places=3)

    def test_budget_counts_rejected_requests(self):
        self.responses = [http_error(500, body=b"boom"), {"ok": 1}]
        with self.assertRaises(client.ApiError):
            self.ds(1)
        self.ds(2)
        with mock.patch.object(client, "BUDGET", 2):
            with self.assertRaises(client.BudgetExceeded):
                self.ds(3)
        self.assertEqual(self.usage()["calls"], 2)

    def test_interval_holds_across_processes(self):
        child = (
            "import sys, time\n"
            "from collectors import client\n"
            "client.MIN_INTERVAL['testprov'] = 0.3\n"
            "client.RPS = 1000.0\n"
            "for _ in range(3):\n"
            "    client._reserve('testprov')\n"
            "    print(time.time(), flush=True)\n")
        procs = []
        for i in range(2):
            env = dict(os.environ, RKD_RAW=self.raw, RKD_USAGE=os.path.join(self.raw, "u%d.json" % i))
            procs.append(subprocess.Popen([sys.executable, "-c", child], cwd=ROOT, env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        times = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, err)
            times += [float(x) for x in out.split()]
        times.sort()
        self.assertEqual(len(times), 6)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertGreaterEqual(min(gaps), 0.28, gaps)


if __name__ == "__main__":
    unittest.main()


class LogbookCountTest(ClientBase):
    """Opt-in api_usage / task budget counting in the Logbook (temp DB only)."""

    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.raw, "logbook.db")
        self.env = mock.patch.dict(os.environ, {"RKD_LOGBOOK_COUNT": "1", "RKD_DB": self.db})
        self.env.start()
        from ecosystem.db import connect
        from ecosystem.tasks import TaskQueue
        self.conn = connect(self.db)
        self.q = TaskQueue(self.conn)

    def tearDown(self):
        self.conn.close()
        self.env.stop()
        super().tearDown()

    def requests(self, provider):
        r = self.conn.execute("SELECT SUM(requests) AS n FROM api_usage WHERE provider=?", (provider,)).fetchone()
        return r["n"] or 0

    def test_counts_requests_and_task_budget(self):
        tid = self.q.add("researcher", "obj", "done", "researcher", budget={"api_calls": 1})
        with mock.patch.dict(os.environ, {"RKD_TASK": tid}):
            self.responses = [{"x": 1}]
            self.ds(1)
            self.assertEqual(self.requests("dexscreener"), 1)
            self.assertEqual(self.q.get(tid)["used"]["api_calls"], 1)
            self.ds(1)  # cached: no request, no count
            self.assertEqual(self.requests("dexscreener"), 1)
            from ecosystem.tasks import BudgetExceeded
            self.responses = [{"x": 2}]
            with self.assertRaises(BudgetExceeded):
                self.ds(2)
            self.assertEqual(self.q.get(tid)["status"], "paused")

    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {"RKD_LOGBOOK_COUNT": "0"}):
            self.responses = [{"x": 1}]
            self.ds(3)
        self.assertEqual(self.requests("dexscreener"), 0)


class LiveTest(ClientBase):
    def live(self, n=0, max_age_s=0):
        return client.live("dexscreener", {"token_pairs": ["solana", str(n)]},
                           "https://ds.invalid/live/%d" % n, None, "token-pairs/v1", max_age_s)

    def test_live_always_fetches_and_keeps_timestamped_snapshots(self):
        self.responses = [[{"priceUsd": "1"}], [{"priceUsd": "2"}]]
        a = self.live()
        self.clock.t += 5
        b = self.live()
        self.assertEqual([a["response"][0]["priceUsd"], b["response"][0]["priceUsd"]], ["1", "2"])
        self.assertEqual(len(self.urls), 2)
        self.assertFalse(a["reused"] or b["reused"])
        self.assertNotEqual(a["raw_path"], b["raw_path"])
        self.assertIn(os.path.join("dexscreener", "live"), a["raw_path"])
        with open(b["raw_path"]) as f:
            snap = json.load(f)
        self.assertEqual(snap["fetched_at"], b["fetched_at"])
        self.assertEqual(snap["request"], {"token_pairs": ["solana", "0"]})
        self.assertEqual(self.usage()["calls"], 2)

    def test_live_never_reads_or_writes_forever_cache(self):
        self.responses = [[1], [2]]
        self.ds(0)
        self.live(0)
        flat = [p for p in os.listdir(os.path.join(self.raw, "dexscreener")) if p.endswith(".json")]
        self.assertEqual(len(flat), 1)  # only the cached() file

    def test_max_age_reuses_recent_snapshot_only(self):
        self.responses = [[{"v": 1}], [{"v": 2}]]
        self.live(max_age_s=60)
        self.clock.t += 30
        r = self.live(max_age_s=60)
        self.assertTrue(r["reused"])
        self.assertEqual(r["response"], [{"v": 1}])
        self.assertEqual(len(self.urls), 1)
        self.clock.t += 61
        r = self.live(max_age_s=60)
        self.assertFalse(r["reused"])
        self.assertEqual(r["response"], [{"v": 2}])

    def test_live_respects_pause_and_budget(self):
        self.responses = [http_error(429, "120")]
        with self.assertRaises(client.RateLimited):
            self.live()
        with self.assertRaises(client.RateLimited):
            self.live()
        self.assertEqual(len(self.urls), 1)

    def test_helius_live_needs_key_and_never_stores_it(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HELIUS_API_KEY", None)
            with self.assertRaises(client.ApiError):
                client.helius_live("getAccountInfo", ["x"])
        self.responses = [{"jsonrpc": "2.0", "result": {"value": None}}]
        with mock.patch.dict(os.environ, {"HELIUS_API_KEY": "SECRETKEY123"}):
            r = client.helius_live("getAccountInfo", ["x"])
        self.assertEqual(r["response"]["result"], {"value": None})
        with open(r["raw_path"]) as f:
            self.assertNotIn("SECRETKEY123", f.read())


class ReviewFixesTest(ClientBase):
    """Regressions for the Change Reviewer findings on build/token-scanner (2026-11-22)."""

    def _lock_held(self):
        c = __import__("sqlite3").connect(os.path.join(self.raw, "throttle.sqlite"), timeout=0, isolation_level=None)
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute("ROLLBACK")
            return False
        except Exception:
            return True
        finally:
            c.close()

    def _watch_saves(self):
        seen = []
        real = client._save_usage

        def save(u):
            seen.append(self._lock_held())
            real(u)
        return seen, mock.patch.object(client, "_save_usage", save)

    def test_review_2_error_and_pause_writes_hold_the_lock(self):
        """Finding 2: error/pause paths wrote usage.json outside the throttle lock (lost counts)."""
        seen, p = self._watch_saves()
        with p:
            self.responses = [http_error(500, body=b"boom")]
            with self.assertRaises(client.ApiError):
                self.ds(1)
            self.responses = [{"jsonrpc": "2.0", "error": {"code": -32600, "message": "bad"}}]
            with self.assertRaises(client.ApiError):
                client.evm_rpc("eth_x", [], url="https://rpc.invalid")
            self.responses = [http_error(429, "120")]
            with self.assertRaises(client.RateLimited):
                self.ds(2)
        self.assertTrue(seen)
        self.assertTrue(all(seen), seen)
        u = self.usage()
        self.assertEqual((u["calls"], len(u["errors"])), (3, 2))

    def test_review_2_concurrent_count_is_not_lost(self):
        """Finding 2: another process counts a call while our error path is between its read and write.
        If our write is unlocked, it overwrites that count (old code: 1). Locked, the other process waits
        for the lock and writes afterwards, so both calls stay counted (2)."""
        self.responses = [http_error(500, body=b"boom")]
        real_usage = client._usage
        state = {"n": 0, "deferred": False}

        def other_process_counts():
            other = real_usage()
            other["calls"] += 1
            client._atomic_write_json(client.USAGE, other, indent=1)

        def racing_usage():
            u = real_usage()
            state["n"] += 1
            if state["n"] == 3:  # the error path's read
                if self._lock_held():
                    state["deferred"] = True  # blocked: it will write after we release the lock
                else:
                    other_process_counts()
            return u
        with mock.patch.object(client, "_usage", racing_usage):
            with self.assertRaises(client.ApiError):
                self.ds(1)
        if state["deferred"]:
            other_process_counts()
        self.assertEqual(self.usage()["calls"], 2)

    def test_review_4_past_retry_after_date_still_pauses(self):
        """Finding 4: an HTTP-date Retry-After in the past gave a 0 s pause."""
        when = email.utils.formatdate(self.clock.t - 600, usegmt=True)
        self.responses = [http_error(429, when)]
        with self.assertRaises(client.RateLimited):
            self.ds()
        self.assertGreaterEqual(client.paused_until("dexscreener") - self.clock.t, 60)
        self.responses = [http_error(429, "0")]
        self.clock.t += 61
        with self.assertRaises(client.RateLimited):
            self.ds(9)
        self.assertGreaterEqual(client.paused_until("dexscreener") - self.clock.t, 60)
