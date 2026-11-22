"""Read-only, cached, throttled HTTP client for the research collectors.

- Every successful response is cached as raw JSON under data/raw/<provider>/<sha256>.json.
  A cache hit makes no network call, so re-runs reproduce the numbers offline.
- live() is the second path, for current state (price, liquidity, holders): it always fetches
  (or reuses a snapshot younger than max_age_s) and keeps each response as a timestamped snapshot
  under data/raw/<provider>/live/<UTC day>/. Same throttle, pauses and budget as cached().
- Every network call is counted in the usage file (RKD_USAGE, default data/raw/usage.json) and
  checked against a hard budget. Rejected requests count too.
- Throttle, held across processes through data/raw/throttle.sqlite: each provider has a minimum
  interval between calls (MIN_INTERVAL), and all providers together stay under RKD_RPS per second.
- HTTP 429 or a JSON-RPC rate-limit error stops the run (RateLimited). Nothing retries.
  The provider is then paused until Retry-After, or for DEFAULT_PAUSE (at least MIN_PAUSE).
  The pause covers that provider only and is shared by every usage file and process.
- Usage and cache files are written atomically (temp file in the same folder, then os.replace).
  An unreadable usage file is moved aside to <name>.corrupt-<unix> and its call count is salvaged.
- The Helius key is read from the HELIUS_API_KEY environment variable only and is never written
  to disk or logs (cache keys hash the method and params, never the URL).
"""
import email.utils
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("RKD_RAW", os.path.join(ROOT, "data", "raw"))
USAGE = os.environ.get("RKD_USAGE", os.path.join(RAW, "usage.json"))  # one counter file per study run
BUDGET = int(os.environ.get("RKD_CALL_BUDGET", "500"))
RPS = float(os.environ.get("RKD_RPS", "2"))  # global ceiling across providers and processes
UA = "rkd-research/0.1"

# Minimum seconds between two calls to the same provider, across processes.
MIN_INTERVAL = {"geckoterminal": 15.0, "dexscreener": 0.5, "helius": 0.5, "robinhood_rpc": 0.5}
DEFAULT_INTERVAL = 0.5
# Pause after a rate limit when the server sends no Retry-After. MIN_PAUSE is a floor for both cases.
DEFAULT_PAUSE = 900.0
MIN_PAUSE = {"geckoterminal": 1800.0}
LOCK_TIMEOUT = 900  # seconds a process waits for another one's throttle slot

_now = time.time  # patched in tests
_sleep = time.sleep


