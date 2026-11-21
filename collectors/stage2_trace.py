"""Stage 2: classify stage-1 launches, confirm 7-day survival on-chain, trace deployer holdings.

Pre-specified rule (fixed before outcomes were seen; extension to 40 anchors added after the
first 10 anchors gave only 5 dev-buy survivors, see Logbook update):
 1. DexScreener /tokens/v1 for every stage-1 mint (30 per call), fetched ~10 days after launch.
    Listed = survivor candidate (pilot: DexScreener lists fresh bonding-curve tokens but drops inactive ones).
 2. On-chain day-7 check (getTransactionsForAddress on the mint, signatures, succeeded,
    blockTime in [t0+6d, t0+7d), limit 10) for every listed candidate (cap 60) and for 25 random
    unlisted mints (validates 'unlisted = dead'). Survivor = 10 or more such txs.
 3. Hold trace for up to 25 confirmed survivors and 25 confirmed non-survivors with a dev buy > 0
    (random draw, fixed seed): full history of the deployer's token account from t0 to t0+7d.
Outputs data/raw/stage2_<D>.json.  Usage: python3 -m collectors.stage2_trace 2026-11-11
"""
import json
import os
import random
import sys

from collectors import client

SEED = 7
DAY = 86400
SURV_MIN_TX = 10
N_PER_GROUP = 25
CAP_LISTED = 80
BASE_ANCHORS = 10  # unlisted validation draw comes from the first 10 anchors only (fixed before extension)
N_UNLISTED_CHECK = 25
MAX_TRACE_PAGES = 3


def launches(day):
    s = json.load(open(os.path.join(client.RAW, "stage1_{}.json".format(day))))
    seen, out = set(), []
    for k in sorted(s["anchors"], key=int):
        for l in s["anchors"][k]["launches"]:
            if l["mint"] not in seen:
                seen.add(l["mint"])
                out.append(dict(l, anchor_id=int(k)))
    return out


def dex_listing(mints):
    info = {}
    for i in range(0, len(mints), 30):
        for p in client.dexscreener_tokens(mints[i:i + 30]):
            a = p["baseToken"]["address"]
            d = info.setdefault(a, {"pairs": 0, "dexIds": [], "vol24": 0.0, "liq": 0.0})
            d["pairs"] += 1
            d["dexIds"].append(p.get("dexId"))
            d["vol24"] += float((p.get("volume") or {}).get("h24") or 0)
            d["liq"] += float((p.get("liquidity") or {}).get("usd") or 0)
    return info


def day7_txcount(mint, t0):
    r = client.helius_rpc("getTransactionsForAddress", [mint, {
        "transactionDetails": "signatures", "sortOrder": "asc", "limit": SURV_MIN_TX,
        "filters": {"blockTime": {"gte": t0 + 6 * DAY, "lt": t0 + 7 * DAY}, "status": "succeeded"}}])
    return len(r["data"])


def trace(ata, t0):
    txs, token = [], None
    for _ in range(MAX_TRACE_PAGES):
        opts = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                "sortOrder": "asc", "limit": 100,
                "filters": {"blockTime": {"gte": t0, "lte": t0 + 7 * DAY}, "status": "succeeded"}}
        if token:
            opts["paginationToken"] = token
        r = client.helius_rpc("getTransactionsForAddress", [ata, opts])
        txs.extend({"transaction": e["transaction"], "meta": e["meta"], "blockTime": e["blockTime"],
                    "slot": e["slot"]} for e in r["data"])
        token = r.get("paginationToken")
        if not token:
            return txs, True
    return txs, False


def main(day):
    path = os.path.join(client.RAW, "stage2_{}.json".format(day))
    st = json.load(open(path)) if os.path.exists(path) else {"day": day, "seed": SEED}
    save = lambda: json.dump(st, open(path, "w"))
    L = launches(day)
    by_mint = {l["mint"]: l for l in L}
    st.setdefault("dex", {}); st.setdefault("dex_checked", [])
    todo = [l["mint"] for l in L if l["mint"] not in set(st["dex_checked"])]
    if todo:
        if not st["dex_checked"]:  # first run stored only listed mints; all its mints were checked
            st["dex_checked"] = [l["mint"] for l in L if l["anchor_id"] < BASE_ANCHORS]
            todo = [m for m in todo if m not in set(st["dex_checked"])]
        for i in range(0, len(todo), 30):
            st["dex"].update(dex_listing(todo[i:i + 30])); st["dex_checked"].extend(todo[i:i + 30]); save()
    print("launches", len(L), "listed", len(st["dex"]), "calls", client.calls_used())
    rng = random.Random(SEED)
    listed = [m for m in by_mint if m in st["dex"]]
    unlisted = [m for m in by_mint if m not in st["dex"] and by_mint[m]["anchor_id"] < BASE_ANCHORS]
    rng.shuffle(listed); rng.shuffle(unlisted)
    to_check = listed[:CAP_LISTED] + unlisted[:N_UNLISTED_CHECK]
    st.setdefault("day7", {})
    for m in to_check:
        if m not in st["day7"]:
            st["day7"][m] = day7_txcount(m, by_mint[m]["t0"]); save()
    print("day7 checked", len(st["day7"]), "calls", client.calls_used())
    # Groups (revised after a selection bug: the first version filled 'non_survivor' with
    # DexScreener-listed-but-dead tokens, which are <1% of dead launches, not a random draw).
    #  survivor      = every checked day-7 survivor with a dev buy (cap N_PER_GROUP)
    #  non_survivor  = every checked UNLISTED dead launch with a dev buy from the random base-anchor
    #                  draw (unlisted = ~99% of all launches, so this is the random non-survivor sample)
    #  listed_dead   = secondary stratum: listed-but-dead with a dev buy, only those already traced
    checked = sorted(st["day7"])
    dev = lambda m: by_mint[m]["dev_raw"] > 0
    surv = [m for m in checked if st["day7"][m] >= SURV_MIN_TX and dev(m)]
    dead_unl = [m for m in checked if st["day7"][m] < SURV_MIN_TX and dev(m) and m not in st["dex"]
                and by_mint[m]["anchor_id"] < BASE_ANCHORS]
    dead_lis = [m for m in checked if st["day7"][m] < SURV_MIN_TX and dev(m) and m in st["dex"]
                and m in st.get("traces", {})]
    groups = {"survivor": surv[:N_PER_GROUP], "non_survivor": dead_unl, "listed_dead": dead_lis}
    st["groups"] = groups
    st.setdefault("traces", {})
    for g, ms in groups.items():
        for m in ms:
            if m in st["traces"]:
                continue
            l = by_mint[m]
            txs, complete = trace(l["dev_ata"], l["t0"])
            raw = os.path.join(client.RAW, "traces", m + ".json")
            os.makedirs(os.path.dirname(raw), exist_ok=True)
            json.dump(txs, open(raw, "w"))
            st["traces"][m] = {"n_tx": len(txs), "complete": complete, "file": os.path.relpath(raw, client.RAW)}
            save()
    print("traced", len(st["traces"]), "calls", client.calls_used())
    save()


if __name__ == "__main__":
    main(sys.argv[1])
