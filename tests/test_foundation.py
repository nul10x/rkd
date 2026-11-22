"""Phase 2/3 acceptance tests. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import sqlite3
import tempfile
import unittest

from datetime import datetime, timezone

from ecosystem.db import connect, load_schema, set_journal
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
        self.assertEqual(self.q.claim("researcher")["id"], tid)  # sequential: same task, not a second
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


class TermuxRegressionTests(unittest.TestCase):
    """Regression tests for the 2026-11-21 Termux/Android review."""

    def setUp(self):
        self.conn = connect(":memory:")
        self.lb = Logbook(self.conn)
        self.q = TaskQueue(self.conn, limits={})

    def _two_records(self):
        a = self.lb.save(dict(FINDING))["id"]
        b = self.lb.save(dict(FINDING, title="EXAMPLE: unrelated wallet funding pattern",
                              description="EXAMPLE DATA. Something else entirely."))["id"]
        return a, b

    def test_killed_process_task_is_resumed(self):
        tid = self.q.add("builder", "EXAMPLE objective", "tests pass", "user")
        self.q.claim("builder")
        # simulate Android killing the process: a fresh queue on the same database
        again = TaskQueue(self.conn, limits={}).claim("builder")
        self.assertIsNotNone(again)
        self.assertEqual((again["id"], again["status"]), (tid, "running"))

    def test_unknown_relation_is_refused_not_ignored(self):
        a, b = self._two_records()
        with self.assertRaises(LogbookError):
            self.lb.link(a, b, "implement", "builder")
        r = handle(self.conn, make("builder", "logbook", "link", {"src": a, "dst": b, "relation": "foo"}))
        self.assertFalse(r["payload"]["ok"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0], 0)

    def test_empty_update_is_an_error_reply(self):
        a, _ = self._two_records()
        r = handle(self.conn, make("builder", "logbook", "update_record", {"id": a, "changes": {}}))
        self.assertFalse(r["payload"]["ok"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM messages WHERE status='new'").fetchone()[0], 0)

    def test_database_error_becomes_error_reply(self):
        r = handle(self.conn, make("builder", "logbook", "submit_record", {"record": "not an object"}))
        self.assertFalse(r["payload"]["ok"])

    def test_provider_day_is_utc(self):
        self.q.provider_request("demo")
        day = self.conn.execute("SELECT day FROM api_usage WHERE provider='demo'").fetchone()[0]
        self.assertEqual(day, datetime.now(timezone.utc).date().isoformat())

    def test_rate_limit_time_is_normalised_to_utc(self):
        for prov, ts in (("z", "2999-01-01T00:00:00Z"), ("off", "2999-01-01T02:00:00+02:00"),
                         ("naive", "2999-01-01T00:00:00")):
            self.q.provider_rate_limited(prov, ts)
            got = self.conn.execute("SELECT paused_until FROM api_usage WHERE provider=?", (prov,)).fetchone()[0]
            self.assertEqual(got, "2999-01-01T00:00:00+00:00")
            with self.assertRaises(ProviderPaused):
                self.q.provider_request(prov)

    def test_ids_keep_increasing_past_999999(self):
        ts = "2026-01-01T00:00:00+00:00"
        self.conn.execute("INSERT INTO tasks(id,agent,objective,done_condition,budget,created_by,created_at,updated_at)"
                          " VALUES ('T-999999','x','o','d','{}','user',?,?)", (ts, ts))
        self.assertEqual(self.q.add("x", "o", "d", "user"), "T-1000000")
        self.assertEqual(self.q.add("x", "o", "d", "user"), "T-1000001")


class _FakeConn:
    """Stands in for a connection on a filesystem we cannot reproduce here."""
    def __init__(self, fail_on):
        self.fail_on, self.calls = fail_on, []

    def execute(self, sql):
        self.calls.append(sql)
        if self.fail_on in sql:
            raise sqlite3.OperationalError("disk I/O error")
        return self

    def fetchone(self):
        return ("delete",)

    def executescript(self, sql):
        raise sqlite3.OperationalError("no such module: fts5")


class FilesystemFallbackTests(unittest.TestCase):
    def test_wal_unsupported_falls_back_to_delete(self):
        c = _FakeConn(fail_on="WAL")
        self.assertEqual(set_journal(c), "delete")
        self.assertIn("PRAGMA journal_mode = DELETE", c.calls)

    def test_wal_on_normal_file(self):
        fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
        try:
            conn = connect(path)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            conn.close()
        finally:
            for ext in ("", "-wal", "-shm"):
                if os.path.exists(path + ext):
                    os.remove(path + ext)

    def test_missing_fts5_has_clear_message(self):
        with self.assertRaises(RuntimeError) as cm:
            load_schema(_FakeConn(fail_on="never"))
        self.assertIn("FTS5", str(cm.exception))


class LinkNoteTests(unittest.TestCase):
    """Researcher request 2026-11-22: re-sending a link with a note sets the note on an existing link.
    Before, _link used INSERT OR IGNORE and silently dropped it."""

    def setUp(self):
        self.conn = connect(":memory:")
        self.lb = Logbook(self.conn)
        self.a = self.lb.save(dict(FINDING))["id"]
        self.b = self.lb.save(dict(FINDING, title="EXAMPLE: unrelated wallet funding pattern",
                                   description="EXAMPLE DATA. Something else entirely."))["id"]

    def note(self):
        return self.conn.execute("SELECT note FROM links WHERE src=? AND dst=?", (self.a, self.b)).fetchone()["note"]

    def test_note_added_to_existing_link_via_protocol(self):
        self.lb.link(self.a, self.b, "contradicts", "researcher")
        r = handle(self.conn, make("researcher", "logbook", "link", {
            "src": self.a, "dst": self.b, "relation": "contradicts", "note": "EXAMPLE: different definitions"}))
        self.assertTrue(r["payload"]["ok"])
        self.assertEqual(r["payload"]["data"]["result"], "note_updated")
        self.assertEqual(self.note(), "EXAMPLE: different definitions")
        out = [l for l in self.lb.get(self.a)["links"] if l["other"] == self.b][0]
        self.assertEqual(out["note"], "EXAMPLE: different definitions")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0], 1)

    def test_history_is_append_only_and_keeps_old_notes(self):
        self.assertEqual(self.lb.link(self.a, self.b, "related", "builder", "first"), "created")
        self.assertEqual(self.lb.link(self.a, self.b, "related", "researcher", "second"), "note_updated")
        self.assertEqual(self.lb.link(self.a, self.b, "related", "researcher", "third"), "note_updated")
        h = self.lb.link_note_history(self.a, self.b, "related")
        self.assertEqual([(x["old_note"], x["new_note"], x["changed_by"]) for x in h],
                         [("first", "second", "researcher"), ("second", "third", "researcher")])

    def test_same_or_missing_note_changes_nothing(self):
        self.lb.link(self.a, self.b, "related", "builder", "keep me")
        self.assertEqual(self.lb.link(self.a, self.b, "related", "builder", "keep me"), "unchanged")
        self.assertEqual(self.lb.link(self.a, self.b, "related", "builder"), "unchanged")  # no note: never erases
        self.assertEqual(self.note(), "keep me")
        self.assertEqual(self.lb.link_note_history(self.a, self.b, "related"), [])

    def test_existing_database_gets_history_table(self):
        fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
        try:
            c = connect(path)
            c.execute("DROP TABLE link_note_history")  # a database created before this change
            c.commit(); c.close()
            c = connect(path)
            self.assertIsNotNone(c.execute("SELECT name FROM sqlite_master WHERE name='link_note_history'").fetchone())
            c.close()
        finally:
            for ext in ("", "-wal", "-shm"):
                if os.path.exists(path + ext):
                    os.remove(path + ext)


if __name__ == "__main__":
    unittest.main()
