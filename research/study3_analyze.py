"""Study 3 analysis (plan KR-000016, pilot KR-000017). Reads data/raw only and never calls the network:
a response that is not cached counts as missing.
Usage: python3 -m research.study3_analyze 2026-11-11
Writes data/exports/study3_<day>_stats.json and study3_<day>_tokens.csv.
"""
import csv
import json
import os
import statistics
import sys

from collectors import client
from collectors import study3 as S
from collectors.stage2_trace import DAY, MAX_TRACE_PAGES, SURV_MIN_TX
from research import study3_parse as P
from research.pump import WSOL
from research.stats import bootstrap, mann_whitney, newcombe_diff, wilson

H = 3600


def from_cache(provider, key):
    p = client._cache_path(provider, key)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)["response"]


def helius(method, params):
    r = from_cache("helius", {"method": method, "params": params})
    return None if r is None else r["result"]


def mint_page(l):
    return helius("getTransactionsForAddress", [l["mint"], dict(S.FULL, sortOrder="asc", limit=100, filters={
        "blockTime": {"gte": l["t0"], "lte": l["t0"] + H}, "status": "succeeded"})])


def ata_trace(ata, t0):
    """Cached pages of collectors.stage2_trace.trace (same request keys)."""
    txs, token = [], None
    for _ in range(MAX_TRACE_PAGES):
        opts = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                "sortOrder": "asc", "limit": 100,
                "filters": {"blockTime": {"gte": t0, "lte": t0 + 7 * DAY}, "status": "succeeded"}}
        if token:
            opts["paginationToken"] = token
        r = helius("getTransactionsForAddress", [ata, opts])
        if r is None:
            return None
        txs += r["data"]
        token = r.get("paginationToken")
        if not token or len(r["data"]) < 100:
            return txs
    return txs


def rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": k / n if n else None, "ci95": [lo, hi]}


def med_ci(vals, seed):
    if not vals:
        return {"n": 0}
    lo, hi, _ = bootstrap(lambda r: statistics.median(r), vals, n=2000, seed=seed)
    return {"n": len(vals), "median": statistics.median(vals), "ci95": [lo, hi]}


def mw(a, b):
    if not a or not b:
        return {"n1": len(a), "n2": len(b)}
    u, p, auc = mann_whitney(a, b)
    return {"n1": len(a), "n2": len(b), "U": u, "p": p, "auc": auc}


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [None] * len(ps), 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        adj[i] = run
    return adj


