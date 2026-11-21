"""Study 2 analysis (offline): Pump.fun / LaunchLab / Meteora DBC (Solana) vs Pons (Robinhood Chain), launches 2026-11-11.

Usage: python3 -m research.xchain_analyze
Writes data/exports/study2_2026-11-11_stats.json and study2_2026-11-11_tokens.csv.
"""
import csv
import glob
import json
import os
import statistics

from collectors import client
from collectors.stage2_trace import SURV_MIN_TX, launches
from collectors.xchain_rh import block_for, DAY
from research.stats import newcombe_diff, wilson

DAY_STR = "2026-11-11"
ZERO = "0x0000000000000000000000000000000000000000"
RAW = client.RAW


def load(name):
    return json.load(open(os.path.join(RAW, name)))


def rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": k / n if n else None, "ci95": [lo, hi]}


def dex_solana_pairs():
    """All cached DexScreener Solana /tokens/v1 responses -> per-mint aggregate."""
    agg = {}
    for f in glob.glob(os.path.join(RAW, "dexscreener", "*.json")):
        d = json.load(open(f))
        if d["request"].get("chain") not in (None, "solana"):
            continue
        for p in d["response"]:
            if p.get("chainId") != "solana":
                continue
            a = agg.setdefault(p["baseToken"]["address"], {"mc": 0.0, "liq": 0.0, "vol24": 0.0, "dexIds": set()})
            a["mc"] = max(a["mc"], float(p.get("marketCap") or p.get("fdv") or 0))
            a["liq"] += float((p.get("liquidity") or {}).get("usd") or 0)
            a["vol24"] += float((p.get("volume") or {}).get("h24") or 0)
            a["dexIds"].add(p.get("dexId"))
    return agg


def snapshot(mints, dex):
    listed = [dex[m] for m in mints if m in dex]
    out = {"listed": rate(len(listed), len(mints))}
    for k in ("mc", "liq", "vol24"):
        vals = [x[k] for x in listed]
        out[k] = {"listed_median": statistics.median(vals) if vals else None,
                  "listed_mean": statistics.mean(vals) if vals else None,
                  "population_mean_unlisted_as_0": sum(vals) / len(mints) if mints else None,
                  "share_listed_over_100k": (sum(1 for v in vals if v >= 1e5) / len(mints)) if (mints and k == "mc") else None}
    return out


def pons(rh):
    L = rh["launches"]
    idx = {l["token"]: i for i, l in enumerate(L)}
    grads = {g["token"] for g in rh["graduations"] if g["token"] in idx}
    covered24 = set()
    tr = {}
    for k, logs in rh["transfers_24h"].items():
        covered24 |= {L[i]["token"] for i in range(int(k), min(int(k) + 100, len(L)))}
        for t, frm, to, val, blk, tx in logs:
            tr.setdefault(t, []).append((blk, frm, to, val, tx))
    covered7 = set()
    d7 = {}
    for k, logs in rh["transfers_d7"].items():
        covered7 |= {L[i]["token"] for i in range(int(k), min(int(k) + 100, len(L)))}
        for t, blk in logs:
            d7.setdefault(t, []).append(blk)
    rows = []
    for l in L:
        t = l["token"]
        row = {"chain": "robinhood", "pad": "pons", "mint": t, "deployer": l["deployer"], "t0": l["t0"],
               "graduated_d10": t in grads, "pair_token": l["pair_token"]}
        if t in covered7:
            lo, hi = block_for(l["t0"] + 6 * DAY), block_for(l["t0"] + 7 * DAY)
            row["day7_events"] = sum(1 for b in d7.get(t, []) if lo <= b < hi)
        if t in covered24:
            ev = sorted(tr.get(t, []))
            end24, end1h = block_for(l["t0"] + DAY), block_for(l["t0"] + 3600)
            dev_buy = sum(v for b, f, to, v, tx in ev if tx == l["tx"] and to == l["deployer"])
            bal, t100 = 0, None
            for b, f, to, v, tx in ev:
                if b > end24:
                    break
                if to == l["deployer"]:
                    bal += v
                if f == l["deployer"]:
                    bal -= v
                if dev_buy and t100 is None and b > l["block"] and bal <= 0.01 * dev_buy:
                    t100 = b
            buyers = {to for b, f, to, v, tx in ev if b <= end24 and f == l["curve"] and to not in (l["deployer"], ZERO)}
            sellers = {f for b, f, to, v, tx in ev if b <= end24 and to == l["curve"] and f not in (l["deployer"], ZERO)}
            row.update(dev_buy_pct=100 * dev_buy / 1e27, dev_out_1h=(t100 is not None and t100 <= end1h) if dev_buy else None,
                       dev_out_24h=(t100 is not None) if dev_buy else None, buyers_24h=len(buyers), sellers_24h=len(sellers),
                       transfers_24h=sum(1 for e in ev if e[0] <= end24))
        rows.append(row)
    return rows, covered24, covered7


