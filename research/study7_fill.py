"""Study 7 sensitivity: extend capped tokens past trade coverage with cached GeckoTerminal 1-minute candles. Offline.
Usage: python3 -m research.study7_fill"""
import json
import os
import statistics

from collectors import client
from collectors.study7 import history, sample
from research.stats import wilson
from research.study7_analyze import EXPORT, boot_median
from research.study7_parse import LAUNCH_PRICE, main_pool, trade_events
from collectors.study7_candles import GT, candle_path


def candles(pool, t0):
    p = client._cache_path("geckoterminal", {"study7_candles": [pool, t0]})
    if not os.path.exists(p):
        return []
    r = json.load(open(p))["response"]
    c = ((r.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return sorted(x for x in c if t0 <= x[0] <= t0 + 3600)


def day(d):
    by, groups, _ = sample(d)
    ratios, rows = [], []
    for g, ms in groups.items():
        for m in ms:
            l = by[m]
            txs, done, _ = history(l, offline=True)
            ev = [(e["blockTime"] - l["t0"], x) for e in txs for x in trade_events(e, m)]
            pool = main_pool([x for _, x in ev])
            ev = [(t, x) for t, x in ev if x["price"] and (x["venue"] == "curve" or x["pool"] == pool)]
            if not ev:
                continue
            cover = 3600 if done else txs[-1]["blockTime"] - l["t0"]
            peak = max(x["price"] for _, x in ev)
            last = {}
            for t, x in ev:
                last[t] = x["price"]
            times = sorted(last)
            def at(T):
                k = [q for q in times if q <= T]
                return last[k[-1]] if k else None
            pts = {}
            source = "trades"
            if not done:
                c = candles(pool, l["t0"]) if pool else []
                for x in c:
                    T = x[0] - l["t0"] + 60
                    if T <= cover and x[0] - l["t0"] >= 0:
                        px = at(T)
                        if px:
                            ratios.append(x[4] / px)
                after = [x for x in c if x[0] - l["t0"] + 60 > cover]
                if not after and cover < 3600:
                    rows.append({"group": g, "filled": False})
                    continue
                source = "trades+candles"
                peak = max([peak] + [x[2] for x in after])
                def at2(T):
                    if T <= cover:
                        return at(T)
                    k = [x for x in c if x[0] - l["t0"] + 60 <= T]
                    return k[-1][4] if k else at(cover)
                f = at2
            else:
                f = at
            for T in (300, 1800, 3600):
                pts[str(T // 60)] = f(T)
            end = pts["60"]
            idx, dd = peak / LAUNCH_PRICE, 100 * (1 - end / peak)
            rows.append({"group": g, "filled": True, "source": source, "peak_index": idx, "drawdown": dd,
                         "end_index": end / LAUNCH_PRICE, "i5": pts["5"] / LAUNCH_PRICE, "i30": pts["30"] / LAUNCH_PRICE,
                         "shape": "no_pump" if idx < 3 else "pump_and_dump" if dd >= 50 else "pump_and_hold"})
    use = [r for r in rows if r["filled"]]
    out = {"day": d, "tokens": len(rows), "with_60m_after_fill": len(use), "not_filled": len(rows) - len(use),
           "from_candles": sum(r["source"] != "trades" for r in use),
           "candle_vs_trade_price": None, "shapes": {}, "by_group": {}}
    if ratios:
        out["candle_vs_trade_price"] = {"n": len(ratios), "median_ratio": round(statistics.median(ratios), 4),
                                        "within_10pct": round(sum(.9 <= x <= 1.1 for x in ratios) / len(ratios), 4)}
    for s in ("no_pump", "pump_and_dump", "pump_and_hold"):
        k = sum(r["shape"] == s for r in use)
        lo, hi = wilson(k, len(use))
        out["shapes"][s] = {"n": k, "pct": round(100 * k / len(use), 1), "ci95": [round(100 * lo, 1), round(100 * hi, 1)]}
    pumped = [r["drawdown"] for r in use if r["peak_index"] >= 3]
    out["pumped"] = {"n": len(pumped), "median_drawdown": round(statistics.median(pumped), 2), "ci95": boot_median(pumped)}
    for g in groups:
        x = [r for r in use if r["group"] == g]
        out["by_group"][g] = {"n": len(x), **{k: round(statistics.median(r[v] for r in x), 3) for k, v in
                              (("index_5m", "i5"), ("index_30m", "i30"), ("index_60m", "end_index"), ("peak", "peak_index"), ("drawdown_60", "drawdown"))}}
    return out


if __name__ == "__main__":
    res = {d: day(d) for d in ("2026-11-11", "2026-11-09")}
    with open(os.path.join(EXPORT, "study7_candle_fill.json"), "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    print(json.dumps(res, indent=1, sort_keys=True))
