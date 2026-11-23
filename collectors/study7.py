"""Study 7 collector (plan KR-000068): full first-hour mint history for a seeded launch sample.
Usage: python3 -m collectors.study7 DAY [--limit N]   Env: RKD_USAGE, RKD_CALL_BUDGET, HELIUS_API_KEY."""
import json
import os
import random
import sys

from collectors import client
from collectors.study3 import FULL, mint_page, sample as s3_sample
from research.study3_parse import ordered
from research.study7_parse import DEFAULT_KEY, WSOL, trade_events

N_GROUP, MIN_EVENTS, PAGE_CAP = {"2026-11-11": 25, "2026-11-09": 15}, 20, 40


def sol_paired(l):
    """True when the launch's curve trades in the cached first page are quoted in SOL."""
    q = [x["quote_mint"] for e in mint_page(l).get("data") or [] for x in trade_events(e, l["mint"]) if x["venue"] == "curve"]
    return bool(q) and all(x in (DEFAULT_KEY, WSOL) for x in q)


def n_events(l):
    return sum(len(trade_events(e, l["mint"])) for e in mint_page(l).get("data") or [])


def sample(day):
    by, grads, non, _ = s3_sample(day)
    sg = [m for m in grads if sol_paired(by[m])]
    sn = [m for m in non if sol_paired(by[m])]
    active = [m for m in sn if n_events(by[m]) >= MIN_EVENTS]
    g = sorted(random.Random("study7-{}-grad".format(day)).sample(sorted(sg), min(N_GROUP[day], len(sg))))
    a = sorted(random.Random("study7-{}-active".format(day)).sample(sorted(active), min(N_GROUP[day], len(active))))
    return by, {"graduate": g, "active_non_graduate": a}, {"graduates": len(grads), "graduates_sol_paired": len(sg),
                                                         "non_grad_random": len(non), "non_grad_sol_paired": len(sn),
                                                         "non_grad_active": len(active)}


def history(l, cap=PAGE_CAP, offline=False):
    """All first-hour successful txs. Returns (txs ascending, complete, pages)."""
    r, txs, pages = mint_page(l), [], 1
    while True:
        txs += r.get("data") or []
        tok = r.get("paginationToken")
        if not tok:
            return ordered(txs), True, pages
        if pages >= cap:
            return ordered(txs), False, pages
        opts = dict(FULL, sortOrder="asc", limit=100, paginationToken=tok,
                    filters={"blockTime": {"gte": l["t0"], "lte": l["t0"] + 3600}, "status": "succeeded"})
        key = {"method": "getTransactionsForAddress", "params": [l["mint"], opts]}
        if offline and not os.path.exists(client._cache_path("helius", key)):
            return ordered(txs), False, pages
        r = client.helius_rpc("getTransactionsForAddress", [l["mint"], opts])
        pages += 1


def main():
    day = sys.argv[1]
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    by, groups, frame = sample(day)
    print(json.dumps({"day": day, "frame": frame, "n": {k: len(v) for k, v in groups.items()}}))
    for g, ms in groups.items():
        for m in ms[:lim]:
            try:
                t, done, p = history(by[m])
            except client.BudgetExceeded as e:
                print("BUDGET_STOP", e, flush=True)
                return
            print(g, m[:8], "txs", len(t), "pages", p, "complete", done, "calls", client.calls_used(), flush=True)


if __name__ == "__main__":
    main()
