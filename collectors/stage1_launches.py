"""Stage 1: sample Pump.fun launches by launch date.

For launch day D (UTC), draw N uniform random anchor times with a fixed seed. For each anchor,
take the up-to-100 successful txs touching the Pump.fun mint authority just before it
(getTransactionsForAddress, full, desc), keep the create txs and parse them.
Output: data/raw/stage1_<D>.json (list of launches with anchor id).

Usage: python3 -m collectors.stage1_launches 2026-11-11 [n_anchors] [start_anchor]
"""
import calendar
import json
import os
import random
import sys
import time

from collectors import client
from research import pump

SEED = 20261111


def anchors(day, n):
    t = calendar.timegm(time.strptime(day, "%Y-%m-%d"))
    rng = random.Random(SEED)
    return [t + int(rng.random() * 86400) for _ in range(n)]


def fetch_anchor(anchor):
    r = client.helius_rpc("getTransactionsForAddress", [pump.MINT_AUTHORITY, {
        "transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
        "sortOrder": "desc", "limit": 100,
        "filters": {"blockTime": {"lte": anchor}, "status": "succeeded"}}])
    out = []
    for e in r["data"]:
        tx = {"transaction": e["transaction"], "meta": e["meta"], "blockTime": e["blockTime"], "slot": e["slot"]}
        p = pump.parse_create(tx)
        if p:
            out.append(p)
    return out, len(r["data"])


def main(day, n=10, start=0):
    path = os.path.join(client.RAW, "stage1_{}.json".format(day))
    state = json.load(open(path)) if os.path.exists(path) else {"day": day, "seed": SEED, "anchors": {}}
    for i, a in enumerate(anchors(day, n)):
        if i < start or str(i) in state["anchors"]:
            continue
        launches, ntx = fetch_anchor(a)
        state["anchors"][str(i)] = {"anchor": a, "n_tx": ntx, "launches": launches}
        json.dump(state, open(path, "w"))
        print("anchor", i, a, "txs", ntx, "creates", len(launches), "calls", client.calls_used())
    return state


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10, int(sys.argv[3]) if len(sys.argv) > 3 else 0)
