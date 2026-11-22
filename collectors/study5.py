"""Study 5 collector + analysis (plan KR-000047, amended after pilot KR-000048).

One code path, two data sources: `collect` makes cached calls through collectors/client.py; `analyse` reads
data/raw only (no network; an uncached response counts as missing).

  python3 -m collectors.study5 collect primary|holdout|pump
  python3 -m collectors.study5 analyse primary|holdout|pump      # writes data/exports/study5_<set>_stats.json/_tokens.csv
Env (collect): RKD_USAGE=data/raw/usage_study5.json RKD_CALL_BUDGET=900 RKD_LOGBOOK_COUNT=1 RKD_TASK=T-000010 HELIUS_API_KEY=...
"""
import calendar
import csv
import json
import os
import random
import statistics
import sys

from collectors import client
from research import study5_parse as P
from research.pump import account_keys
from research.stats import bootstrap, newcombe_diff, wilson
from tools.token_scanner import token_scanner as T

FULL = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}
FEE_RECEIVER = "DNXgeM9EiiaAbaWvwjHj9fQQLAX5ZsfHyvmYUNRAdNC8"
DAY = 86400
MAX_POOL_PAGES = 10  # per day
MAX_AUTH_PAGES = 3
NEW_WINDOW = 30 * DAY
SETS = {"primary": ("2026-10-01", 35), "holdout": ("2026-11-05", 10)}


def day_start(day):
    return calendar.timegm((int(day[:4]), int(day[5:7]), int(day[8:10]), 0, 0, 0))


def days(name):
    first, n = SETS[name]
    t = day_start(first)
    return [t + i * DAY for i in range(n)]


# ---------- requests (identical params live and offline) ----------

def pool_page_params(t, token=None):
    opts = dict(FULL, sortOrder="asc", limit=100, filters={"blockTime": {"gte": t, "lt": t + DAY}, "status": "succeeded"})
    if token:
        opts["paginationToken"] = token
    return [FEE_RECEIVER, opts]


def first_tx_params(mint):
    return [mint, {"transactionDetails": "signatures", "sortOrder": "asc", "limit": 1, "filters": {"status": "succeeded"}}]


def auth_params(auth, t0, token=None):
    opts = dict(FULL, sortOrder="asc", limit=100, filters={"blockTime": {"gte": t0, "lte": t0 + 7 * DAY}, "status": "succeeded"})
    if token:
        opts["paginationToken"] = token
    return [auth, opts]


def live(method, params):
    return client.helius_rpc(method, params)


def cache(method, params):
    p = client._cache_path("helius", {"method": method, "params": params})
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)["response"]["result"]


def paged(rpc, make, max_pages):
    """(txs, complete) following paginationToken up to max_pages."""
    txs, token = [], None
    for _ in range(max_pages):
        r = rpc("getTransactionsForAddress", make(token))
        if r is None:
            return txs, False
        txs += r["data"]
        token = r.get("paginationToken")
        if not token or len(r["data"]) < 100:
            return txs, True
    return txs, False


def mint_states(rpc, mints):
    out, ms = {}, sorted(mints)
    for i in range(0, len(ms), 100):
        r = rpc("getMultipleAccounts", [ms[i:i + 100], {"encoding": "jsonParsed"}])
        if r is None:
            continue
        for m, a in zip(ms[i:i + 100], r["value"]):
            out[m] = a
    return out


def _caps(a):
    facts = T.mint_facts(a)[0] if a else None
    if facts is None:
        return None, None
    raw = ((a.get("data") or {}).get("parsed") or {}).get("info", {}).get("extensions") or []
    return facts, P.capabilities(facts, raw)


# ---------- build (collection order == analysis input) ----------

def build_cpmm(name, rpc):
    rows, meta = {}, []
    for t in days(name):
        txs, complete = paged(rpc, lambda tok: pool_page_params(t, tok), MAX_POOL_PAGES)
        meta.append({"day": t, "pool_txs": len(txs), "complete": complete})
        for x in txs:
            for m, lp in P.cpmm_creates(x):
                rows.setdefault(m, {"mint": m, "day": t, "pool_created": x["blockTime"],
                                    "pool_creator": account_keys(x)[0], "launchpad": lp})
    non = sorted(m for m in rows if not rows[m]["launchpad"])
    states = mint_states(rpc, non)
    for m in non:
        r = rows[m]
        facts, caps = _caps(states.get(m))
        if facts is None:
            r["state_missing"] = True
            continue
        r.update(caps)
        r["extensions"] = ";".join(facts["extensions"])
        if not facts["freeze_authority"]:
            continue
        auth = facts["freeze_authority"]
        r["freeze_auth"] = auth
        r["freeze_auth_is_pool_creator"] = auth == r["pool_creator"]
        f = rpc("getTransactionsForAddress", first_tx_params(m))
        first = f["data"][0]["blockTime"] if f and f.get("data") else None
        r["mint_first_tx"] = first
        r["new_token"] = None if first is None else r["pool_created"] - first <= NEW_WINDOW
        if r["new_token"]:
            t0 = r["pool_created"]
            txs, complete = paged(rpc, lambda tok: auth_params(auth, t0, tok), MAX_AUTH_PAGES)
            ev = P.freeze_events(txs, m, auth)
            r.update(auth_txs_seen=len(txs), auth_history_complete=complete, n_freezes=len(ev),
                     n_frozen_owners=len({o for _, _, o in ev}), freeze_used=bool(ev),
                     first_freeze_s=min(bt for bt, _, _ in ev) - t0 if ev else None)
    return [rows[m] for m in sorted(rows)], meta


