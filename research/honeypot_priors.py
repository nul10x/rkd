"""Honeypot priors: Wilson 95% CIs for published honeypot counts (no network). Usage: python3 -m research.honeypot_priors

Counts are copied from the cited papers (read 2026-11-22); this script only adds sampling intervals, which the
papers mostly do not give. Intervals cover sampling error only, not labelling error or definition differences.
- Naviglio et al. 2025, arXiv:2502.10512 (EPJ DS): Uniswap V2, 17,194 tokens launched 2024-10-02..2024-12-02;
  honeypot = flagged by GoPlus OR Honeypot.is: 15,114.
- Gan et al. 2023, DeFi@CCS 'Why Trick Me': 10,000 random Uniswap V2/V3 pools; 8,443 'abnormal' pools (abstract only).
- Wu et al. 2024, TokenScout (CCS): 214,084 ERC-20 tokens 2015..2023-02; 22,800 labelled honeypot (auditors + vendors).
- Cernera et al. 2026, arXiv:2610.10149: 3,677 Telegram P&D operations (BSC 3,649, ETH 35), 2021-05..2025-01;
  2,629 Bait-and-Trap (honeypot) operations; 1,492 honeypot tokens = 70.3% of targeted tokens.
- Chen et al. 2026, arXiv:2603.24625: 100,063 new Solana tokens (Orca, Raydium, Meteora) 2025-H1; 461 freeze-authority
  abuse (retained freeze authority AND >= 1 FreezeAccount on a user account, 24 h window); audit 1 FP in 382 (0.26%).
"""
import json

from research.stats import wilson

ROWS = [
    ("naviglio2025_uniswapv2_new_tokens_honeypot", 15114, 17194),
    ("gan2023_uniswap_random_pools_abnormal", 8443, 10000),
    ("tokenscout2024_erc20_labelled_honeypot", 22800, 214084),
    ("cernera2026_telegram_pnd_ops_honeypot", 2629, 3677),
    ("chen2026_solana_new_tokens_freeze_abuse", 461, 100063),
    ("chen2026_label_audit_false_positive", 1, 382),
]


def main():
    out = {}
    for name, k, n in ROWS:
        lo, hi = wilson(k, n)
        out[name] = {"k": k, "n": n, "p": round(k / n, 5), "ci95": [round(lo, 5), round(hi, 5)]}
    # Chen 2026 restated as a rate among the 76,469 rug-pull candidates.
    lo, hi = wilson(461, 76469)
    out["chen2026_freeze_abuse_share_of_rug_candidates"] = {"k": 461, "n": 76469, "p": round(461 / 76469, 5),
                                                            "ci95": [round(lo, 5), round(hi, 5)]}
    # Cernera 2026 Table 1: honeypot mechanism per Bait-and-Trap operation (counts sum to 2,629).
    mech = {"sell_reversion": 1902, "timed_sell_reversion": 273, "approval_reversion": 120,
            "high_buy_fee_gt90": 288, "high_sell_fee_gt90": 46}
    tot = sum(mech.values())
    out["cernera2026_mechanism_share"] = {"total": tot, **{k: {"k": v, "p": round(v / tot, 4),
                                          "ci95": [round(x, 4) for x in wilson(v, tot)]} for k, v in mech.items()}}
    # Base-rate illustration (EXAMPLE inputs): a detector with TokenScout's honeypot error rates (FNR 4.72%,
    # FPR 1.80%, Table 3, EVM) applied at different prevalences. PPV = share of flagged tokens that are honeypots.
    fnr, fpr = 0.0472, 0.0180
    out["example_ppv_by_prevalence"] = {str(prev): round((1 - fnr) * prev / ((1 - fnr) * prev + fpr * (1 - prev)), 4)
                                        for prev in (0.0046, 0.05, 0.1065, 0.5, 0.879)}
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