def part_a(day, L, grads, non):
    rows = []
    for m in grads + non:
        l = L[m]
        pg = mint_page(l)
        row = {"part": "a", "mint": m, "group": "graduate" if m in grads else "non_graduate", "anchor_id": l["anchor_id"],
               "dev_buy_pct": 100 * l["dev_raw"] / P.SUPPLY_RAW}
        if pg is None:
            row["missing"] = True
            rows.append(row)
            continue
        txs = pg["data"]
        row.update(P.block0(txs, l))
        if not l.get("dev_ata"):  # no dev buy: no deployer holding to exit (collector fix 2026-11-21)
            src, row["dev_exit_source"] = None, "no_dev_buy"
        else:
            src = txs if len(txs) < 100 else ata_trace(l["dev_ata"], l["t0"])
            row["dev_exit_source"] = "mint_page" if len(txs) < 100 else ("ata_trace" if src is not None else "missing")
        if src is not None:
            ex = P.dev_exit(src, l, H)
            row["dev_exit_1h"] = ex is not None
            row["dev_exit_s"] = ex
        rows.append(row)
    ok = [r for r in rows if r.get("create_found")]
    g = [r for r in ok if r["group"] == "graduate"]
    n = [r for r in ok if r["group"] == "non_graduate"]
    out = {"n_graduates": len(grads), "n_non_sample": len(non), "parsed_graduates": len(g), "parsed_non": len(n),
           "missing_or_unparsed": len(rows) - len(ok)}
    out["H3a_mw_block0_share"] = mw([r["block0_share"] for r in g], [r["block0_share"] for r in n])
    out["block0_share_median"] = {"graduate": med_ci([r["block0_share"] for r in g], 11), "non": med_ci([r["block0_share"] for r in n], 12)}
    kg, kn = sum(r["block0_buyers"] > 0 for r in g), sum(r["block0_buyers"] > 0 for r in n)
    out["block0_any"] = {"graduate": rate(kg, len(g)), "non": rate(kn, len(n)), "diff": newcombe_diff(kg, len(g), kn, len(n))}
    # Population rate: graduates are a census, non-graduates a random sample; reweight by sampling fraction.
    n_non_pop = len(L) - len(grads)
    w = n_non_pop / len(n) if n else None
    out["block0_any_population_est"] = (kg + kn * w) / (len(g) + len(n) * w) if w else None
    # Sensitivity (pilot deviation 2): drop tokens that graduated inside the creation slot.
    g2 = [r for r in g if not r["graduated_in_block0"]]
    out["sens_excl_block0_graduation"] = {"n_graduated_in_block0": len(g) - len(g2),
                                          "mw": mw([r["block0_share"] for r in g2], [r["block0_share"] for r in n])}
    # Anchor-cluster sensitivity: bootstrap of the median difference by anchor.
    by_anchor = {}
    for r in ok:
        by_anchor.setdefault(r["anchor_id"], []).append(r)
    anchors = sorted(by_anchor)

    def md(sample_anchors):
        rs = [r for a in sample_anchors for r in by_anchor[a]]
        a1 = [r["block0_share"] for r in rs if r["group"] == "graduate"]
        b1 = [r["block0_share"] for r in rs if r["group"] == "non_graduate"]
        return statistics.median(a1) - statistics.median(b1) if a1 and b1 else None
    lo, hi, _ = bootstrap(md, anchors, n=2000, seed=13)
    out["anchor_bootstrap_median_diff_ci95"] = [lo, hi]
    out["n_anchors"] = len(anchors)
    # Secondary: dev exit within 1 h by block0_any.
    d = [r for r in ok if "dev_exit_1h" in r]
    b1 = [r for r in d if r["block0_buyers"] > 0]
    b0 = [r for r in d if r["block0_buyers"] == 0]
    k1, k0 = sum(r["dev_exit_1h"] for r in b1), sum(r["dev_exit_1h"] for r in b0)
    out["dev_exit_1h_by_block0"] = {"block0": rate(k1, len(b1)), "no_block0": rate(k0, len(b0)), "diff": newcombe_diff(k1, len(b1), k0, len(b0)),
                                    "dev_exit_unknown": len(ok) - len(d)}
    out["comparisons_looked_at"] = 5
    return rows, out


