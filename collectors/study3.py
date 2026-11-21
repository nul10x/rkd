"""Study 3 collector (plan: Logbook KR-000016). Every response is cached by collectors/client.py, so any
stage can be re-run after a stop and only missing calls are made.

Stages, run one provider at a time (a GeckoTerminal job holds the shared throttle lock while it waits):
  python3 -m collectors.study3 grad    DAY   # Helius: curve 'complete' flags (only if not cached yet)
  python3 -m collectors.study3 mints   DAY   # Helius: first-hour mint page per sampled launch; dev ATA trace if needed
  python3 -m collectors.study3 pools   DAY   # GeckoTerminal: token pools -> PumpSwap pool + created_at (graduates)
  python3 -m collectors.study3 poolT   DAY   # Helius: last 100 pool txs at or before T; day-7 tx count of the mint
  python3 -m collectors.study3 hourly  DAY   # GeckoTerminal: hourly OHLCV to t0 + 7 d
Env: RKD_USAGE=data/raw/usage_study3.json RKD_CALL_BUDGET=2400 HELIUS_API_KEY=...
"""
import calendar
import json
import os
import random
import sys
import time

from collectors import client
from collectors.stage2_trace import DAY, day7_txcount, launches, trace

GT = "https://api.geckoterminal.com/api/v2"
N_NON = 300
N_B_MAX = 100
FULL = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}


def grad_flags(day):
    p = os.path.join(client.RAW, "xchain_pump_grad_{}.json".format(day))
    return json.load(open(p))["complete"] if os.path.exists(p) else None


def sample(day):
    """(a) all graduates + N_NON random non-graduates; (b) graduates, at most N_B_MAX. Seeds fixed in KR-000016."""
    L = launches(day)
    g = grad_flags(day)
    grads = sorted(l["mint"] for l in L if g.get(l["mint"]) == 1)
    non = sorted(l["mint"] for l in L if g.get(l["mint"]) != 1)
    rnd = random.Random("study3-" + day)
    non_s = sorted(rnd.sample(non, min(N_NON, len(non))))
    b = sorted(random.Random("study3-" + day + "-b").sample(grads, min(N_B_MAX, len(grads))))
    return {l["mint"]: l for l in L}, grads, non_s, b


def mint_page(l):
    return client.helius_rpc("getTransactionsForAddress", [l["mint"], dict(FULL, sortOrder="asc", limit=100, filters={
        "blockTime": {"gte": l["t0"], "lte": l["t0"] + 3600}, "status": "succeeded"})])


def gt(path, key):
    return client.cached("geckoterminal", key, GT + path, None, path.split("?")[0])


def token_pools(mint):
    # Same request and cache key as collectors/xchain_peaks.py, so step-2 responses are reused.
    return gt("/networks/solana/tokens/{}/pools?page=1".format(mint), {"pools": ["solana", mint]})


def pumpswap_pool(resp):
    for x in resp.get("data") or []:
        if ((x.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id") == "pumpswap":
            a = x["attributes"]
            return a["address"], calendar.timegm(time.strptime(a["pool_created_at"], "%Y-%m-%dT%H:%M:%SZ"))
    return None, None


def pool_txs_at(pool, T):
    return client.helius_rpc("getTransactionsForAddress", [pool, dict(FULL, sortOrder="desc", limit=100, filters={
        "blockTime": {"lte": T}, "status": "succeeded"})])


def hourly(pool, t0):
    before = int(t0 + 7 * DAY + 3600)
    path = "/networks/solana/pools/{}/ohlcv/hour?aggregate=1&limit=200&currency=usd&token=base&before_timestamp={}".format(pool, before)
    return gt(path, {"ohlcv_hour": ["solana", pool, before]})


def main(stage, day):
    if stage == "grad":
        if grad_flags(day) is None:
            from collectors import xchain_pump_grad
            xchain_pump_grad.main(day)
        print("graduates", sum(1 for v in grad_flags(day).values() if v == 1), "calls", client.calls_used())
        return
    L, grads, non, b = sample(day)
    print(day, "graduates", len(grads), "non-grad sample", len(non), "(b) sample", len(b))
    if stage == "mints":
        for i, m in enumerate(grads + non):
            r = mint_page(L[m])
            if len(r["data"]) >= 100:  # page does not cover the first hour: use the deployer ATA trace (study-1 method)
                trace(L[m]["dev_ata"], L[m]["t0"])
            if i % 50 == 0:
                print("mints", i, "calls", client.calls_used(), flush=True)
    elif stage == "pools":
        for m in b:
            token_pools(m)
    elif stage == "poolT":
        for m in b:
            pool, created = pumpswap_pool(token_pools(m))
            if pool:
                pool_txs_at(pool, created + 3600)
            day7_txcount(m, L[m]["t0"])
    elif stage == "hourly":
        for m in b:
            pool, created = pumpswap_pool(token_pools(m))
            if pool:
                hourly(pool, L[m]["t0"])
    print(stage, "done, calls", client.calls_used())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
