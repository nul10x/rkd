"""Study 1 analysis: deployer hold time vs 7-day survival. Offline: reads data/raw only.

Usage: python3 -m research.study1_analyze 2026-11-11
Writes data/exports/study1_<D>_tokens.csv and data/exports/study1_<D>_stats.json.
"""
import csv
import json
import os
import statistics
import sys

from collectors import client
from collectors.stage2_trace import SURV_MIN_TX, launches
from research import pump
from research.stats import bootstrap, km_median, logrank, mann_whitney, wilson

DAY = 86400
TOTAL_SUPPLY_RAW = 10 ** 15  # Pump.fun: 1e9 tokens x 1e6 decimals (checked per row below)
DUST = 0.01  # "fully out" = balance <= 1% of initial dev buy


def hold_events(l, txs):
    owner, mint, init, t0 = l["deployer"], l["mint"], l["dev_raw"], l["t0"]
    first_out = t50 = t100 = None
    out_kind, max_bal, n_out = None, init, 0
    for tx in txs:
        if tx["blockTime"] > t0 + 7 * DAY or tx["transaction"]["signatures"][0] == l["signature"]:
            continue
        pre = pump.owner_balance(tx, owner, mint, "preTokenBalances")
        post = pump.owner_balance(tx, owner, mint, "postTokenBalances")
        if pre is None and post is None:
            continue
        pre = pre or 0
        post = post if post is not None else 0
        dt = tx["blockTime"] - t0
        max_bal = max(max_bal, post)
        if post < pre:
            n_out += 1
            if first_out is None:
                first_out, out_kind = dt, pump.classify_out(tx, owner, mint)
        if t50 is None and post <= 0.5 * init:
            t50 = dt
        if t100 is None and post <= DUST * init:
            t100 = dt
    return {"first_out_s": first_out, "first_out_kind": out_kind, "t50_s": t50, "t100_s": t100,
            "n_out_tx": n_out, "max_balance_raw": max_bal}


def devbuy_test(st, L, seed=13, n_boot=2000):
    """Pre-registered KR-000006 test (fixed 2026-11-21 before holdout data was collected).
    Survivors = every on-chain-confirmed day-7 survivor with dev buy > 0 (no trace needed).
    Comparison = every confirmed-dead UNLISTED mint with dev buy > 0 from the random base-anchor draw.
    One-sided Mann-Whitney U (survivors larger), alpha 0.05; median difference with a
    two-group bootstrap 95% CI. Replicates iff one-sided p < 0.05 and the median difference > 0."""
    import random
    from collectors.stage2_trace import BASE_ANCHORS
    pct = lambda m: 100 * L[m]["dev_raw"] / TOTAL_SUPPLY_RAW
    surv = [pct(m) for m in sorted(st["day7"]) if m in L and st["day7"][m] >= SURV_MIN_TX and L[m]["dev_raw"] > 0]
    dead = [pct(m) for m in sorted(st["day7"]) if m in L and st["day7"][m] < SURV_MIN_TX and L[m]["dev_raw"] > 0
            and m not in st["dex"] and L[m]["anchor_id"] < BASE_ANCHORS]
    if not surv or not dead:
        return {"n_s": len(surv), "n_n": len(dead)}
    u, p2, auc = mann_whitney(surv, dead)
    p1 = p2 / 2 if auc > 0.5 else 1 - p2 / 2
    rng = random.Random(seed)
    diffs = sorted(statistics.median([rng.choice(surv) for _ in surv]) - statistics.median([rng.choice(dead) for _ in dead])
                   for _ in range(n_boot))
    diff = statistics.median(surv) - statistics.median(dead)
    return {"n_s": len(surv), "n_n": len(dead), "median_s": statistics.median(surv), "median_n": statistics.median(dead),
            "median_diff": diff, "median_diff_ci95": [diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1]],
            "U": u, "p_one_sided": p1, "AUC": auc, "replicates": p1 < 0.05 and diff > 0}


def summarise(rows, key):
    t = [r[key] if r[key] is not None else 7 * DAY for r in rows]
    e = [r[key] is not None for r in rows]
    med = km_median(t, e)
    lo, hi, ok = bootstrap(lambda rs: km_median([x[0] for x in rs], [x[1] for x in rs]), list(zip(t, e)), seed=11)
    within = {}
    for name, lim in (("5min", 300), ("1h", 3600), ("24h", DAY), ("7d", 7 * DAY)):
        k = sum(1 for x, ev in zip(t, e) if ev and x <= lim)
        within[name] = {"k": k, "n": len(rows), "p": k / len(rows) if rows else None, "ci95": wilson(k, len(rows))}
    return {"n": len(rows), "events": sum(e), "km_median_s": med, "km_median_ci95": [lo, hi],
            "bootstrap_defined_share": ok, "within": within}, t, e


