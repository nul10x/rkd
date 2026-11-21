"""Cost of a Pump.fun round trip and the price impact of one buy on the bonding curve. No API calls.

Inputs (sources in the Logbook record): curve fee 1.25% per side (pump.fun/docs/fees, checked 2026-11-21);
curve virtual reserves 30 SOL / 1.073e9 tokens, 793.1M tokens for sale (published constants, see curve_ratios.py).
Network/priority costs per transaction are EXAMPLE ASSUMPTIONS (0.0001 / 0.001 / 0.005 SOL), not measurements.
The Pump.fun app Platform Fee (from 2026-10-17) is not included: its rate was not on the page read.

Results:
- An instant buy-then-sell on a constant-product curve returns the same SOL before fees, so the round trip
  costs only fees: breakeven move = 1/(1-f)^2 - 1, plus fixed per-tx costs relative to position size.
- Price impact of a buy sets the minimum slippage tolerance; anything above it is room for a sandwich.
Usage: python3 -m research.trade_costs
"""
import json

V_SOL0, V_TOK0, REAL_TOK = 30.0, 1.073e9, 793.1e6
FEE = 0.0125


def state(progress):
    vt = V_TOK0 - progress * REAL_TOK
    return V_SOL0 * V_TOK0 / vt, vt


def buy(vs, vt, sol_in, fee=FEE):
    net = sol_in * (1 - fee)
    k = vs * vt
    tok = vt - k / (vs + net)
    return tok, vs + net, vt - tok


def sell(vs, vt, tok, fee=FEE):
    k = vs * vt
    sol = vs - k / (vt + tok)
    return sol * (1 - fee)


def round_trip(progress, size, per_tx):
    vs, vt = state(progress)
    tok, vs2, vt2 = buy(vs, vt, size)
    back = sell(vs2, vt2, tok)
    cost = size - back + 2 * per_tx
    # price move needed so that selling at a higher price covers the cost (approx., linear in price)
    return {"loss_pct": round(100 * cost / size, 3), "breakeven_move_pct": round(100 * (size + 2 * per_tx) / back - 100, 3)}


def impact(progress, size):
    vs, vt = state(progress)
    p0 = vs / vt
    tok, vs2, vt2 = buy(vs, vt, size, fee=0.0)
    avg = size / tok
    return {"avg_price_over_spot_pct": round(100 * (avg / p0 - 1), 3), "spot_after_over_before_pct": round(100 * ((vs2 / vt2) / p0 - 1), 3)}


def main():
    sizes, prog, per_tx = (0.05, 0.1, 0.5, 1.0, 5.0), (0.0, 0.25, 0.5, 0.9), (0.0001, 0.001, 0.005)
    out = {"fee_only_breakeven_pct": round(100 * (1 / (1 - FEE) ** 2 - 1), 3),
           "round_trip_at_25pct_progress": {str(c): {str(s): round_trip(0.25, s, c) for s in sizes} for c in per_tx},
           "buy_price_impact": {str(p): {str(s): impact(p, s) for s in sizes} for p in prog}}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