class RateLimited(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


# ---------- files ----------

def _atomic_write_json(path, obj, **dump_kw):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, **dump_kw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fresh_usage():
    return {"calls": 0, "by_provider": {}, "errors": [], "paused": {}}


def _migrate(u):
    """Fill missing keys and turn the old global 'rate_limited' record into a per-provider pause."""
    fresh = _fresh_usage()
    for k, v in fresh.items():
        if not isinstance(u.get(k), type(v)):
            u[k] = v
    old = u.pop("rate_limited", None)
    if isinstance(old, dict):
        p = old.get("provider") or "*"
        at = float(old.get("at") or 0)
        rec = dict(old, at=at, until=at + _pause_seconds(p, None), migrated=True)
        rec.pop("provider", None)
        cur = u["paused"].get(p)
        if not isinstance(cur, dict) or float(cur.get("until") or 0) < rec["until"]:
            u["paused"][p] = rec
    return u


def _usage():
    if not os.path.exists(USAGE):
        return _fresh_usage()
    text = ""
    try:
        with open(USAGE, encoding="utf-8") as f:
            text = f.read()
        u = json.loads(text)
        if not isinstance(u, dict):
            raise ValueError("usage file is not a JSON object")
    except (ValueError, OSError) as e:
        return _recover_usage(text, e)
    return _migrate(u)


def _recover_usage(text, err):
    """A half-written usage file (from a killed run) must not stop later runs, nor reset the budget."""
    bad = "{}.corrupt-{}".format(USAGE, int(_now()))
    try:
        os.replace(USAGE, bad)
    except OSError:
        bad = None
    u = _fresh_usage()
    m = re.search(r'"calls"\s*:\s*(\d+)', text or "")
    if m:
        u["calls"] = int(m.group(1))
    u["recovered"] = {"from": bad, "at": _now(), "error": str(err)[:200], "calls_salvaged": bool(m)}
    _save_usage(u)
    return u


def _save_usage(u):
    _atomic_write_json(USAGE, u, indent=1)


def calls_used():
    return _usage()["calls"]


def _cache_path(provider, key_obj):
    h = hashlib.sha256(json.dumps(key_obj, sort_keys=True).encode()).hexdigest()
    return os.path.join(RAW, provider, h + ".json")


# ---------- shared throttle and pauses ----------

def _db():
    os.makedirs(RAW, exist_ok=True)
    c = sqlite3.connect(os.path.join(RAW, "throttle.sqlite"), timeout=LOCK_TIMEOUT, isolation_level=None)
    c.execute("CREATE TABLE IF NOT EXISTS last_call(provider TEXT PRIMARY KEY, t REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS pause(provider TEXT PRIMARY KEY, until REAL NOT NULL, info TEXT)")
    return c


def _pause_seconds(provider, retry_after):
    floor = MIN_PAUSE.get(provider, 0.0)
    if retry_after is None:
        return max(DEFAULT_PAUSE, floor)
    return max(float(retry_after), floor)


def _parse_retry_after(value):
    """Retry-After is either seconds or an HTTP date. Returns seconds from now, or None."""
    if value is None:
        return None
    value = str(value).strip()
    if value.isdigit():
        return float(value)
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    return max(0.0, dt.timestamp() - _now())


def _paused_until(provider, u, c=None):
    best = 0.0
    for p in (provider, "*"):
        rec = u["paused"].get(p)
        if isinstance(rec, dict):
            best = max(best, float(rec.get("until") or 0))
    if c is not None:
        for (until,) in c.execute("SELECT until FROM pause WHERE provider IN (?,?)", (provider, "*")):
            best = max(best, until)
    return best


def paused_until(provider):
    """Unix time until which `provider` is paused (0.0 = not paused or never was). Reads only."""
    u = _usage()
    path = os.path.join(RAW, "throttle.sqlite")
    if not os.path.exists(path):
        return _paused_until(provider, u)
    c = _db()
    try:
        return _paused_until(provider, u, c)
    finally:
        c.close()


def _check_pause(provider, u, c):
    until = _paused_until(provider, u, c)
    if until > _now():
        raise RateLimited("{} is paused after a rate limit until {} UTC".format(
            provider, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(until))))


def _reserve(provider):
    """Under the shared lock: check pause and budget, wait for the provider's slot, count the call."""
    c = _db()
    try:
        c.execute("BEGIN IMMEDIATE")
        u = _usage()
        _check_pause(provider, u, c)
        if u["calls"] >= BUDGET:
            raise BudgetExceeded("call budget {} reached".format(BUDGET))
        last = dict(c.execute("SELECT provider,t FROM last_call WHERE provider IN (?,?)", (provider, "*")))
        ready = max(last.get(provider, 0.0) + MIN_INTERVAL.get(provider, DEFAULT_INTERVAL),
                    last.get("*", 0.0) + 1.0 / RPS)
        wait = ready - _now()
        if wait > 0:
            _sleep(wait)
        t = _now()
        c.executemany("INSERT OR REPLACE INTO last_call(provider,t) VALUES (?,?)", [(provider, t), ("*", t)])
        u["calls"] += 1
        u["by_provider"][provider] = u["by_provider"].get(provider, 0) + 1
        _save_usage(u)
        c.execute("COMMIT")
    except BaseException:
        if c.in_transaction:
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def _record_pause(provider, label, retry_after, extra=None):
    at = _now()
    rec = {"until": at + _pause_seconds(provider, retry_after), "at": at, "label": label,
           "retry_after": retry_after}
    rec.update(extra or {})
    u = _usage()
    u["paused"][provider] = rec
    _save_usage(u)
    c = _db()
    try:
        c.execute("INSERT OR REPLACE INTO pause(provider,until,info) VALUES (?,?,?)",
                  (provider, rec["until"], json.dumps(rec)))
    finally:
        c.close()
    return rec


