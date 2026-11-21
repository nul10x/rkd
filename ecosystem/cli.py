"""Command line for agents and the user.

  python3 -m ecosystem.cli msg  [file.json|-]      send one rkd/1 message to the logbook
  python3 -m ecosystem.cli search "dev wallet" [--status validated] [--category developer_behaviour]
  python3 -m ecosystem.cli get KR-000001
  python3 -m ecosystem.cli history KR-000001
  python3 -m ecosystem.cli stale [--days 30]
  python3 -m ecosystem.cli tasks [--agent researcher]
  python3 -m ecosystem.cli stats
"""
import argparse
import json
import sys

from .db import connect
from .logbook import Logbook
from .protocol import handle
from .tasks import TaskQueue


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ecosystem")
    ap.add_argument("--db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("msg"); m.add_argument("file", nargs="?", default="-")
    s = sub.add_parser("search"); s.add_argument("text", nargs="?")
    s.add_argument("--status"); s.add_argument("--category"); s.add_argument("--kind")
    s.add_argument("--limit", type=int, default=10)
    for name in ("get", "history"):
        sub.add_parser(name).add_argument("id")
    st = sub.add_parser("stale"); st.add_argument("--days", type=int, default=30)
    t = sub.add_parser("tasks"); t.add_argument("--agent"); t.add_argument("--status")
    sub.add_parser("stats")
    a = ap.parse_args(argv)

    conn = connect(a.db)
    lb = Logbook(conn)
    if a.cmd == "msg":
        raw = sys.stdin.read() if a.file == "-" else open(a.file).read()
        out = handle(conn, json.loads(raw))
    elif a.cmd == "search":
        out = lb.search(a.text, a.category, a.status, a.kind, a.limit)
    elif a.cmd == "get":
        out = lb.get(a.id)
    elif a.cmd == "history":
        out = lb.history(a.id)
    elif a.cmd == "stale":
        out = lb.stale(a.days)
    elif a.cmd == "tasks":
        out = TaskQueue(conn).list(a.agent, a.status)
    else:
        out = lb.stats()
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0 if not (isinstance(out, dict) and out.get("type") == "error") else 1


if __name__ == "__main__":
    sys.exit(main())
