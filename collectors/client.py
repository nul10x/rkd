"""Read-only, cached, throttled HTTP client for the research collectors.

- Every successful response is cached as raw JSON under data/raw/<provider>/<sha256>.json.
  A cache hit makes no network call, so re-runs reproduce the numbers offline.
- Every network call is counted in data/raw/usage.json and checked against a hard budget.
- Throttle: at most RKD_RPS requests per second (default 2).
- HTTP 429 or a JSON-RPC rate-limit error stops the run (RateLimited). Nothing retries.
- The Helius key is read from the HELIUS_API_KEY environment variable only and is never written
  to disk or logs (cache keys hash the method and params, never the URL).
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("RKD_RAW", os.path.join(ROOT, "data", "raw"))
USAGE = os.path.join(RAW, "usage.json")
BUDGET = int(os.environ.get("RKD_CALL_BUDGET", "500"))
RPS = float(os.environ.get("RKD_RPS", "2"))
UA = "rkd-research/0.1"
_last = [0.0]


class RateLimited(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


def _usage():
    if os.path.exists(USAGE):
        with open(USAGE) as f:
            return json.load(f)
    return {"calls": 0, "by_provider": {}, "errors": [], "rate_limited": None}


def _save_usage(u):
    os.makedirs(RAW, exist_ok=True)
    with open(USAGE, "w") as f:
        json.dump(u, f, indent=1)


def calls_used():
    return _usage()["calls"]


def _cache_path(provider, key_obj):
    h = hashlib.sha256(json.dumps(key_obj, sort_keys=True).encode()).hexdigest()
    return os.path.join(RAW, provider, h + ".json")


def _fetch(provider, url, body, label):
    u = _usage()
    if u.get("rate_limited"):
        raise RateLimited("an earlier run hit a rate limit: " + json.dumps(u["rate_limited"]))
    if u["calls"] >= BUDGET:
        raise BudgetExceeded("call budget {} reached".format(BUDGET))
    wait = _last[0] + 1.0 / RPS - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    u["calls"] += 1
    u["by_provider"][provider] = u["by_provider"].get(provider, 0) + 1
    _save_usage(u)
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
            u = _usage()
            u["rate_limited"] = {"provider": provider, "label": label, "at": time.time()}
            _save_usage(u)
            raise RateLimited("{} HTTP 429 on {}".format(provider, label))
        u = _usage()
        u["errors"].append({"provider": provider, "label": label, "http": e.code, "body": text})
        _save_usage(u)
        raise ApiError("{} HTTP {} on {}: {}".format(provider, e.code, label, text))
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        code = err.get("code") if isinstance(err, dict) else None
        msg = json.dumps(err)[:300]
        u = _usage()
        if code == 429 or "rate" in msg.lower() and "limit" in msg.lower():
            u["rate_limited"] = {"provider": provider, "label": label, "at": time.time(), "error": msg}
            _save_usage(u)
            raise RateLimited("{} rate limit on {}: {}".format(provider, label, msg))
        u["errors"].append({"provider": provider, "label": label, "rpc_error": msg})
        _save_usage(u)
        raise ApiError("{} error on {}: {}".format(provider, label, msg))
    return payload


def cached(provider, key_obj, url, body, label):
    path = _cache_path(provider, key_obj)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)["response"]
    resp = _fetch(provider, url, body, label)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"request": key_obj, "fetched_at": time.time(), "response": resp}, f)
    return resp


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
