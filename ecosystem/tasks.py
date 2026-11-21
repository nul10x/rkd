"""Task queue with hard budgets. Sequential: one running task per agent.

Every task has an objective, a completion condition and a budget. Spending
past any budget limit pauses the task with its progress kept, so nothing
runs in an unlimited loop.
"""
import json
from datetime import date

from .db import load_limits, next_id, now, row_dict

BUDGET_KEYS = ("model_requests", "max_minutes", "max_pages", "max_retries")


class BudgetExceeded(RuntimeError):
    pass


class ProviderPaused(RuntimeError):
    pass


class TaskQueue:
    def __init__(self, conn, limits=None):
        self.conn = conn
        self.limits = limits if limits is not None else load_limits()

    def _default_budget(self):
        return dict(self.limits.get("task_defaults", {
            "model_requests": 5, "max_minutes": 15, "max_pages": 20, "max_retries": 2}))

    def add(self, agent, objective, done_condition, created_by, budget=None, priority=5):
        if not objective or not done_condition:
            raise ValueError("a task needs an objective and a done_condition")
        b = self._default_budget()
        b.update(budget or {})
        cap = self.limits.get("task_caps", {})
        for k, v in b.items():
            if k in cap and v > cap[k]:
                raise ValueError("budget {}={} exceeds cap {}".format(k, v, cap[k]))
        ts = now()
        with self.conn:
            tid = next_id(self.conn, "T", "tasks")
            self.conn.execute(
                """INSERT INTO tasks(id,agent,objective,done_condition,budget,priority,created_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (tid, agent, objective, done_condition, json.dumps(b), priority, created_by, ts, ts))
        return tid

    def get(self, tid):
        r = row_dict(self.conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())
        if r:
            for k in ("budget", "used", "progress"):
                r[k] = json.loads(r[k])
        return r

    def claim(self, agent):
        """Start the next queued task for `agent`, unless it already runs one."""
        with self.conn:
            if self.conn.execute("SELECT 1 FROM tasks WHERE agent=? AND status='running'", (agent,)).fetchone():
                return None
            r = self.conn.execute(
                """SELECT id FROM tasks WHERE agent=? AND status IN ('queued','paused')
                   ORDER BY status='paused' DESC, priority, created_at LIMIT 1""", (agent,)).fetchone()
            if not r:
                return None
            self.conn.execute("UPDATE tasks SET status='running', updated_at=? WHERE id=?", (now(), r["id"]))
        return self.get(r["id"])

    def spend(self, tid, key, amount=1, progress=None):
        """Count usage. Pauses the task and raises BudgetExceeded past its limit."""
        t = self.get(tid)
        used = t["used"]
        used[key] = used.get(key, 0) + amount
        prog = dict(t["progress"], **(progress or {}))
        limit = t["budget"].get(key)
        over = limit is not None and used[key] > limit
        with self.conn:
            self.conn.execute(
                "UPDATE tasks SET used=?, progress=?, status=?, error=?, updated_at=? WHERE id=?",
                (json.dumps(used), json.dumps(prog), "paused" if over else t["status"],
                 "budget exceeded: {}".format(key) if over else t["error"], now(), tid))
        if over:
            raise BudgetExceeded("{} over budget for {} ({}/{})".format(tid, key, used[key], limit))
        return used

    def checkpoint(self, tid, progress):
        t = self.get(tid)
        with self.conn:
            self.conn.execute("UPDATE tasks SET progress=?, updated_at=? WHERE id=?",
                              (json.dumps(dict(t["progress"], **progress)), now(), tid))

    def finish(self, tid, status="done", error=None):
        if status not in ("done", "failed", "cancelled", "paused"):
            raise ValueError("bad final status")
        with self.conn:
            self.conn.execute("UPDATE tasks SET status=?, error=?, updated_at=? WHERE id=?",
                              (status, error, now(), tid))

    def list(self, agent=None, status=None):
        sql, args = "SELECT id,agent,status,priority,objective,error FROM tasks WHERE 1=1", []
        if agent:
            sql += " AND agent=?"; args.append(agent)
        if status:
            sql += " AND status=?"; args.append(status)
        return [row_dict(r) for r in self.conn.execute(sql + " ORDER BY created_at", args)]

    # ---------- free-tier provider budget ----------
    def provider_request(self, provider):
        """Count one external API request. Raises ProviderPaused at the daily cap
        or while a rate-limit pause is active. Never retries by itself."""
        day = date.today().isoformat()
        cap = self.limits.get("providers", {}).get(provider, {}).get("daily_requests")
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO api_usage(provider,day) VALUES (?,?)", (provider, day))
            r = self.conn.execute("SELECT requests,paused_until FROM api_usage WHERE provider=? AND day=?",
                                  (provider, day)).fetchone()
            if r["paused_until"] and r["paused_until"] > now():
                raise ProviderPaused("{} paused until {}".format(provider, r["paused_until"]))
            if cap is not None and r["requests"] >= cap:
                raise ProviderPaused("{} reached its daily cap of {}".format(provider, cap))
            self.conn.execute("UPDATE api_usage SET requests=requests+1 WHERE provider=? AND day=?", (provider, day))
        return r["requests"] + 1

    def provider_rate_limited(self, provider, until_iso):
        day = date.today().isoformat()
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO api_usage(provider,day) VALUES (?,?)", (provider, day))
            self.conn.execute("UPDATE api_usage SET paused_until=? WHERE provider=? AND day=?",
                              (until_iso, provider, day))
