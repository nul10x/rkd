"""Study 7 analysis (plan KR-000068). Offline: reads cached pages only. Usage: python3 -m research.study7_analyze DAY"""
import csv
import json
import os
import random
import statistics
import sys

from collectors import client
from collectors.study7 import history, sample
from research.stats import mann_whitney, wilson
from research.study3_parse import _block0
from research.study7_parse import LAUNCH_PRICE, main_pool, trade_events

CHECKS = (300, 1800, 3600)
SUPPLY = 1e9
SNIPER_SLOTS = 10
SIZE = ((100, "<100 SOL"), (400, "100-400 SOL"), (2000, "400-2,000 SOL"), (float("inf"), ">=2,000 SOL"))
VOL = ((50, "<50 SOL"), (500, "50-500 SOL"), (float("inf"), ">=500 SOL"))
EXPORT = os.path.join(os.path.dirname(client.RAW), "exports")


def bucket(v, table):
    return next(n for lim, n in table if v < lim)


def token_metrics(l, txs, complete):
    mint, slot0, t0, dev = l["mint"], l["slot"], l["t0"], l["deployer"]
    b0, buyers = _block0(txs, l)
    if not b0.get("create_found"):
        return None
    bundle = set(buyers or ())
    first = {}
    rows = []
    for e in txs:
        t = e["blockTime"] - t0
        for x in trade_events(e, mint):
            if x["sol"] is None:
                return None
            if x["buy"] and x["user"] not in first:
                first[x["user"]] = e["slot"]
            rows.append((t, e["slot"], x))
    if not rows or not any(r[2]["price"] for r in rows):
        return None
    pool = main_pool([r[2] for r in rows])
    n_pools = len({r[2]["pool"] for r in rows if r[2]["venue"] == "pool"})
    rows = [r for r in rows if r[2]["venue"] == "curve" or r[2]["pool"] == pool]
    snipers = {u for u, s in first.items() if slot0 < s <= slot0 + SNIPER_SLOTS and u != dev and u not in bundle}
    cover = 3600 if complete else txs[-1]["blockTime"] - t0
    out = {"mint": mint, "complete": complete, "covered_s": cover, "trades": len(rows),
           "graduated_in_block0": bool(b0.get("graduated_in_block0")), "bundle_buyers": len(bundle),
           "bundle_pct": round(b0.get("block0_share", 0), 3), "sniper_wallets": len(snipers), "pools_seen": n_pools}
    grid, price, liq = [], None, None
    i, n = 0, len(rows)
    peak, peak_t, vol, bv, sv = 0, 0, 0.0, 0.0, 0.0
    users, held = set(), {"bundle": 0.0, "sniper": 0.0, "dev": 0.0}
    bought = {"bundle": 0.0, "sniper": 0.0, "dev": 0.0}
    sold = {"bundle": 0.0, "sniper": 0.0, "dev": 0.0}
    check = {}
    for minute in range(0, 61):
        T = minute * 60
        while i < n and rows[i][0] <= T:
            t, _, x = rows[i]
            i += 1
            if x["price"]:
                price, liq = x["price"], x["liq"]
                if price > peak:
                    peak, peak_t = price, t
            vol += x["sol"]
            bv += x["sol"] if x["buy"] else 0
            sv += 0 if x["buy"] else x["sol"]
            users.add(x["user"])
            who = "dev" if x["user"] == dev else "bundle" if x["user"] in bundle else "sniper" if x["user"] in snipers else None
            if who:
                if x["buy"]:
                    bought[who] += x["tok"]
                else:
                    sold[who] += x["tok"]
        ok = T <= cover and price is not None
        grid.append(round(price / LAUNCH_PRICE, 4) if ok else None)
        if T in CHECKS:
            key = str(T // 60)
            check[key] = None if not ok else {
                "index": round(price / LAUNCH_PRICE, 4), "mc_sol": round(price * SUPPLY, 2), "liq_sol": round(liq or 0, 3),
                "volume_sol": round(vol, 3), "buy_sol": round(bv, 3), "sell_sol": round(sv, 3),
                "sell_share": round(sv / vol, 4) if vol else None, "trades": i, "traders": len(users),
                "peak_index": round(peak / LAUNCH_PRICE, 4), "drawdown_pct": round(100 * (1 - price / peak), 2),
                "liq_over_mc": round((liq or 0) / (price * SUPPLY), 4),
                "insider_sold_pct": round(100 * (sold["bundle"] + sold["sniper"]) / (bought["bundle"] + bought["sniper"]), 2)
                if bought["bundle"] + bought["sniper"] else None,
                "dev_sold_pct": round(100 * sold["dev"] / bought["dev"], 2) if bought["dev"] else None}
    out["sniper_pct"] = round(100 * bought["sniper"] / SUPPLY, 3)
    out["insider_pct"] = round(out["bundle_pct"] + out["sniper_pct"], 3)
    out["check"], out["grid"] = check, grid
    end = check.get("60")
    if end:
        out["peak_index"], out["peak_min"] = end["peak_index"], round(peak_t / 60, 2)
        out["drawdown_60"] = end["drawdown_pct"]
        out["peak_mc_sol"] = round(peak * SUPPLY, 2)
        out["shape"] = "no_pump" if end["peak_index"] < 3 else "pump_and_dump" if end["drawdown_pct"] >= 50 else "pump_and_hold"
        out["size"], out["vol_class"] = bucket(out["peak_mc_sol"], SIZE), bucket(end["volume_sol"], VOL)
    return out


def boot_median(v, n=4000, seed=7):
    r = random.Random(seed)
    b = sorted(statistics.median([r.choice(v) for _ in v]) for _ in range(n))
    return [round(b[int(.025 * n)], 2), round(b[int(.975 * n)], 2)]


def q(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p
    a = int(k)
    return v[a] + (v[min(a + 1, len(v) - 1)] - v[a]) * (k - a)


def desc(v):
    v = [x for x in v if x is not None]
    if not v:
        return {"n": 0}
    return {"n": len(v), "median": round(statistics.median(v), 3), "p25": round(q(v, .25), 3), "p75": round(q(v, .75), 3),
            "median_ci": boot_median(v) if len(v) > 1 else None}


FIELDS = ("index", "mc_sol", "liq_sol", "volume_sol", "buy_sol", "sell_share", "trades", "traders", "peak_index",
          "drawdown_pct", "liq_over_mc", "insider_sold_pct", "dev_sold_pct")


def group_table(rows):
    res = {"n": len(rows)}
    for c in ("5", "30", "60"):
        res[c + "m"] = {f: desc([r["check"][c][f] for r in rows if r["check"].get(c)]) for f in FIELDS}
    res["bundle_pct"], res["sniper_pct"], res["insider_pct"] = (desc([r[k] for r in rows]) for k in ("bundle_pct", "sniper_pct", "insider_pct"))
    res["peak_min"] = desc([r.get("peak_min") for r in rows])
    res["drawdown_60"] = desc([r.get("drawdown_60") for r in rows])
    return res


def band(rows):
    out = []
    for m in range(61):
        v = [r["grid"][m] for r in rows if r["grid"][m] is not None]
        out.append(None if len(v) < 3 else [round(q(v, .25), 4), round(statistics.median(v), 4), round(q(v, .75), 4)])
    return out


def run(day):
    by, groups, frame = sample(day)
    rows, dropped = [], []
    for g, ms in groups.items():
        for m in ms:
            txs, done, pages = history(by[m], offline=True)
            r = token_metrics(by[m], txs, done)
            if r is None:
                dropped.append(m)
                continue
            r["group"], r["pages"] = g, pages
            rows.append(r)
    use = [r for r in rows if r.get("shape")]
    shape = {s: [r for r in use if r["shape"] == s] for s in ("pump_and_dump", "pump_and_hold", "no_pump")}
    pumped = [r["drawdown_60"] for r in use if r["peak_index"] >= 3]
    h1_ci = boot_median(pumped) if len(pumped) > 1 else None
    insider = [r["insider_pct"] for r in use]
    cut = statistics.median(insider) if insider else 0
    hi = [r["drawdown_60"] for r in use if r["insider_pct"] >= cut]
    lo = [r["drawdown_60"] for r in use if r["insider_pct"] < cut]
    mw = mann_whitney(hi, lo) if hi and lo else None
    res = {"day": day, "frame": frame, "tokens_analysed": len(rows), "dropped": len(dropped), "with_full_60m": len(use),
           "incomplete": sum(not r["complete"] for r in rows),
           "shape_counts": {k: {"n": len(v), "pct": round(100 * len(v) / len(use), 1) if use else None,
                                "ci95": [round(100 * x, 1) for x in wilson(len(v), len(use))] if use else None}
                            for k, v in shape.items()},
           "H1": {"n": len(pumped), "median_drawdown": round(statistics.median(pumped), 2) if pumped else None, "ci95": h1_ci,
                  "supported": bool(h1_ci and h1_ci[0] > 50)},
           "H2": {"cut_insider_pct": round(cut, 3), "n_high": len(hi), "n_low": len(lo),
                  "median_dd_high": round(statistics.median(hi), 2) if hi else None,
                  "median_dd_low": round(statistics.median(lo), 2) if lo else None,
                  "auc": round(mw[2], 4) if mw else None,
                  "p_one_sided": round(mw[1] / 2 if mw[2] > .5 else 1 - mw[1] / 2, 5) if mw else None,
                  "supported": bool(mw and mw[2] > .5 and mw[1] / 2 < .05)},
           "all": group_table(rows),
           "by_group": {g: group_table([r for r in rows if r["group"] == g]) for g in groups},
           "by_shape": {k: group_table(v) for k, v in shape.items() if v},
           "by_size": {n: group_table([r for r in use if r["size"] == n]) for _, n in SIZE if any(r["size"] == n for r in use)},
           "by_volume": {n: group_table([r for r in use if r["vol_class"] == n]) for _, n in VOL if any(r["vol_class"] == n for r in use)},
           "coverage": {"covered_at_5m": sum(bool(r["check"].get("5")) for r in rows), "covered_at_30m": sum(bool(r["check"].get("30")) for r in rows),
                        "covered_at_60m": sum(bool(r["check"].get("60")) for r in rows),
                        "capped_covered_minutes": desc([r["covered_s"] / 60 for r in rows if not r["complete"]]),
                        "by_group_60m": {g: [sum(bool(r["check"].get("60")) for r in rows if r["group"] == g), sum(r["group"] == g for r in rows)] for g in groups}},
           "bands": {"all": band(rows), **{k: band(v) for k, v in shape.items() if len(v) >= 3}}}
    os.makedirs(EXPORT, exist_ok=True)
    with open(os.path.join(EXPORT, "study7_{}_stats.json".format(day)), "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    keys = ["mint", "group", "shape", "size", "vol_class", "complete", "covered_s", "pages", "trades", "graduated_in_block0",
            "pools_seen", "bundle_buyers", "bundle_pct", "sniper_wallets", "sniper_pct", "insider_pct", "peak_index", "peak_min",
            "peak_mc_sol", "drawdown_60"]
    with open(os.path.join(EXPORT, "study7_{}_tokens.csv".format(day)), "w", newline="") as f:
        w = csv.DictWriter(f, keys, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["mint"]):
            w.writerow(r)
    with open(os.path.join(EXPORT, "study7_{}_paths.json".format(day)), "w") as f:
        json.dump([{k: r.get(k) for k in ("mint", "group", "shape", "complete", "covered_s", "bundle_pct", "sniper_pct", "grid")} for r in sorted(rows, key=lambda x: x["mint"])], f)
    return res


if __name__ == "__main__":
    r = run(sys.argv[1])
    print(json.dumps({k: r[k] for k in ("day", "frame", "tokens_analysed", "dropped", "with_full_60m", "incomplete", "shape_counts", "H1", "H2")}, indent=1))
