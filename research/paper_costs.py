"""Round-trip fee breakevens for the paper engine, and Wilson intervals for Study 6 tail shares. No API calls.

Fee sources: pump.fun/docs/fees (last updated 2026-11-16, read 2026-11-22). Curve 1.25%; canonical PumpSwap 1.25%
below 420 SOL market cap, 1.20% at 420-1470 SOL, down to 0.30% at 98,240 SOL and up; pump.fun app Platform Fee
0.45% (0.40% with a referral code), charged in addition from 2026-10-17 on trades placed through its web/mobile app.
Per-transaction SOL costs are EXAMPLE ASSUMPTIONS. Usage: python3 -m research.paper_costs
"""
import json
import os

from research.stats import wilson

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def breakeven(side_fee_a, side_fee_b, size=None, per_tx=0.0):
    """Price rise needed to get back the stake when buying at fee a and selling at fee b."""
    spend = 1.0 if size is None else 1.0 + 2 * per_tx / size
    return round(100 * (spend / ((1 - side_fee_a) * (1 - side_fee_b)) - 1), 3)


def main():
    routes = {"curve_direct": (.0125, .0125), "curve_pump_app": (.017, .017),
              "pumpswap_420_1470_direct": (.012, .012), "pumpswap_420_1470_pump_app": (.0165, .0165),
              "curve_buy_pumpswap_sell_direct": (.0125, .012), "pumpswap_98240plus_direct": (.003, .003)}
    out = {"fee_only_breakeven_pct": {k: breakeven(*v) for k, v in routes.items()},
           "with_example_per_tx_cost_pct": {k: {"size_{}_sol_{}_per_tx".format(s, c): breakeven(*routes[k], size=s, per_tx=c)
                                                for s in (.1, .5, 1.0) for c in (.0001, .001, .005)}
                                            for k in ("curve_direct", "curve_pump_app")},
           "study6_share_worse_than_2.548pct": {}}
    for day in ("2026-11-11", "2026-11-09"):
        r = json.load(open(os.path.join(HERE, "data", "exports", "study6_{}_stats.json".format(day))))
        for g, x in r["groups"].items():
            for d in ("1", "5", "25"):
                c = x["anchors"]["25"]["drift_pct"][d]
                k = round(c["share_adverse_gt_fee_breakeven"] * c["n"])
                lo, hi = wilson(k, c["n"])
                out["study6_share_worse_than_2.548pct"]["{} {} d{}".format(day, g, d)] = {
                    "k": k, "n": c["n"], "pct": round(100 * k / c["n"], 1), "ci95": [round(100 * lo, 1), round(100 * hi, 1)]}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
