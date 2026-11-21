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


def connect(path=None):
    path = Path(path or DEFAULT_DB)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")      # crash-safe, low memory
    conn.execute("PRAGMA cache_size = -2000")      # ~2 MB page cache
    conn.executescript((Path(__file__).parent / "schema.sql").read_text())
    conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES ('schema_version',?)", (SCHEMA_VERSION,))
    conn.commit()
    return conn


def next_id(conn, prefix, table):
    row = conn.execute(
        "SELECT id FROM {} WHERE id LIKE ? ORDER BY id DESC LIMIT 1".format(table), (prefix + "-%",)
    ).fetchone()
    n = int(row["id"].split("-")[1]) + 1 if row else 1
    return "{}-{:06d}".format(prefix, n)


def row_dict(row):
    return dict(row) if row is not None else None


def load_limits():
    p = ROOT / "config" / "limits.json"
    return json.loads(p.read_text()) if p.exists() else {}
