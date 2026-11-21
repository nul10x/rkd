"""Study 2, Solana side: launch-date samples from Raydium LaunchLab (bonk.fun etc.) and Meteora DBC (Bags etc.).

Neither program has a creates-only account, so each anchor reads the 100 successful program txs
just before a seeded random time on the launch day and keeps the create txs (~1-4 per call).
Then: DexScreener snapshot for every sampled mint, and an on-chain day-7 check for listed mints
plus N_UNLISTED random unlisted mints per pad.
Usage: RKD_USAGE=data/raw/usage_xchain.json RKD_CALL_BUDGET=1000 python3 -m collectors.xchain_sol_pads
"""
import calendar
import json
import os
import random
import time

from collectors import client
from collectors.stage2_trace import day7_txcount
from research import pump

DAY_STR = "2026-11-11"
PADS = {
    "launchlab": {"program": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
                  "create_logs": ("Program log: Instruction: Initialize", "Program log: Instruction: InitializeV2",
                                  "Program log: Instruction: InitializeWithToken2022")},
    "meteora_dbc": {"program": "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",
                    "create_logs": ("Program log: Instruction: InitializeVirtualPoolWithSplToken",
                                    "Program log: Instruction: InitializeVirtualPoolWithToken2022")},
}
QUOTES = {pump.WSOL, "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
N_ANCHORS = 60
N_UNLISTED = 10
SEED = 2026111102


def anchors(n):
    t = calendar.timegm(time.strptime(DAY_STR, "%Y-%m-%d"))
    rng = random.Random(SEED)
    return [t + int(rng.random() * 86400) for _ in range(n)]


def parse(e, create_logs):
    meta = e["meta"]
    logs = meta.get("logMessages") or []
    if meta.get("err") is not None or not any(l in create_logs for l in logs):
        return None
    keys = [k["pubkey"] for k in e["transaction"]["message"]["accountKeys"]]
    post = meta.get("postTokenBalances") or []
    mints = {b["mint"] for b in post if b["mint"] not in QUOTES}
    if len(mints) != 1:
        return None
    mint = next(iter(mints))
    dep = keys[0]
    dev = sum(int(b["uiTokenAmount"]["amount"]) for b in post if b["mint"] == mint and b.get("owner") == dep)
    supply = sum(int(b["uiTokenAmount"]["amount"]) for b in post if b["mint"] == mint)
    quote = sorted({b["mint"] for b in post if b["mint"] in QUOTES})
    return {"mint": mint, "deployer": dep, "t0": e["blockTime"], "signature": e["transaction"]["signatures"][0],
            "dev_raw": dev, "supply_raw_seen": supply, "quote": quote,
            "decimals": next((b["uiTokenAmount"]["decimals"] for b in post if b["mint"] == mint), None)}


def main():
    path = os.path.join(client.RAW, "xchain_sol_pads_{}.json".format(DAY_STR))
    st = json.load(open(path)) if os.path.exists(path) else {"seed": SEED, "pads": {}}
    save = lambda: json.dump(st, open(path, "w"))
    for pad, cfg in PADS.items():
        P = st["pads"].setdefault(pad, {"anchors": {}, "dex": {}, "day7": {}})
        for i, a in enumerate(anchors(N_ANCHORS)):
            if str(i) in P["anchors"]:
                continue
            r = client.helius_rpc("getTransactionsForAddress", [cfg["program"], {
                "transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                "sortOrder": "desc", "limit": 100, "filters": {"blockTime": {"lte": a}, "status": "succeeded"}}])
            got = [p for p in (parse(e, cfg["create_logs"]) for e in r["data"]) if p]
            P["anchors"][str(i)] = {"anchor": a, "n_tx": len(r["data"]),
                                    "span_s": (r["data"][0]["blockTime"] - r["data"][-1]["blockTime"]) if r["data"] else None,
                                    "launches": got}
            save()
        seen, L = set(), []
        for k in sorted(P["anchors"], key=int):
            for l in P["anchors"][k]["launches"]:
                if l["mint"] not in seen:
                    seen.add(l["mint"]); L.append(dict(l, anchor_id=int(k)))
        print(pad, "launches", len(L), "calls", client.calls_used())
        mints = [l["mint"] for l in L]
        for i in range(0, len(mints), 30):
            if str(i) not in P["dex"]:
                P["dex"][str(i)] = client.dexscreener_tokens(mints[i:i + 30]); save()
        listed = {p["baseToken"]["address"] for v in P["dex"].values() for p in v}
        rng = random.Random(SEED)
        unl = [m for m in mints if m not in listed]
        rng.shuffle(unl)
        by = {l["mint"]: l for l in L}
        for m in sorted(m for m in mints if m in listed) + unl[:N_UNLISTED]:
            if m not in P["day7"]:
                P["day7"][m] = day7_txcount(m, by[m]["t0"]); save()
        print(pad, "listed", len(listed & set(mints)), "day7 checked", len(P["day7"]), "calls", client.calls_used())


if __name__ == "__main__":
    main()
