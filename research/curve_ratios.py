"""Mechanical liquidity/market-cap ratio of a Pump.fun token on the bonding curve and at graduation.

No API calls. Constants are the published Pump.fun curve parameters (virtual reserves 30 SOL /
1,073,000,000 tokens, 793,100,000 real tokens for sale, 1e9 supply) and the post-migration PumpSwap
pool state reported in arXiv:2602.14860 (about 85 SOL / 206.9M tokens). They are unverified on-chain here.

Point: before and at graduation, liquidity/MC is a function of curve progress only, so it carries no
information about a token beyond how far along the curve it is. Only after migration can it vary
(LP adds/removals, trading), which is where a ratio screen could possibly say something.
Usage: python3 -m research.curve_ratios
"""
import json

V_SOL0, V_TOK0, REAL_TOK, SUPPLY = 30.0, 1.073e9, 793.1e6, 1e9
POOL_SOL, POOL_TOK = 85.0, 0.2069e9


def curve_state(sold):
    """Virtual reserves after `sold` tokens have been bought off the curve (constant product)."""
    vt = V_TOK0 - sold
    vs = V_SOL0 * V_TOK0 / vt
    return vs, vt


def row(frac):
    sold = frac * REAL_TOK
    vs, vt = curve_state(sold)
    price = vs / vt
    mc = price * SUPPLY
    real_sol = vs - V_SOL0
    # Two-sided "liquidity" as DEX screeners count it: SOL in the pool + token side at spot price.
    tok_left = REAL_TOK - sold
    liq = real_sol + tok_left * price
    return {"curve_progress": frac, "real_sol_in": round(real_sol, 3), "mc_sol": round(mc, 3),
            "liq_two_sided_sol": round(liq, 3), "liq_over_mc": round(liq / mc, 4)}


def main():
    out = {"curve": [row(f) for f in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)]}
    p = POOL_SOL / POOL_TOK
    out["pumpswap_at_migration"] = {"mc_sol": round(p * SUPPLY, 3), "liq_two_sided_sol": 2 * POOL_SOL,
                                    "liq_over_mc": round(2 * POOL_SOL / (p * SUPPLY), 4)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
