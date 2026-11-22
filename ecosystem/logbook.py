"""Logbook: the ecosystem's institutional memory.

Saves, versions, links, searches and retrieves knowledge records.
Records are never deleted or silently overwritten: every update first
snapshots the previous version into record_versions.
"""
import difflib
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from .db import next_id, now, row_dict

STATUSES = ("unverified", "hypothesis", "under_investigation",
            "historically_supported", "validated", "rejected", "n/a")
KINDS = ("finding", "hypothesis", "observation", "project", "experiment",
         "tool", "lesson", "failed_approach", "decision", "report")
CATEGORIES = (
    "crypto_research", "developer_behaviour", "wallet_intelligence", "market_structure",
    "token_launch_analysis", "historical_patterns", "statistical_findings",
    "research_hypotheses", "validated_findings", "development_projects",
    "software_architecture", "code_documentation", "experiments",
    "failed_approaches", "lessons_learned",
)
EDITABLE = ("title", "description", "category", "status", "confidence", "methodology",
            "sample_size", "time_period", "evidence", "limitations", "tags", "last_verified_at")
# A finding above "under_investigation" must carry its basis.
EVIDENCE_REQUIRED = ("historically_supported", "validated")
NEAR_DUP_RATIO = 0.85
RELATIONS = ("related", "supports", "contradicts", "supersedes", "derived_from", "implements", "tests")


class LogbookError(ValueError):
    pass


class DuplicateRecord(LogbookError):
    def __init__(self, existing_id, kind):
        super().__init__("{} duplicate of {}".format(kind, existing_id))
        self.existing_id = existing_id
        self.kind = kind


def _hash(title, description):
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    return hashlib.sha256((norm(title) + "\n" + norm(description)).encode()).hexdigest()


def _fts_query(text):
    """Turn free text into a safe FTS5 OR query of quoted terms."""
    terms = re.findall(r"[\w]+", text.lower())
    terms = [t for t in terms if len(t) > 1]
    return " OR ".join('"{}"'.format(t) for t in terms)


def _validate(rec, partial=False):
    if not partial:
        for f in ("kind", "title", "description", "category", "created_by"):
            if not rec.get(f):
                raise LogbookError("missing required field: " + f)
    if "kind" in rec and rec["kind"] not in KINDS:
        raise LogbookError("unknown kind: {}".format(rec["kind"]))
    if "category" in rec and rec["category"] not in CATEGORIES:
        raise LogbookError("unknown category: {} (allowed: {})".format(rec["category"], ", ".join(CATEGORIES)))
    if "status" in rec and rec["status"] not in STATUSES:
        raise LogbookError("unknown status: {}".format(rec["status"]))
    c = rec.get("confidence")
    if c is not None and not (0 <= float(c) <= 1):
        raise LogbookError("confidence must be between 0 and 1")


def _check_evidence(rec, sources_count):
    if rec.get("status") in EVIDENCE_REQUIRED:
        missing = [f for f in ("methodology", "sample_size", "evidence", "limitations") if not rec.get(f)]
        if sources_count == 0:
            missing.append("sources")
        if missing:
            raise LogbookError("status {} requires: {}".format(rec["status"], ", ".join(missing)))