# ---------- requests ----------

def _logbook_count(provider):
    """Opt-in (RKD_LOGBOOK_COUNT=1): count the request in the Logbook's api_usage (daily caps from
    config/limits.json apply) and, with RKD_TASK=<task id>, in that task's 'api_calls' budget.
    Off by default so tests and offline analysis never write to the shared Logbook."""
    if os.environ.get("RKD_LOGBOOK_COUNT") != "1":
        return
    from ecosystem.db import connect
    from ecosystem.tasks import TaskQueue
    conn = connect(os.environ.get("RKD_DB") or None)
    try:
        q = TaskQueue(conn)
        q.provider_request(provider)
        if os.environ.get("RKD_TASK"):
            q.spend(os.environ["RKD_TASK"], "api_calls")
    finally:
        conn.close()


def _logbook_pause(provider, until_ts):
    if os.environ.get("RKD_LOGBOOK_COUNT") != "1":
        return
    from ecosystem.db import connect
    from ecosystem.tasks import TaskQueue
    import datetime as _dt
    conn = connect(os.environ.get("RKD_DB") or None)
    try:
        iso = _dt.datetime.fromtimestamp(until_ts, tz=_dt.timezone.utc).isoformat()
        TaskQueue(conn).provider_rate_limited(provider, iso)
    finally:
        conn.close()


def _fetch(provider, url, body, label):
    u = _usage()
    _check_pause(provider, u, None)  # cheap early check; repeated under the lock in _reserve
    _reserve(provider)
    _logbook_count(provider)
    headers = {"User-Agent": UA, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")[:300]
        if e.code == 429:
            ra = _parse_retry_after(e.headers.get("Retry-After") if e.headers else None)
            rec = _record_pause(provider, label, ra)
            _logbook_pause(provider, rec["until"])
            raise RateLimited("{} HTTP 429 on {}; paused for {:.0f} s".format(provider, label, rec["until"] - rec["at"]))
        u = _usage()
        u["errors"].append({"provider": provider, "label": label, "http": e.code, "body": text})
        _save_usage(u)
        raise ApiError("{} HTTP {} on {}: {}".format(provider, e.code, label, text))
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        code = err.get("code") if isinstance(err, dict) else None
        msg = json.dumps(err)[:300]
        if code == 429 or "rate" in msg.lower() and "limit" in msg.lower():
            rec = _record_pause(provider, label, None, {"error": msg})
            _logbook_pause(provider, rec["until"])
            raise RateLimited("{} rate limit on {}; paused for {:.0f} s: {}".format(
                provider, label, rec["until"] - rec["at"], msg))
        u = _usage()
        u["errors"].append({"provider": provider, "label": label, "rpc_error": msg})
        _save_usage(u)
        raise ApiError("{} error on {}: {}".format(provider, label, msg))
    return payload


def cached(provider, key_obj, url, body, label):
    path = _cache_path(provider, key_obj)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)["response"]
    resp = _fetch(provider, url, body, label)
    _atomic_write_json(path, {"request": key_obj, "fetched_at": time.time(), "response": resp})
    return resp


def _live_dir(provider, ts):
    day = time.strftime("%Y-%m-%d", time.gmtime(ts))
    return os.path.join(RAW, provider, "live", day)


