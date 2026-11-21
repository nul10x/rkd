"""Agent communication protocol rkd/1: JSON envelopes, persisted in `messages`.

Envelope:
{
  "protocol": "rkd/1",
  "id": "M-...",            (assigned if missing)
  "from": "researcher",
  "to": "logbook",
  "type": "submit_record" | "update_record" | "link" | "query" | "get" | "history"
          | "contradictions" | "stale" | "task_add" | "task_report",
  "reply_to": null,
  "payload": {...}
}
Replies use type "result" or "error" with reply_to set to the request id.
"""
import json
import uuid

from .db import now
from .logbook import DuplicateRecord, Logbook, LogbookError
from .tasks import TaskQueue

PROTOCOL = "rkd/1"
AGENTS = ("researcher", "logbook", "builder", "validator", "coordinator", "user")


class ProtocolError(ValueError):
    pass


def make(frm, to, type_, payload, reply_to=None):
    return {"protocol": PROTOCOL, "id": "M-" + uuid.uuid4().hex[:12], "from": frm, "to": to,
            "type": type_, "reply_to": reply_to, "payload": payload}


def validate(msg):
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a JSON object")
    if msg.get("protocol") != PROTOCOL:
        raise ProtocolError("protocol must be " + PROTOCOL)
    for f in ("from", "to", "type", "payload"):
        if f not in msg:
            raise ProtocolError("missing field: " + f)
    for f in ("from", "to"):
        if msg[f] not in AGENTS:
            raise ProtocolError("unknown agent: {}".format(msg[f]))
    if not isinstance(msg["payload"], dict):
        raise ProtocolError("payload must be an object")
    msg.setdefault("id", "M-" + uuid.uuid4().hex[:12])
    return msg


def _store(conn, msg, status="new"):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO messages(id,from_agent,to_agent,type,reply_to,payload,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (msg["id"], msg["from"], msg["to"], msg["type"], msg.get("reply_to"),
             json.dumps(msg["payload"]), status, now()))


def handle(conn, msg):
    """Validate, persist and dispatch one message addressed to the logbook.
    Returns the reply envelope (also persisted)."""
    msg = validate(msg)
    _store(conn, msg)
    lb, q, p = Logbook(conn), TaskQueue(conn), msg["payload"]
    try:
        t = msg["type"]
        if t == "submit_record":
            rec = dict(p["record"], created_by=msg["from"])
            data = lb.save(rec, p.get("sources", []), p.get("links", []),
                           allow_near_duplicate=p.get("allow_near_duplicate", False))
        elif t == "update_record":
            data = lb.update(p["id"], p["changes"], msg["from"], p.get("note"), p.get("sources", []))
        elif t == "link":
            lb.link(p["src"], p["dst"], p["relation"], msg["from"], p.get("note"))
            data = {"linked": True}
        elif t == "query":
            data = {"results": lb.search(p.get("text"), p.get("category"), p.get("status"),
                                         p.get("kind"), p.get("limit", 10))}
        elif t == "get":
            data = lb.get(p["id"])
        elif t == "history":
            data = {"versions": lb.history(p["id"])}
        elif t == "contradictions":
            data = {"contradicted_by": lb.contradictions(p["id"])}
        elif t == "stale":
            data = {"stale": lb.stale(p.get("days", 30))}
        elif t == "task_add":
            data = {"task_id": q.add(p["agent"], p["objective"], p["done_condition"], msg["from"],
                                     p.get("budget"), p.get("priority", 5))}
        elif t == "task_report":
            q.finish(p["task_id"], p.get("status", "done"), p.get("error"))
            data = {"task": q.get(p["task_id"])}
        else:
            raise ProtocolError("unknown type: " + t)
        reply = make("logbook", msg["from"], "result", {"ok": True, "data": data}, msg["id"])
        status = "handled"
    except DuplicateRecord as e:
        reply = make("logbook", msg["from"], "error",
                     {"ok": False, "error": str(e), "duplicate_of": e.existing_id, "duplicate_kind": e.kind}, msg["id"])
        status = "error"
    except (LogbookError, ProtocolError, KeyError, ValueError) as e:
        reply = make("logbook", msg["from"], "error", {"ok": False, "error": "{}: {}".format(type(e).__name__, e)}, msg["id"])
        status = "error"
    with conn:
        conn.execute("UPDATE messages SET status=? WHERE id=?", (status, msg["id"]))
    _store(conn, reply, "handled")
    return reply