def build_pump(rpc, n=1000):
    from collectors.stage2_trace import launches
    L = launches("2026-11-11")
    ms = sorted(random.Random("study5-2026-11-11").sample([l["mint"] for l in L], min(n, len(L))))
    states = mint_states(rpc, ms)
    rows = []
    for m in ms:
        facts, caps = _caps(states.get(m))
        rows.append({"mint": m, "state_missing": True} if facts is None else
                    dict({"mint": m, "extensions": ";".join(facts["extensions"])}, **caps))
    return rows


# ---------- statistics ----------

def rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": k / n if n else None, "ci95": [lo, hi]}


CAPS = ("freeze_authority", "mint_authority", "token_2022", "transfer_hook_set", "permanent_delegate_set",
        "default_frozen", "non_transferable", "transfer_fee", "any_sell_block_capability")


def census(rows):
    ok = [r for r in rows if "freeze_authority" in r]
    return dict({"n": len(ok), "state_missing": sum(1 for r in rows if r.get("state_missing"))},
                **{c: rate(sum(1 for r in ok if r[c]), len(ok)) for c in CAPS})


def summarise(rows, meta):
    non = [r for r in rows if not r["launchpad"]]
    out = {"days": len(meta), "pool_txs": sum(d["pool_txs"] for d in meta),
           "days_incomplete": sum(1 for d in meta if not d["complete"]),
           "base_mints": len(rows), "launchpad_migrations": sum(1 for r in rows if r["launchpad"]),
           "census_non_launchpad": census(non)}
    by = {}
    for r in non:
        if "freeze_authority" in r:
            by.setdefault(r["day"], []).append(r["freeze_authority"])

    def share(ds):
        v = [x for d in ds for x in by[d]]
        return sum(v) / len(v) if v else None
    lo, hi, _ = bootstrap(share, sorted(by), n=2000, seed=51)
    out["census_non_launchpad"]["freeze_authority"]["day_bootstrap_ci95"] = [lo, hi]
    fr = [r for r in non if r.get("freeze_authority")]
    new = [r for r in fr if r.get("new_token")]
    seen = [r for r in new if "freeze_used" in r]
    out["freeze_retained"] = {"n": len(fr), "established_excluded": sum(1 for r in fr if r.get("new_token") is False),
                              "first_tx_missing": sum(1 for r in fr if r.get("new_token") is None),
                              "new": len(new), "auth_history_missing": len(new) - len(seen),
                              "auth_history_truncated": sum(1 for r in seen if not r["auth_history_complete"])}
    k = sum(1 for r in seen if r["freeze_used"])
    out["Q5b_freeze_used_given_retained"] = rate(k, len(seen))
    a = [r for r in seen if r["freeze_auth_is_pool_creator"]]
    b = [r for r in seen if not r["freeze_auth_is_pool_creator"]]
    ka, kb = sum(r["freeze_used"] for r in a), sum(r["freeze_used"] for r in b)
    out["Q5c_by_authority_is_pool_creator"] = {"creator": rate(ka, len(a)), "other": rate(kb, len(b)),
                                               "diff": newcombe_diff(ka, len(a), kb, len(b))}
    tf = sorted(r["first_freeze_s"] for r in seen if r["freeze_used"])
    out["Q5c_time_to_first_freeze_s"] = {"n": len(tf), "median": statistics.median(tf) if tf else None,
                                         "p25": tf[len(tf) // 4] if tf else None, "p75": tf[(3 * len(tf)) // 4] if tf else None}
    out["Q5c_frozen_owners_per_used_token_median"] = statistics.median(
        [r["n_frozen_owners"] for r in seen if r["freeze_used"]]) if k else None
    n_all = out["census_non_launchpad"]["n"] - out["freeze_retained"]["established_excluded"]
    out["freeze_used_share_of_all_new_non_launchpad"] = rate(k, n_all)
    out["comparisons_looked_at"] = 3
    return out


def write(name, rows, out):
    ex = os.path.join(client.ROOT, "data", "exports")
    keys = sorted({k for r in rows for k in r})
    with open(os.path.join(ex, "study5_{}_tokens.csv".format(name)), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(ex, "study5_{}_stats.json".format(name)), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps(out, indent=1, sort_keys=True))


def main(cmd, name):
    rpc = live if cmd == "collect" else cache
    if name == "pump":
        rows = build_pump(rpc)
        out = {"set": "pump_2026-11-11", "plan": "KR-000047", "census": census(rows)}
    else:
        rows, meta = build_cpmm(name, rpc)
        out = dict({"set": name, "first_day": SETS[name][0], "plan": "KR-000047", "pilot": "KR-000048"}, **summarise(rows, meta))
    if cmd == "collect":
        print(name, "collected, calls", client.calls_used(), flush=True)
        return
    write(name, rows, out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