def live(provider, key_obj, url, body, label, max_age_s=0):
    """Fresh fetch for current state (price, liquidity, holders, authorities). Never a forever-cache hit.

    Every response is kept as a timestamped snapshot: RAW/<provider>/live/<UTC day>/<unix>_<sha12>.json
    holding request, fetched_at and response. With max_age_s > 0 the newest snapshot of the same request
    that is younger than max_age_s is reused (no network call), so repeated commands spare free limits.
    The key_obj is what identifies the request; it must not contain secrets (the URL is never stored).
    Returns {"response", "fetched_at", "raw_path", "reused"}.
    """
    h = hashlib.sha256(json.dumps(key_obj, sort_keys=True).encode()).hexdigest()[:12]
    now = _now()
    if max_age_s and max_age_s > 0:
        best = None
        for ts in (now, now - 86400):
            d = _live_dir(provider, ts)
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                if not name.endswith("_" + h + ".json"):
                    continue
                try:
                    t = int(name.split("_", 1)[0])
                except ValueError:
                    continue
                if now - t <= max_age_s and (best is None or t > best[0]):
                    best = (t, os.path.join(d, name))
        if best:
            with open(best[1], encoding="utf-8") as f:
                snap = json.load(f)
            return {"response": snap["response"], "fetched_at": snap["fetched_at"],
                    "raw_path": best[1], "reused": True}
    resp = _fetch(provider, url, body, label)
    fetched = _now()
    path = os.path.join(_live_dir(provider, fetched), "{}_{}.json".format(int(fetched), h))
    _atomic_write_json(path, {"request": key_obj, "fetched_at": fetched, "response": resp})
    return {"response": resp, "fetched_at": fetched, "raw_path": path, "reused": False}


def helius_live(method, params, max_age_s=0):
    """JSON-RPC on Helius, fresh (see live()). Result is under ["response"]["result"]."""
    key = os.environ.get("HELIUS_API_KEY")
    if not key:
        raise ApiError("HELIUS_API_KEY is not set")
    url = "https://mainnet.helius-rpc.com/?api-key=" + key
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return live("helius", {"method": method, "params": params}, url, body, method, max_age_s)


def dexscreener_token_pairs_live(chain, token, max_age_s=0):
    """GET /token-pairs/v1/{chain}/{token}: all pools of one token (published limit 300 req/min). Fresh."""
    url = "https://api.dexscreener.com/token-pairs/v1/{}/{}".format(chain, token)
    return live("dexscreener", {"token_pairs": [chain, token]}, url, None, "token-pairs/v1", max_age_s)


def helius_rpc(method, params):
    key = os.environ.get("HELIUS_API_KEY")
    key_obj = {"method": method, "params": params}
    path = _cache_path("helius", key_obj)
    if not os.path.exists(path) and not key:
        raise ApiError("HELIUS_API_KEY is not set")
    url = "https://mainnet.helius-rpc.com/?api-key=" + (key or "")
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return cached("helius", key_obj, url, body, method)["result"]


def dexscreener_tokens(mints):
    """GET /tokens/v1/solana/{up to 30 comma-separated mints}. 300 req/min published limit."""
    assert 0 < len(mints) <= 30
    mints = sorted(mints)
    url = "https://api.dexscreener.com/tokens/v1/solana/" + ",".join(mints)
    return cached("dexscreener", {"tokens": mints}, url, None, "tokens/v1")


ROBINHOOD_RPC = os.environ.get("RH_RPC_URL", "https://rpc.mainnet.chain.robinhood.com")  # public, rate limited


def evm_rpc(method, params, provider="robinhood_rpc", url=None):
    """JSON-RPC on an EVM chain (default: Robinhood Chain public RPC). Cached like helius_rpc.
    Do not use for 'latest'-dependent calls you need fresh: the cache key is method+params."""
    key_obj = {"method": method, "params": params}
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return cached(provider, key_obj, url or ROBINHOOD_RPC, body, method)["result"]


def dexscreener_tokens_chain(chain, mints):
    """GET /tokens/v1/{chain}/{<=30 addresses}."""
    assert 0 < len(mints) <= 30
    mints = sorted(mints)
    url = "https://api.dexscreener.com/tokens/v1/{}/{}".format(chain, ",".join(mints))
    return cached("dexscreener", {"chain": chain, "tokens": mints}, url, None, "tokens/v1")
