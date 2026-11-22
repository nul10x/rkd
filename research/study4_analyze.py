"""Study 4 analysis (plan KR-000039). Reads data/raw only and never calls the network; an uncached page is missing.
Usage: python3 -m research.study4_analyze 2026-11-11 [N_LAUNCHES]
Writes data/exports/study4_<day>_stats.json and study4_<day>_tokens.csv (full runs only).
"""
import csv
import json
import os
import statistics
import sys

from collectors import client
from collectors import study4 as C
from research import study3_analyze as A3
from research import study4_funding as F
from research.stats import bootstrap, mann_whitney, newcombe_diff, wilson


def page(w, t0):
    r = A3.helius("getTransactionsForAddress", C.wallet_params(w, t0))
    return None if r is None else r["data"]


def rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": k / n if n else None, "ci95": [lo, hi]}


def build(day, n=None):
    coh = C.cohort(day, A3.mint_page)
    if n:
        coh = coh[:n]
    pages = []
    for l, buyers in coh:
        pages.append((l, buyers, page(l["deployer"], l["t0"]), {b: page(b, l["t0"]) for b in buyers}))
    lf = {l["mint"]: F.launch_funders(l["deployer"], dp or [], bp) for l, _, dp, bp in pages}
    hub = F.hubs(lf)
    return pages, hub


def rows_for(pages, hub, hubs_in_2hop=True, hub_set=None, covered_only=False):
    hs = hub if hub_set is None else hub_set
    rows = []
    for l, buyers, dp, bp in pages:
        if covered_only:  # sensitivity (pilot amendment): drop busy buyer pages (100 txs, partial 7-day window)
            bp = {b: t for b, t in bp.items() if t is not None and len(t) < F.PAGE_LIMIT}
            buyers = {b: v for b, v in buyers.items() if b in bp}
            if not bp:
                continue
        row = {"mint": l["mint"], "anchor_id": l["anchor_id"], "group": "graduate" if l["graduate"] else "non_graduate",
               "n_buyers": len(buyers), "dev_page_missing": dp is None}
        if dp is None:
            rows.append(row)
            continue
        r = F.classify(l["deployer"], dp, bp, hs, hubs_in_2hop)
        tot = sum(buyers.values())
        linked = [b for b, v in r["buyers"].items() if v.get("linked")]
        row.update(dev_linked=r["dev_linked"], coordinated_not_dev=r["coordinated_not_dev"],
                   buyer_to_buyer_funding=r["buyer_to_buyer_funding"], dev_page_busy=r["dev_page_busy"],
                   dev_page_txs=len(dp), n_linked=len(linked),
                   n_direct=sum(1 for v in r["buyers"].values() if v.get("direct")),
                   n_two_hop=sum(1 for v in r["buyers"].values() if v.get("two_hop")),
                   n_shared=sum(1 for v in r["buyers"].values() if v.get("shared_funder")),
                   n_busy=sum(1 for v in r["buyers"].values() if v.get("busy")),
                   n_missing=sum(1 for v in r["buyers"].values() if v.get("missing")),
                   n_fresh=sum(1 for v in r["buyers"].values() if not v.get("missing") and v["n_txs"] <= 5),
                   block0_share=100.0 * tot / 1e15,
                   dev_linked_share=100.0 * sum(buyers[b] for b in linked) / 1e15)
        rows.append(row)
    return rows


def summary(rows, seed):
    ok = [r for r in rows if "dev_linked" in r]
    g = [r for r in ok if r["group"] == "graduate"]
    n = [r for r in ok if r["group"] == "non_graduate"]
    out = {"parsed": len(ok), "dev_page_missing": len(rows) - len(ok)}
    for k in ("dev_linked", "coordinated_not_dev", "buyer_to_buyer_funding"):
        kg, kn = sum(r[k] for r in g), sum(r[k] for r in n)
        out[k] = {"graduate": rate(kg, len(g)), "non": rate(kn, len(n)), "diff": newcombe_diff(kg, len(g), kn, len(n))}
    if g and n:
        u, p, auc = mann_whitney([r["dev_linked_share"] for r in g], [r["dev_linked_share"] for r in n])
        out["dev_linked_share_mw"] = {"U": u, "p": p, "auc": auc,
                                      "median_graduate": statistics.median(r["dev_linked_share"] for r in g),
                                      "median_non": statistics.median(r["dev_linked_share"] for r in n)}
        by = {}
        for r in ok:
            by.setdefault(r["anchor_id"], []).append(r)

        def d(anchors):
            rs = [r for a in anchors for r in by[a]]
            a1 = [r["dev_linked"] for r in rs if r["group"] == "graduate"]
            b1 = [r["dev_linked"] for r in rs if r["group"] == "non_graduate"]
            return sum(a1) / len(a1) - sum(b1) / len(b1) if a1 and b1 else None
        lo, hi, _ = bootstrap(d, sorted(by), n=2000, seed=seed)
        out["anchor_bootstrap_diff_ci95"] = [lo, hi]
        out["n_anchors"] = len(by)
    nb = sum(r["n_buyers"] for r in ok)
    out["buyers"] = {"n": nb, "linked": sum(r["n_linked"] for r in ok), "direct": sum(r["n_direct"] for r in ok),
                     "two_hop": sum(r["n_two_hop"] for r in ok), "shared": sum(r["n_shared"] for r in ok),
                     "busy": sum(r["n_busy"] for r in ok), "missing": sum(r["n_missing"] for r in ok),
                     "fresh_le5_txs": sum(r["n_fresh"] for r in ok)}
    return out


def main(day, n=None):
    pages, hub = build(day, n)
    rows = rows_for(pages, hub)
    out = {"launch_day": day, "plan": "KR-000039", "n_launches": len(pages), "n_hubs": len(hub),
           "primary": summary(rows, 41),
           "sens_no_hub_exclusion": summary(rows_for(pages, hub, hub_set=set()), 42),
           "sens_hubs_excluded_from_2hop": summary(rows_for(pages, hub, hubs_in_2hop=False), 43),
           "sens_covered_buyers_only": summary(rows_for(pages, hub, covered_only=True), 44),
           "comparisons_looked_at": 4}
    if n:
        print(json.dumps(out, indent=1, sort_keys=True))
        return rows
    out["api_calls_usage_study4"] = json.load(open(os.path.join(client.RAW, "usage_study4.json")))["calls"]
    ex = os.path.join(client.ROOT, "data", "exports")
    keys = sorted({k for r in rows for k in r})
    with open(os.path.join(ex, "study4_{}_tokens.csv".format(day)), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(ex, "study4_{}_stats.json".format(day)), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