class Logbook:
    def __init__(self, conn):
        self.conn = conn

    # ---------- write ----------
    def save(self, rec, sources=(), links=(), allow_near_duplicate=False):
        """Insert a new record. Returns {'id', 'near_duplicates'}.

        Exact duplicates raise DuplicateRecord. Near duplicates raise unless
        allow_near_duplicate=True, in which case they are linked as 'related'.
        """
        rec = dict(rec)
        rec.setdefault("status", "unverified" if rec.get("kind") in ("finding", "hypothesis", "observation") else "n/a")
        _validate(rec)
        _check_evidence(rec, len(sources))
        h = _hash(rec["title"], rec["description"])
        exact = self.conn.execute("SELECT id FROM records WHERE content_hash=?", (h,)).fetchone()
        if exact:
            raise DuplicateRecord(exact["id"], "exact")
        near = self.find_near_duplicates(rec["title"], rec["description"])
        if near and not allow_near_duplicate:
            raise DuplicateRecord(near[0]["id"], "near")
        ts = now()
        with self.conn:
            rid = next_id(self.conn, "KR", "records")
            self.conn.execute(
                """INSERT INTO records (id,kind,title,description,category,status,confidence,methodology,
                   sample_size,time_period,evidence,limitations,tags,created_by,discovered_at,
                   last_verified_at,updated_at,version,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (rid, rec["kind"], rec["title"], rec["description"], rec["category"], rec["status"],
                 rec.get("confidence"), rec.get("methodology"), rec.get("sample_size"),
                 rec.get("time_period"), rec.get("evidence"), rec.get("limitations"), rec.get("tags"),
                 rec["created_by"], rec.get("discovered_at") or ts, rec.get("last_verified_at"), ts, h))
            for s in sources:
                self._add_source(rid, s)
            for l in links:
                self._link(rid, l["dst"], l.get("relation", "related"), rec["created_by"], l.get("note"))
            for n in near:
                self._link(rid, n["id"], "related", rec["created_by"], "auto: near duplicate")
        return {"id": rid, "near_duplicates": [n["id"] for n in near]}

    def update(self, rid, changes, changed_by, note=None, sources=()):
        """Change fields of a record. The previous version is preserved."""
        old = self.get_row(rid)
        if old is None:
            raise LogbookError("no such record: " + rid)
        if not changes:
            raise LogbookError("no changes given")
        bad = set(changes) - set(EDITABLE)
        if bad:
            raise LogbookError("not editable: " + ", ".join(sorted(bad)))
        _validate(changes, partial=True)
        merged = dict(old, **changes)
        n_src = self.conn.execute("SELECT COUNT(*) FROM sources WHERE record_id=?", (rid,)).fetchone()[0]
        _check_evidence(merged, n_src + len(sources))
        ts = now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO record_versions(record_id,version,snapshot,changed_by,change_note,changed_at) VALUES (?,?,?,?,?,?)",
                (rid, old["version"], json.dumps(old, default=str), changed_by, note, ts))
            sets = ", ".join("{}=?".format(k) for k in changes)
            self.conn.execute(
                "UPDATE records SET {}, version=version+1, updated_at=?, content_hash=? WHERE id=?".format(sets),
                list(changes.values()) + [ts, _hash(merged["title"], merged["description"]), rid])
            for s in sources:
                self._add_source(rid, s)
        return self.get_row(rid)

    def link(self, src, dst, relation, created_by, note=None):
        """Create a link. If it already exists and a different non-empty note is given, the note is
        replaced and the previous one kept in link_note_history. Returns "created", "note_updated" or
        "unchanged"."""
        with self.conn:
            return self._link(src, dst, relation, created_by, note)

    def add_source(self, rid, source):
        with self.conn:
            self._add_source(rid, source)

    def _link(self, src, dst, relation, by, note):
        if relation not in RELATIONS:
            raise LogbookError("unknown relation: {} (allowed: {})".format(relation, ", ".join(RELATIONS)))
        if src == dst:
            raise LogbookError("cannot link a record to itself")
        for r in (src, dst):
            if not self.conn.execute("SELECT 1 FROM records WHERE id=?", (r,)).fetchone():
                raise LogbookError("no such record: " + r)
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO links(src,dst,relation,note,created_by,created_at) VALUES (?,?,?,?,?,?)",
            (src, dst, relation, note, by, now()))
        if cur.rowcount:
            return "created"
        if not note:
            return "unchanged"  # re-sending a link without a note never erases one
        old = self.conn.execute("SELECT note FROM links WHERE src=? AND dst=? AND relation=?",
                                (src, dst, relation)).fetchone()["note"]
        if old == note:
            return "unchanged"
        ts = now()
        self.conn.execute(
            "INSERT INTO link_note_history(src,dst,relation,old_note,new_note,changed_by,changed_at) "
            "VALUES (?,?,?,?,?,?,?)", (src, dst, relation, old, note, by, ts))
        self.conn.execute("UPDATE links SET note=? WHERE src=? AND dst=? AND relation=?", (note, src, dst, relation))
        return "note_updated"

    def link_note_history(self, src, dst, relation):
        return [row_dict(x) for x in self.conn.execute(
            "SELECT old_note,new_note,changed_by,changed_at FROM link_note_history "
            "WHERE src=? AND dst=? AND relation=? ORDER BY rowid", (src, dst, relation))]

    def _add_source(self, rid, s):
        if not s.get("kind") or not s.get("ref"):
            raise LogbookError("source needs kind and ref")
        self.conn.execute(
            "INSERT OR IGNORE INTO sources(record_id,kind,ref,note,retrieved_at) VALUES (?,?,?,?,?)",
            (rid, s["kind"], s["ref"], s.get("note"), s.get("retrieved_at") or now()))

    # ---------- read ----------
    def get_row(self, rid):
        return row_dict(self.conn.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone())

    def get(self, rid):
        """Full record with sources, links in both directions and version count."""
        r = self.get_row(rid)
        if r is None:
            return None
        r.pop("rowid", None)
        r.pop("content_hash", None)
        r["sources"] = [row_dict(x) for x in self.conn.execute(
            "SELECT kind,ref,note,retrieved_at FROM sources WHERE record_id=?", (rid,))]
        r["links"] = [row_dict(x) for x in self.conn.execute(
            """SELECT l.relation, 'out' AS direction, l.dst AS other, r.title, r.status, l.note FROM links l
               JOIN records r ON r.id=l.dst WHERE l.src=?
               UNION ALL
               SELECT l.relation, 'in', l.src, r.title, r.status, l.note FROM links l
               JOIN records r ON r.id=l.src WHERE l.dst=?""", (rid, rid))]
        return r

    def history(self, rid):
        rows = self.conn.execute(
            "SELECT version,snapshot,changed_by,change_note,changed_at FROM record_versions WHERE record_id=? ORDER BY version",
            (rid,)).fetchall()
        out = []
        for x in rows:
            d = row_dict(x)
            d["snapshot"] = json.loads(d["snapshot"])
            out.append(d)
        return out

    def search(self, text=None, category=None, status=None, kind=None, limit=10):
        """Ranked search. Returns compact answers: id, title, status, confidence,
        sample size and a highlighted snippet, never just file names."""
        where, args = [], []
        if category:
            where.append("r.category=?"); args.append(category)
        if status:
            st = [status] if isinstance(status, str) else list(status)
            where.append("r.status IN ({})".format(",".join("?" * len(st)))); args.extend(st)
        if kind:
            where.append("r.kind=?"); args.append(kind)
        q = _fts_query(text) if text else ""
        if q:
            sql = """SELECT r.id,r.kind,r.title,r.category,r.status,r.confidence,r.sample_size,
                       r.updated_at,r.last_verified_at,
                       snippet(records_fts,1,'[',']','…',16) AS snippet, bm25(records_fts) AS score
                     FROM records_fts JOIN records r ON r.rowid=records_fts.rowid
                     WHERE records_fts MATCH ? {} ORDER BY score LIMIT ?""".format(
                ("AND " + " AND ".join(where)) if where else "")
            rows = self.conn.execute(sql, [q] + args + [limit]).fetchall()
        else:
            sql = """SELECT r.id,r.kind,r.title,r.category,r.status,r.confidence,r.sample_size,
                       r.updated_at,r.last_verified_at, substr(r.description,1,160) AS snippet
                     FROM records r {} ORDER BY r.updated_at DESC LIMIT ?""".format(
                ("WHERE " + " AND ".join(where)) if where else "")
            rows = self.conn.execute(sql, args + [limit]).fetchall()
        out = [row_dict(r) for r in rows]
        for r in out:
            r.pop("score", None)
            r["contradicted_by"] = self._contradiction_ids(r["id"])
        return out

    def find_near_duplicates(self, title, description, limit=5):
        q = _fts_query(title)
        if not q:
            return []
        cands = self.conn.execute(
            """SELECT r.id,r.title,r.description FROM records_fts JOIN records r ON r.rowid=records_fts.rowid
               WHERE records_fts MATCH ? ORDER BY bm25(records_fts) LIMIT 20""", (q,)).fetchall()
        probe = (title + " " + description).lower()
        hits = []
        for c in cands:
            sm = difflib.SequenceMatcher(None, probe, (c["title"] + " " + c["description"]).lower())
            if sm.real_quick_ratio() < NEAR_DUP_RATIO or sm.quick_ratio() < NEAR_DUP_RATIO:
                continue                     # cheap upper bounds; skips the slow ratio() on a phone
            ratio = sm.ratio()
            if ratio >= NEAR_DUP_RATIO:
                hits.append({"id": c["id"], "title": c["title"], "similarity": round(ratio, 3)})
        return sorted(hits, key=lambda h: -h["similarity"])[:limit]

    def _contradiction_ids(self, rid):
        return [r[0] for r in self.conn.execute(
            """SELECT src FROM links WHERE dst=? AND relation='contradicts'
               UNION SELECT dst FROM links WHERE src=? AND relation='contradicts'""", (rid, rid))]

    def contradictions(self, rid):
        ids = self._contradiction_ids(rid)
        return [self.get(i) for i in ids]

    def stale(self, days=30, limit=50):
        """Findings whose verification is older than `days` (or never verified)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
        return [row_dict(r) for r in self.conn.execute(
            """SELECT id,title,status,last_verified_at,updated_at FROM records
               WHERE kind IN ('finding','hypothesis','observation') AND status NOT IN ('rejected')
               AND COALESCE(last_verified_at, discovered_at) < ? ORDER BY COALESCE(last_verified_at, discovered_at)
               LIMIT ?""", (cutoff, limit))]

    def stats(self):
        q = lambda sql: [row_dict(r) for r in self.conn.execute(sql)]
        return {
            "records": self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0],
            "by_status": q("SELECT status, COUNT(*) n FROM records GROUP BY status"),
            "by_category": q("SELECT category, COUNT(*) n FROM records GROUP BY category"),
            "versions": self.conn.execute("SELECT COUNT(*) FROM record_versions").fetchone()[0],
            "links": self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0],
        }