def main():
    out = {"launch_day": DAY_STR, "snapshot": "2026-11-21 (day 10)"}
    rows = []
    # --- Pump.fun (study-1 sample) ---
    Lp = launches(DAY_STR)
    s2 = load("stage2_{}.json".format(DAY_STR))
    pg = load("xchain_pump_grad_{}.json".format(DAY_STR))
    dex = dex_solana_pairs()
    pm = [l["mint"] for l in Lp]
    alive = [m for m in s2["day7"] if s2["day7"][m] >= SURV_MIN_TX]
    t100 = list(csv.DictReader(open(os.path.join(client.ROOT, "data", "exports", "study1_{}_tokens.csv".format(DAY_STR)))))
    rnd = [r for r in t100 if r["group"] == "non_survivor"]
    out["pumpfun"] = {
        "n": len(pm), "dev_buy_gt0": rate(sum(1 for l in Lp if l["dev_raw"] > 0), len(pm)),
        "graduated_d10_lower_bound": rate(sum(1 for m in pm if pg["complete"].get(m) == 1), len(pm)),
        "curve_account_closed": sum(1 for m in pm if pg["complete"].get(m) is None),
        "day7_alive_lower_bound": rate(len(alive), len(pm)),
        "snapshot": snapshot(pm, dex),
        "dev_full_exit_1h_random_dead": rate(sum(1 for r in rnd if r["t100_s"] not in ("", None) and float(r["t100_s"]) <= 3600), len(rnd)),
        "dev_full_exit_24h_random_dead": rate(sum(1 for r in rnd if r["t100_s"] not in ("", None) and float(r["t100_s"]) <= DAY), len(rnd)),
        "dev_buy_pct_median_devbuyers": statistics.median(100 * l["dev_raw"] / 1e15 for l in Lp if l["dev_raw"] > 0),
    }
    for l in Lp:
        d = dex.get(l["mint"], {})
        rows.append({"chain": "solana", "pad": "pumpfun", "mint": l["mint"], "deployer": l["deployer"], "t0": l["t0"],
                     "graduated_d10": pg["complete"].get(l["mint"]) == 1, "day7_events": s2["day7"].get(l["mint"]),
                     "dev_buy_pct": 100 * l["dev_raw"] / 1e15, "dex_mc": d.get("mc"), "dex_liq": d.get("liq"), "dex_vol24": d.get("vol24")})
    # --- other Solana pads ---
    sp = load("xchain_sol_pads_{}.json".format(DAY_STR))
    for pad, P in sorted(sp["pads"].items()):
        seen, L = set(), []
        for k in sorted(P["anchors"], key=int):
            for l in P["anchors"][k]["launches"]:
                if l["mint"] not in seen:
                    seen.add(l["mint"]); L.append(l)
        ms = [l["mint"] for l in L]
        al = [m for m in P["day7"] if P["day7"][m] >= SURV_MIN_TX]
        unl = [m for m in P["day7"] if m not in dex]
        out[pad] = {"n": len(ms), "anchors": len(P["anchors"]), "dev_buy_gt0": rate(sum(1 for l in L if l["dev_raw"] > 0), len(ms)),
                    "day7_alive_lower_bound": rate(len(al), len(ms)), "unlisted_checked_alive": rate(sum(1 for m in unl if P["day7"][m] >= SURV_MIN_TX), len(unl)),
                    "snapshot": snapshot(ms, dex),
                    "median_txs_per_anchor_span_s": statistics.median(a["span_s"] for a in P["anchors"].values() if a["span_s"])}
        for l in L:
            rows.append({"chain": "solana", "pad": pad, "mint": l["mint"], "deployer": l["deployer"], "t0": l["t0"],
                         "day7_events": P["day7"].get(l["mint"]), "dev_buy_pct": None})
    # --- Pons ---
    rh = load("xchain_rh_{}.json".format(DAY_STR))
    pr, c24, c7 = pons(rh)
    rows += pr
    n = len(pr)
    sub24 = [r for r in pr if "buyers_24h" in r]
    sub7 = [r for r in pr if "day7_events" in r]
    db = [r for r in sub24 if r["dev_out_1h"] is not None]
    rh_dex = [p for v in rh.get("dex", {}).values() for p in v]
    out["pons"] = {
        "n": n, "graduated_d10": rate(sum(r["graduated_d10"] for r in pr), n),
        "eth_paired": rate(sum(1 for r in pr if r["pair_token"] == ZERO), n),
        "day7_alive_subset": rate(sum(1 for r in sub7 if r["day7_events"] >= SURV_MIN_TX), len(sub7)),
        "subset_24h_n": len(sub24), "subset_24h_first_t0": min(r["t0"] for r in sub24), "subset_24h_last_t0": max(r["t0"] for r in sub24),
        "dev_buy_gt0": rate(len(db), len(sub24)),
        "dev_buy_pct_median_devbuyers": statistics.median(r["dev_buy_pct"] for r in db) if db else None,
        "dev_full_exit_1h": rate(sum(1 for r in db if r["dev_out_1h"]), len(db)),
        "dev_full_exit_24h": rate(sum(1 for r in db if r["dev_out_24h"]), len(db)),
        "buyers_24h_median": statistics.median(r["buyers_24h"] for r in sub24),
        "buyers_24h_mean": statistics.mean(r["buyers_24h"] for r in sub24),
        "buyers_24h_zero_share": rate(sum(1 for r in sub24 if r["buyers_24h"] == 0), len(sub24)),
        "buyers_24h_ge10_share": rate(sum(1 for r in sub24 if r["buyers_24h"] >= 10), len(sub24)),
        "dexscreener_checked": 30, "dexscreener_listed": len({p["baseToken"]["address"].lower() for p in rh_dex}),
    }
    pf, po = out["pumpfun"], out["pons"]
    out["diff_pumpfun_minus_pons"] = {
        "graduated_d10": newcombe_diff(pf["graduated_d10_lower_bound"]["k"], pf["n"], po["graduated_d10"]["k"], po["n"]),
        "day7_alive": newcombe_diff(pf["day7_alive_lower_bound"]["k"], pf["n"], po["day7_alive_subset"]["k"], po["day7_alive_subset"]["n"]),
        "dev_full_exit_1h": newcombe_diff(pf["dev_full_exit_1h_random_dead"]["k"], pf["dev_full_exit_1h_random_dead"]["n"],
                                          po["dev_full_exit_1h"]["k"], po["dev_full_exit_1h"]["n"]),
    }
    pk = load("xchain_peaks_{}.json".format(DAY_STR))
    out["peaks_measured"] = pk
    # Pre-registered in KR-000010: Runner_100k / Runner_1M = 7-day peak MC >= $100k / $1M (graduates only);
    # Rug (price) = last 7-day close <= 10% of the 7-day peak. Graduates without a GeckoTerminal pool or candles
    # are reported as unmeasured, not as non-runners.
    pons_grads = sum(r["graduated_d10"] for r in pr)
    runners = {}
    for net, n_launch, n_grad in (("solana", len(pm), pf["graduated_d10_lower_bound"]["k"]), ("robinhood", n, pons_grads)):
        v = [x for k, x in pk.items() if k.startswith(net + ":")]
        m = [x for x in v if x.get("peak_mc")]
        r100 = sum(1 for x in m if x["peak_mc"] >= 1e5)
        r1m = sum(1 for x in m if x["peak_mc"] >= 1e6)
        rug = sum(1 for x in m if x["last_close_over_peak"] is not None and x["last_close_over_peak"] <= 0.10)
        runners[net] = {
            "launches": n_launch, "graduates": n_grad, "graduates_queried": len(v), "measured": len(m),
            "no_pool": sum(1 for x in v if x.get("pool") is None), "no_candles": sum(1 for x in v if x.get("pool") and not x.get("peak_mc")),
            "runner_100k_of_measured": rate(r100, len(m)) if m else None, "runner_1m_of_measured": rate(r1m, len(m)) if m else None,
            "runner_100k_per_launch": rate(r100, n_launch), "runner_1m_per_launch": rate(r1m, n_launch),
            "rug_price_of_measured": rate(rug, len(m)) if m else None,
            "peak_mc_median": statistics.median(x["peak_mc"] for x in m) if m else None,
            "peak_mc_max": max((x["peak_mc"] for x in m), default=None),
            "last_over_peak_median": statistics.median(x["last_close_over_peak"] for x in m) if m else None,
        }
    out["runners"] = runners
    out["api_calls"] = json.load(open(os.path.join(RAW, "usage_xchain.json")))["calls"]
    ex = os.path.join(client.ROOT, "data", "exports")
    keys = sorted({k for r in rows for k in r})
    with open(os.path.join(ex, "study2_{}_tokens.csv".format(DAY_STR)), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    json.dump(out, open(os.path.join(ex, "study2_{}_stats.json".format(DAY_STR)), "w"), indent=1, sort_keys=True, default=list)
    print(json.dumps(out, indent=1, sort_keys=True, default=list))


if __name__ == "__main__":
    main()