def main(day):
    st = json.load(open(os.path.join(client.RAW, "stage2_{}.json".format(day))))
    L = {l["mint"]: l for l in launches(day)}
    rows = []
    for g, ms in st["groups"].items():
        for m in ms:
            l = L[m]
            if m not in st["traces"]:
                continue  # not traced (budget); still counted in the dev-buy test below
            txs = json.load(open(os.path.join(client.RAW, st["traces"][m]["file"])))
            ev = hold_events(l, txs)
            rows.append(dict(group=g, mint=m, deployer=l["deployer"], anchor_id=l["anchor_id"], t0=l["t0"],
                             create_sig=l["signature"], dev_buy_pct=100 * l["dev_raw"] / TOTAL_SUPPLY_RAW,
                             decimals=l["decimals"], day7_tx=st["day7"][m], dex_listed=m in st["dex"],
                             trace_tx=st["traces"][m]["n_tx"], trace_complete=st["traces"][m]["complete"], **ev))
    os.makedirs(os.path.join(client.ROOT, "data", "exports"), exist_ok=True)
    csv_path = os.path.join(client.ROOT, "data", "exports", "study1_{}_tokens.csv".format(day))
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    S = [r for r in rows if r["group"] == "survivor"]
    N = [r for r in rows if r["group"] == "non_survivor"]
    out = {"day": day, "n_launches": len(L), "dev_buy_gt0": sum(1 for l in L.values() if l["dev_raw"] > 0),
           "dex_listed": len(st["dex"]), "day7_checked": len(st["day7"]),
           "decimals_all_6": all(r["decimals"] == 6 for r in rows)}
    listed_chk = [m for m in st["day7"] if m in st["dex"]]
    unl_chk = [m for m in st["day7"] if m not in st["dex"]]
    surv_all = [m for m in st["day7"] if st["day7"][m] >= SURV_MIN_TX]
    out["listed_checked"] = len(listed_chk)
    out["listed_alive_day7"] = sum(1 for m in listed_chk if st["day7"][m] >= SURV_MIN_TX)
    out["unlisted_checked"] = len(unl_chk)
    out["unlisted_alive_day7"] = sum(1 for m in unl_chk if st["day7"][m] >= SURV_MIN_TX)
    out["unlisted_alive_ci95"] = wilson(out["unlisted_alive_day7"], len(unl_chk))
    denom = len(set(st.get("dex_checked") or L))  # launches eligible for the survival check (dev-buy only on holdout)
    out["survival_denominator"] = denom
    out["survival_rate_est"] = len(surv_all) / denom
    out["survival_rate_ci95_if_unlisted_dead"] = wilson(len(surv_all), denom)
    X = [r for r in rows if r["group"] == "listed_dead"]
    groups = {g: v for g, v in (("survivor", S), ("non_survivor", N), ("listed_dead", X)) if v}  # skip empty strata
    for key in ("first_out_s", "t50_s", "t100_s"):
        res = {}
        for g, grp in groups.items():
            res[g], _, _ = summarise(grp, key)
        for other in [g for g in ("non_survivor", "listed_dead") if g in groups]:
            _, ts, es = summarise(S, key)
            _, to, eo = summarise(groups[other], key)
            chi2, p = logrank(ts, es, to, eo)
            res["logrank_survivor_vs_" + other] = {"chi2": chi2, "p": p}
        out[key] = res
    for other in [g for g in ("non_survivor", "listed_dead") if g in groups]:
        a = [r["first_out_s"] for r in S if r["first_out_s"] is not None]
        b = [r["first_out_s"] for r in groups[other] if r["first_out_s"] is not None]
        u, p, auc = mann_whitney(a, b)
        out["first_out_uncensored_mwu_vs_" + other] = {"U": u, "p": p, "AUC_survivor_gt": auc, "n_s": len(a),
                                                     "n_o": len(b), "median_s": statistics.median(a),
                                                     "median_o": statistics.median(b)}
        out["dev_buy_pct_mwu_p_vs_" + other] = mann_whitney([r["dev_buy_pct"] for r in S],
                                                            [r["dev_buy_pct"] for r in groups[other]])[1]
    for g, grp in groups.items():
        kinds = [r["first_out_kind"] for r in grp if r["first_out_kind"]]
        out.setdefault("first_out_kind", {})[g] = {k: kinds.count(k) for k in sorted(set(kinds))}
        out.setdefault("dev_buy_pct_median", {})[g] = statistics.median(r["dev_buy_pct"] for r in grp)
        out.setdefault("anchors", {})[g] = len({r["anchor_id"] for r in grp})
        out.setdefault("n", {})[g] = len(grp)
    out["kr6_devbuy_test"] = devbuy_test(st, L)
    out["incomplete_traces"] = sum(1 for r in rows if not r["trace_complete"])
    out["api_calls_used"] = client.calls_used()
    sp = os.path.join(client.ROOT, "data", "exports", "study1_{}_stats.json".format(day))
    json.dump(out, open(sp, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
