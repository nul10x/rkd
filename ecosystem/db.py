"""SQLite connection and schema bootstrap. Standard library only."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("RKD_DB", ROOT / "data" / "logbook.db"))


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_day():
    """Today's date in UTC; provider quotas reset at UTC midnight."""
    return datetime.now(timezone.utc).date().isoformat()


def set_journal(conn):
    """WAL when the filesystem supports it. Android shared storage (/sdcard)
    has no shared-memory support, so fall back to the rollback journal."""
    try:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    except sqlite3.OperationalError:
        mode = None
    if mode not in ("wal", "memory"):
        mode = conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
    return mode


def load_schema(conn):
    try:
        conn.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    except sqlite3.OperationalError as e:
        if "fts5" in str(e).lower():
            raise RuntimeError("this Python's SQLite has no FTS5 module; install a Python/SQLite "
                               "build with FTS5 (Termux: pkg install python)") from e
        raise


def connect(path=None):
    path = Path(os.path.expanduser(str(path or DEFAULT_DB)))
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    set_journal(conn)                              # crash-safe, low memory
    conn.execute("PRAGMA cache_size = -2000")      # ~2 MB page cache
    load_schema(conn)
    conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES ('schema_version',?)", (SCHEMA_VERSION,))
    conn.commit()
    return conn


def next_id(conn, prefix, table):
    row = conn.execute(
        "SELECT id FROM {} WHERE id LIKE ? ORDER BY rowid DESC LIMIT 1".format(table), (prefix + "-%",)
    ).fetchone()
    n = int(row["id"].split("-")[1]) + 1 if row else 1
    return "{}-{:06d}".format(prefix, n)


def row_dict(row):
    return dict(row) if row is not None else None


def load_limits():
    p = ROOT / "config" / "limits.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
