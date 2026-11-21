"""Study 2, Robinhood Chain side: census of Pons V2 launches on one UTC day and their outcomes.

Uses the public Robinhood Chain RPC (eth_getLogs, cached, 2 req/s, stop on 429) and DexScreener.
Usage: RKD_USAGE=data/raw/usage_xchain.json python3 -m collectors.xchain_rh
Writes data/raw/xchain_rh_2026-11-11.json.
"""
import json
import os

from collectors import client

FACTORY = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"  # PonsV2LaunchFactory (Bitquery docs)
T_LAUNCH = "0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607"  # TokenLaunched
T_GRAD = "0x0a44ef75df69c534f43cd6c1aa3ef8983065fe5fe79ef9e79f6494e6f258c259"  # PoolGraduated
T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # ERC-20 Transfer
DAY = 86400
# Fixed during the pilot (block_at() bisection on 2026-11-21): 2026-11-11 00:00 and 2026-11-12 00:00 UTC.
B0, B1, T0_DAY = 111281151, 112102896, 1794355200
HEAD = 120107373  # pinned snapshot block, 2026-11-21 19:35 UTC
SEC_PER_BLOCK = DAY / (B1 - B0)
BATCH = 100


def block_time(b):
    """Linear interpolation inside the measured day (error of a few seconds at most)."""
    return T0_DAY + (b - B0) * SEC_PER_BLOCK


def block_for(t):
    return B0 + int((t - T0_DAY) / SEC_PER_BLOCK)


def addr(topic):
    return "0x" + topic[-40:]


MAX_SPAN_MULTI = 100000   # blocks allowed when filtering by an address array (RPC error text, 2026-11-21)
MAX_SPAN_TOPIC = 30000    # blocks allowed with a topic filter only


def get_logs(flt, lo, hi):
    """eth_getLogs over [lo, hi] (inclusive) in fixed chunks that never exceed the RPC's span limit.
    Lesson from the first run: splitting on errors burned ~470 counted calls, because every
    rejected request is still a call. A single address string has no span limit observed (whole day OK)."""
    multi = isinstance(flt.get("address"), list)
    span = MAX_SPAN_MULTI if multi else (None if flt.get("address") else MAX_SPAN_TOPIC)
    if span is None:
        return client.evm_rpc("eth_getLogs", [dict(flt, fromBlock=hex(lo), toBlock=hex(hi))])
    out, a = [], lo
    while a <= hi:
        b = min(hi, a + span - 1)
        out += client.evm_rpc("eth_getLogs", [dict(flt, fromBlock=hex(a), toBlock=hex(b))])
        a = b + 1
    return out


def main():
    path = os.path.join(client.RAW, "xchain_rh_2026-11-11.json")
    st = json.load(open(path)) if os.path.exists(path) else {}
    save = lambda: json.dump(st, open(path, "w"))
    if "launches" not in st:
        logs = get_logs({"address": FACTORY, "topics": [T_LAUNCH]}, B0, B1 - 1)
        L = []
        for l in logs:
            w = [l["data"][2:][i:i + 64] for i in range(0, len(l["data"]) - 2, 64)]
            b = int(l["blockNumber"], 16)
            L.append({"token": addr(l["topics"][1]), "curve": addr(l["topics"][2]), "deployer": addr(l["topics"][3]),
                      "pair_token": "0x" + w[0][-40:], "grad_threshold": int(w[2], 16) / 1e18, "block": b,
                      "t0": block_time(b), "tx": l["transactionHash"]})
        st["launches"] = L; save()
    L = st["launches"]
    print("launches", len(L), "calls", client.calls_used())
    if "graduations" not in st:
        g = get_logs({"address": FACTORY, "topics": [T_GRAD]}, B0, HEAD)
        st["graduations"] = [{"token": addr(x["topics"][1]), "block": int(x["blockNumber"], 16)} for x in g]; save()
    print("graduation events since D", len(st["graduations"]), "calls", client.calls_used())
    toks = [l["token"] for l in L]
    st.setdefault("transfers_24h", {}); st.setdefault("transfers_d7", {})
    for i in range(0, len(toks), BATCH):
        key = str(i)
        if key not in st["transfers_24h"]:
            logs = get_logs({"address": toks[i:i + BATCH], "topics": [T_TRANSFER]}, B0, block_for(T0_DAY + 2 * DAY))
            st["transfers_24h"][key] = [[x["address"].lower(), addr(x["topics"][1]), addr(x["topics"][2]), int(x["data"], 16) if x["data"] != "0x" else 0,
                                         int(x["blockNumber"], 16), x["transactionHash"]] for x in logs]
            save()
        if key not in st["transfers_d7"]:
            logs = get_logs({"address": toks[i:i + BATCH], "topics": [T_TRANSFER]}, block_for(T0_DAY + 6 * DAY), block_for(T0_DAY + 8 * DAY))
            st["transfers_d7"][key] = [[x["address"].lower(), int(x["blockNumber"], 16)] for x in logs]
            save()
        print("batch", i, "calls", client.calls_used())
    st.setdefault("dex", {})
    for i in range(0, len(toks), 30):
        if str(i) not in st["dex"]:
            st["dex"][str(i)] = client.dexscreener_tokens_chain("robinhood", toks[i:i + 30]); save()
    print("dex done, calls", client.calls_used())


if __name__ == "__main__":
    main()
