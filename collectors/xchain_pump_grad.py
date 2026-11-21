"""Study 2: Pump.fun graduation status for the study-1 day-D sample.

The bonding-curve account is the owner of the largest token balance in the create tx (the curve
holds the unsold supply). Its 'complete' flag (byte 48: 8-byte discriminator + 5 u64 fields) is
read with getMultipleAccounts, 100 accounts per call, at snapshot time.
Usage: RKD_USAGE=data/raw/usage_xchain.json RKD_CALL_BUDGET=1000 python3 -m collectors.xchain_pump_grad 2026-11-11
"""
import base64
import glob
import json
import os
import sys

from collectors import client
from collectors.stage2_trace import launches
from research import pump


def curves_from_cache(mints):
    out = {}
    for f in glob.glob(os.path.join(client.RAW, "helius", "*.json")):
        d = json.load(open(f))
        q = d["request"]
        if q["method"] != "getTransactionsForAddress" or q["params"][0] != pump.MINT_AUTHORITY:
            continue
        if q["params"][1].get("transactionDetails") != "full":
            continue
        for e in d["response"]["result"]["data"]:
            tx = {"transaction": e["transaction"], "meta": e["meta"], "blockTime": e["blockTime"], "slot": e["slot"]}
            p = pump.parse_create(tx)
            if not p or p["mint"] not in mints:
                continue
            bals = [b for b in e["meta"]["postTokenBalances"] if b["mint"] == p["mint"] and b.get("owner") != p["deployer"]]
            if bals:
                out[p["mint"]] = max(bals, key=lambda b: int(b["uiTokenAmount"]["amount"]))["owner"]
    return out


def main(day):
    path = os.path.join(client.RAW, "xchain_pump_grad_{}.json".format(day))
    st = json.load(open(path)) if os.path.exists(path) else {}
    L = launches(day)
    mints = {l["mint"] for l in L}
    if "curves" not in st:
        st["curves"] = curves_from_cache(mints)
        json.dump(st, open(path, "w"))
    print("curves found", len(st["curves"]), "of", len(mints))
    st.setdefault("complete", {})
    items = sorted(st["curves"].items())
    for i in range(0, len(items), 100):
        chunk = items[i:i + 100]
        if all(m in st["complete"] for m, _ in chunk):
            continue
        r = client.helius_rpc("getMultipleAccounts", [[c for _, c in chunk], {"encoding": "base64"}])
        for (m, _), acc in zip(chunk, r["value"]):
            if acc is None:
                st["complete"][m] = None
            else:
                raw = base64.b64decode(acc["data"][0])
                st["complete"][m] = raw[48] if len(raw) > 48 else None
        json.dump(st, open(path, "w"))
    vals = list(st["complete"].values())
    print("complete=1", vals.count(1), "complete=0", vals.count(0), "missing", vals.count(None), "calls", client.calls_used())


if __name__ == "__main__":
    main(sys.argv[1])
