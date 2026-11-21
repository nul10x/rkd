"""Study 2: 7-day peak market cap of graduated tokens from GeckoTerminal daily OHLCV (free public API).

For each graduated token: /networks/{net}/tokens/{addr}/pools (top pool), then
/networks/{net}/pools/{pool}/ohlcv/day (USD, base token). Peak MC = max daily high x 1e9 supply
(Pump.fun and Pons both mint 1,000,000,000 tokens).
Run slowly: RKD_RPS=0.25 (one call per 4 s). Stops on the first 429.
"""
import json
import os

from collectors import client

GT = "https://api.geckoterminal.com/api/v2"
DAY = 86400


def gt(path, key):
    return client.cached("geckoterminal", key, GT + path, None, path.split("?")[0])


def peak(net, token, t0):
    pools = gt("/networks/{}/tokens/{}/pools?page=1".format(net, token), {"pools": [net, token]})
    data = pools.get("data") or []
    if not data:
        return {"pool": None}
    pool = data[0]["attributes"]["address"]
    before = int(t0 + 8 * DAY)
    o = gt("/networks/{}/pools/{}/ohlcv/day?aggregate=1&limit=10&currency=usd&token=base&before_timestamp={}".format(net, pool, before),
           {"ohlcv": [net, pool, before]})
    rows = ((o.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    day0 = int(t0) - int(t0) % DAY
    rows = sorted(r for r in rows if day0 <= r[0] <= t0 + 7 * DAY)
    if not rows:
        return {"pool": pool, "n_candles": 0}
    hi = max(r[2] for r in rows)
    return {"pool": pool, "n_candles": len(rows), "peak_price": hi, "peak_mc": hi * 1e9,
            "first_open_mc": rows[0][1] * 1e9, "last_close_mc": rows[-1][4] * 1e9,
            "last_close_over_peak": rows[-1][4] / hi if hi else None}


def main():
    from collectors.stage2_trace import launches
    path = os.path.join(client.RAW, "xchain_peaks_2026-11-11.json")
    st = json.load(open(path)) if os.path.exists(path) else {}
    pg = json.load(open(os.path.join(client.RAW, "xchain_pump_grad_2026-11-11.json")))
    L = {l["mint"]: l for l in launches("2026-11-11")}
    todo = [("solana", m, L[m]["t0"]) for m, v in sorted(pg["complete"].items()) if v == 1]
    rh = json.load(open(os.path.join(client.RAW, "xchain_rh_2026-11-11.json")))
    rt = {l["token"]: l["t0"] for l in rh["launches"]}
    todo += [("robinhood", t, rt[t]) for t in sorted({g["token"] for g in rh["graduations"] if g["token"] in rt})]
    for net, tok, t0 in todo:
        k = net + ":" + tok
        if k not in st:
            st[k] = peak(net, tok, t0)
            json.dump(st, open(path, "w"))
    print("peaks", len(st), "calls", client.calls_used())


if __name__ == "__main__":
    main()