def part_b(day, L, b):
    rows = []
    for m in b:
        l = L[m]
        row = {"part": "b", "mint": m, "anchor_id": l["anchor_id"]}
        pools = from_cache("geckoterminal", {"pools": ["solana", m]})
        pool, created = S.pumpswap_pool(pools) if pools else (None, None)
        if not pool:
            row["missing"] = "no_pumpswap_pool" if pools else "pools_not_cached"
            rows.append(row)
            continue
        T = created + H
        row.update(pool=pool, pool_created=created, T=T)
        d7 = helius("getTransactionsForAddress", [m, {"transactionDetails": "signatures", "sortOrder": "asc", "limit": SURV_MIN_TX,
                                                       "filters": {"blockTime": {"gte": l["t0"] + 6 * DAY, "lt": l["t0"] + 7 * DAY}, "status": "succeeded"}}])
        if d7 is not None:
            row["day7_alive"] = len(d7["data"]) >= SURV_MIN_TX
        pt = helius("getTransactionsForAddress", [pool, dict(S.FULL, sortOrder="desc", limit=100, filters={"blockTime": {"lte": T}, "status": "succeeded"})])
        if pt is not None:
            s, t, bt = P.latest_state(pt["data"], pool, m, WSOL)
            if s and t:
                mc_sol = s / t * 1e9
                vol = sum(P.sol_volume(e, pool, WSOL) for e in pt["data"])
                row.update(sol_reserve=s, tok_reserve=t, state_age_s=T - bt, mc_sol_T=mc_sol, liq_over_mc=2 * s / mc_sol,
                           pool_supply_share=t / 1e9, vol_sol_last100=vol, payers_last100=len({P.fee_payer(e) for e in pt["data"]}),
                           traders_per_sol=len({P.fee_payer(e) for e in pt["data"]}) / vol if vol else None)
        before = int(l["t0"] + 7 * DAY + H)
        oh = from_cache("geckoterminal", {"ohlcv_hour": ["solana", pool, before]})
        if oh is not None:
            c = sorted(((oh.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [])
            hT, h0 = T - T % H, created - created % H
            atT = [x for x in c if x[0] == hT] or [x for x in c if x[0] < hT][-1:]
            if atT:
                close_T = atT[0][4]
                first = sum(x[5] for x in c if h0 <= x[0] <= hT)
                after = [x for x in c if hT < x[0] < l["t0"] + 7 * DAY]
                last = after[-1][4] if after else close_T
                row.update(close_T=close_T, mc_usd_T=close_T * 1e9, vol_usd_first=first,
                           vol_over_mc=first / (close_T * 1e9) if close_T else None,
                           max_high_after=max((x[2] for x in after), default=None),
                           runner_2x=bool(after) and max(x[2] for x in after) >= 2 * close_T,
                           rug_from_T=last <= 0.1 * close_T, n_candles_after=len(after))
        rows.append(row)
    ok = [r for r in rows if "runner_2x" in r]
    out = {"n_b_sample": len(b), "with_pool": sum(1 for r in rows if r.get("pool")), "with_outcome": len(ok),
           "runner_2x": rate(sum(r["runner_2x"] for r in ok), len(ok)), "rug_from_T": rate(sum(r["rug_from_T"] for r in ok), len(ok)),
           "day7_alive": rate(sum(1 for r in rows if r.get("day7_alive")), sum(1 for r in rows if "day7_alive" in r))}
    tests, ps = {}, []
    for k in ("liq_over_mc", "vol_over_mc", "traders_per_sol"):
        a = [r[k] for r in ok if r["runner_2x"] and r.get(k) is not None]
        c = [r[k] for r in ok if not r["runner_2x"] and r.get(k) is not None]
        tests[k] = {"mw_runner_vs_not": mw(a, c), "median_runner": med_ci(a, 21), "median_not": med_ci(c, 22)}
        ps.append(tests[k]["mw_runner_vs_not"].get("p", 1.0))
    for k, pa in zip(("liq_over_mc", "vol_over_mc", "traders_per_sol"), holm(ps)):
        tests[k]["holm_p"] = pa
    out["H3b"] = tests
    sec = {}
    for k in ("liq_over_mc", "vol_over_mc", "traders_per_sol"):
        a = [r[k] for r in ok if r["rug_from_T"] and r.get(k) is not None]
        c = [r[k] for r in ok if not r["rug_from_T"] and r.get(k) is not None]
        sec[k] = mw(a, c)
    out["secondary_rug_from_T"] = sec
    out["comparisons_looked_at"] = 6
    return rows, out


def main(day):
    L, grads, non, b = S.sample(day)
    ra, oa = part_a(day, L, grads, non)
    rb, ob = part_b(day, L, b)
    out = {"launch_day": day, "plan": "KR-000016", "pilot": "KR-000017", "n_launches": len(L), "a": oa, "b": ob,
           "api_calls_usage_study3": json.load(open(os.path.join(client.RAW, "usage_study3.json")))["calls"]}
    ex = os.path.join(client.ROOT, "data", "exports")
    rows = ra + rb
    keys = sorted({k for r in rows for k in r})
    with open(os.path.join(ex, "study3_{}_tokens.csv".format(day)), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(ex, "study3_{}_stats.json".format(day)), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
