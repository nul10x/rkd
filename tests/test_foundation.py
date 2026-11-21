"""Phase 2/3 acceptance tests. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import sqlite3
import tempfile
import unittest

from ecosystem.db import connect
from ecosystem.logbook import DuplicateRecord, Logbook, LogbookError
from ecosystem.protocol import handle, make
from ecosystem.tasks import BudgetExceeded, ProviderPaused, TaskQueue

# Clearly fake example data, used only by tests.
FINDING = {
    "kind": "observation", "category": "developer_behaviour", "created_by": "researcher",
    "title": "EXAMPLE: developers who sell within 10 minutes of launch",
    "description": "EXAMPLE DATA. Tokens whose deployer wallet sold most holdings shortly after liquidity was added.",
    "tags": "example deployer early-sell",
}


class LogbookTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db"); os.close(fd)
        self.conn = connect(self.path)
        self.lb = Logbook(self.conn)

    def tearDown(self):
        self.conn.close()
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(self.path + ext):
                os.remove(self.path + ext)

    def test_save_and_get(self):
        rid = self.lb.save(FINDING, sources=[{"kind": "dataset", "ref": "example://none"}])["id"]
        self.assertEqual(rid, "KR-000001")
        r = self.lb.get(rid)
        self.assertEqual(r["status"], "unverified")
        self.assertEqual(r["sources"][0]["ref"], "example://none")

    def test_search_returns_content_not_filenames(self):
        self.lb.save(FINDING)
        res = self.lb.search("deployer sold liquidity")
        self.assertEqual(len(res), 1)
        self.assertIn("[", res[0]["snippet"])       # highlighted match
        self.assertEqual(res[0]["status"], "unverified")
        self.assertEqual(self.lb.search("deployer", status="validated"), [])

    def test_search_survives_fts_syntax(self):
        self.lb.save(FINDING)
        self.lb.search('wallet" OR (NEAR AND -*')  # must not raise

    def test_update_preserves_history(self):
        rid = self.lb.save(FINDING)["id"]
        self.lb.update(rid, {"status": "hypothesis", "confidence": 0.3}, "researcher", "first pass")
        self.lb.update(rid, {"status": "under_investigation"}, "researcher")
        h = self.lb.history(rid)
        self.assertEqual([v["version"] for v in h], [1, 2])
        self.assertEqual(h[0]["snapshot"]["status"], "unverified")
        self.assertEqual(self.lb.get(rid)["version"], 3)

    def test_validated_requires_evidence(self):
        rid = self.lb.save(FINDING)["id"]
        with self.assertRaises(LogbookError) as e:
            self.lb.update(rid, {"status": "validated"}, "researcher")
        self.assertIn("sample_size", str(e.exception))
        self.lb.update(rid, {"status": "historically_supported", "methodology": "m", "sample_size": 40,
                             "evidence": "e", "limitations": "l"}, "researcher",
                       sources=[{"kind": "dataset", "ref": "example://set"}])

    def test_no_delete(self):
        self.lb.save(FINDING)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM records")

    def test_exact_and_near_duplicates(self):
        rid = self.lb.save(FINDING)["id"]
        with self.assertRaises(DuplicateRecord) as e:
            self.lb.save(dict(FINDING, title=FINDING["title"].upper()))
        self.assertEqual((e.exception.kind, e.exception.existing_id), ("exact", rid))
        near = dict(FINDING, description=FINDING["description"] + " Sample is small.")
        with self.assertRaises(DuplicateRecord) as e:
            self.lb.save(near)
        self.assertEqual(e.exception.kind, "near")
        out = self.lb.save(near, allow_near_duplicate=True)
        self.assertEqual(out["near_duplicates"], [rid])

    def test_contradictions_and_stale(self):
        a = self.lb.save(FINDING)["id"]
        b = self.lb.save(dict(FINDING, title="EXAMPLE: early dev sells do not predict failure",
                              description="EXAMPLE DATA. Counter-sample from a different month."))["id"]
        self.lb.link(b, a, "contradicts", "researcher")
        self.assertEqual([r["id"] for r in self.lb.contradictions(a)], [b])
        self.assertEqual(self.lb.search("early sells")[0]["contradicted_by"] != [], True)
        self.assertEqual(len(self.lb.stale(days=-1)), 2)

    def test_bad_values_rejected(self):
        for bad in ({"category": "animation"}, {"status": "true"}, {"confidence": 2}):
            with self.assertRaises(LogbookError):
                self.lb.save(dict(FINDING, **bad))

    def test_persists_across_restart(self):
        rid = self.lb.save(FINDING)["id"]
        self.conn.close()
        self.conn = connect(self.path)
        self.assertEqual(Logbook(self.conn).get(rid)["title"], FINDING["title"])


class ProtocolAndTaskTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.q = TaskQueue(self.conn, limits={"providers": {"demo": {"daily_requests": 2}}})

    def test_round_trip_researcher_logbook_builder(self):
        r = handle(self.conn, make("researcher", "logbook", "submit_record",
                                   {"record": FINDING, "sources": [{"kind": "url", "ref": "example://x"}]}))
        self.assertTrue(r["payload"]["ok"], r)
        rid = r["payload"]["data"]["id"]
        q = handle(self.conn, make("builder", "logbook", "query", {"text": "developer sell launch"}))
        self.assertEqual(q["payload"]["data"]["results"][0]["id"], rid)
        tool = handle(self.conn, make("builder", "logbook", "submit_record", {"record": {
            "kind": "tool", "category": "development_projects", "title": "EXAMPLE early-sell checker",
            "description": "Test tool built from finding.", "status": "n/a"},
            "links": [{"dst": rid, "relation": "implements"}]}))
        self.assertTrue(tool["payload"]["ok"], tool)
        got = handle(self.conn, make("researcher", "logbook", "get", {"id": rid}))
        self.assertEqual(got["payload"]["data"]["links"][0]["relation"], "implements")
        n = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        self.assertEqual(n, 8)  # 4 requests + 4 replies persisted

    def test_bad_messages_become_errors(self):
        r = handle(self.conn, make("researcher", "logbook", "explode", {}))
        self.assertFalse(r["payload"]["ok"])
        dup = make("researcher", "logbook", "submit_record", {"record": FINDING})
        handle(self.conn, dup)
        r = handle(self.conn, make("researcher", "logbook", "submit_record", {"record": FINDING}))
        self.assertEqual(r["payload"]["duplicate_of"], "KR-000001")

    def test_task_budget_pauses_and_resumes(self):
        tid = self.q.add("researcher", "EXAMPLE objective", "report submitted", "user",
                         budget={"model_requests": 2})
        self.assertEqual(self.q.claim("researcher")["id"], tid)
        self.assertIsNone(self.q.claim("researcher"))        # sequential
        self.q.spend(tid, "model_requests", progress={"page": 1})
        self.q.spend(tid, "model_requests")
        with self.assertRaises(BudgetExceeded):
            self.q.spend(tid, "model_requests", progress={"page": 3})
        t = self.q.get(tid)
        self.assertEqual((t["status"], t["progress"]["page"]), ("paused", 3))

    def test_task_needs_done_condition(self):
        with self.assertRaises(ValueError):
            self.q.add("researcher", "research forever", "", "user")

    def test_provider_cap_and_rate_limit(self):
        self.q.provider_request("demo"); self.q.provider_request("demo")
        with self.assertRaises(ProviderPaused):
            self.q.provider_request("demo")
        self.q.provider_rate_limited("other", "2999-01-01T00:00:00+00:00")
        with self.assertRaises(ProviderPaused):
            self.q.provider_request("other")


if __name__ == "__main__":
    unittest.main()
