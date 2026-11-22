# Risk signals for the scanner and bots (Researcher → Builder)

Version 2, 2026-11-22 (v1: 7f864cf). v2 changes: the freeze flag applies to every mint (the 30-day rule was a study sampling rule, not an exemption); quote-asset allowlist named; study 5 primary rates added (KR-000050). Source of truth is the Logbook; every number below is copied from the cited record, which
holds the method, n and limitations. Edge check (`rkd-edge-check`, team rule KR-000027) applied: none of these is a
trading edge or a buy signal. They are risk context. Costs are not applicable because no return is claimed.

Labels used:
- **fact**: read directly from chain state; deterministic; no prediction.
- **replicated association**: pre-registered, same direction on a holdout day (status `historically_supported`).
- **hypothesis**: literature or one in-sample result; not yet measured out of sample by RKD.

Wording rules for every output: never "safe", "legit", "buy", "will pump" or "rug-proof". Say what was measured,
show the data timestamp, the source, n and the label. Absence of a flag means "not seen in the data read", not safe.

## 1. Honeypot (cannot sell)

| Signal | Rule | Label | Evidence | Records |
|---|---|---|---|---|
| Freeze authority retained | mint `freezeAuthority` non-null, on **every** mint (any age) | **fact** (capability) + measured rate (in-sample) | Holder accounts can be frozen; a frozen holder cannot sell. Study 5 (Raydium CPMM pools 2026-10-01..11-04, KR-000050, holdout pending): 248 of 3,366 new non-launchpad tokens kept it (7.4%, CI 6.5–8.3%); of 231 new ones, **47 froze holders within 7 days = 20.3% (CI 15.7–26.0%, lower bound)**; median first freeze 88 s after pool creation. Rates are measured on tokens up to 30 days old; for older tokens the use rate is not measured, so show the capability without a rate. | KR-000022, KR-000046, KR-000050 |
| Freeze authority used | spl-token `freezeAccount` on this mint by the authority on an account it does not own | **fact** (event) | Confirmed honeypot behaviour. Pilot example: one new CPMM token froze 4 buyer accounts at +175 s to +1,478 s after its pool opened (n=1, example only). | KR-000048 |
| Token-2022 sell-block capability | extension `transferHook` with a programId, `permanentDelegate` with a delegate, `defaultAccountState = frozen`, or `nonTransferable` | **fact** (capability) | Each can block or reverse a sale (primary docs). Study 5 (KR-000050, 3,366 new non-launchpad CPMM tokens): transfer hook 0, default frozen 0, non-transferable 0 (each CI 0–0.11%), permanent delegate 6 (0.18%), transfer fee 75 (2.2%, capability only, not simulated). Pump.fun: 0 of 1,000 random 2026-11-11 mints had freeze or mint authority or any of these (CI 0–0.38%). | KR-000022, KR-000048 |
| Quote-asset allowlist | exactly these mints: USDC `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`, USDT `Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB` | **fact** | Issuer-controlled stablecoins keep a freeze authority by design. Show it as info ("issuer can freeze: Circle/Tether"), not as a honeypot flag. No other exemption: mint age does **not** remove the freeze flag. | KR-000048 |
| EVM tokens (e.g. Robinhood Chain) | buy-then-sell simulation on current state, plus static blocklist check | **hypothesis** for rates | Measured prevalence 10.7%–87.9% depending on definition; sell-reversion is 72.3% of trap mechanisms (CI 70.6–74.0%, n=2,629 operations); simulation misses blocklists. | KR-000045 |

Base-rate note (KR-000045/046): where honeypots are rare (~0.5% on Solana), a probabilistic detector with 1.8% false
positives is right on only ~20% of its flags. Prefer the deterministic facts above and show the capability, not a verdict.

## 2. Bundled / manufactured launch (Pump.fun)

| Signal | Rule | Label | Evidence | Records |
|---|---|---|---|---|
| Block-0 buyer cluster | non-deployer net receivers in the creation slot (`research/study3_parse.block0`) | **replicated association** | Graduates vs non-graduates: 79.5% vs 25.7% (2026-11-11, n=73/300) and 88.7% vs 18.0% (holdout 2026-11-09, n=115/300). Median block-0 share of supply among graduates 20% / 33%. Meaning: "graduated" is often bought, not organic demand. | KR-000036, KR-000038 |
| Graduated in its creation slot | Migrate instruction in the create slot | **fact** + replicated share | 41.1% (30/73) and 60.0% (69/115) of graduates. | KR-000036, KR-000038 |
| Dev funded the block-0 buyers | funding link deployer → buyer (direct, 2-hop, shared funder) before launch | **hypothesis** (study 4 collected, analysis pending) | Will be added with numbers when study 4 is filed. | KR-000039, KR-000040 |

Contradiction to show: KR-000015 (literature) says group buying does not predict graduation; KR-000036/38 contradict
it under a different definition. Display both if the scanner cites the literature.

## 3. Dump timing after graduation

| Signal | Rule | Label | Evidence | Records |
|---|---|---|---|---|
| Thin pool 1 h after graduation | PumpSwap pool holds a small share of supply at T = pool creation + 1 h (liq/MC = 2 × pool share) | **replicated association**, low power | Rugs (≥90% fall from T by day 7) vs others: liq/MC AUC 0.047 (n=6 rugs, 2026-11-11) and 0.034 (n=26 vs 64, holdout). Mostly mechanical: it shows **when** the dump comes, not a tradable edge. | KR-000037 |
| Dev exits within 1 h | deployer balance ≤ 1% of its max within t0 + 3,600 s | **fact**, low information | Happens on ~89–91% of launches (Pump.fun and Pons), so it does not separate rugs from survivors on its own. | KR-000012, KR-000023 |

## 4. Trade-execution danger (MEV, costs)

| Signal | Rule | Label | Evidence | Records |
|---|---|---|---|---|
| High slippage setting | user slippage > 10% | **hypothesis** (vendor data) | Sandwiches per 10,000 Jupiter swaps into Pump.fun coins: 8 at 1–3%, 87 at 10–20%, 148 at 20–50%. | KR-000018 |
| Cost floor for any strategy | round trip on the curve | **fact** (protocol math) | +2.55% fee-only breakeven; 4.6% at 0.1 SOL with an assumed 0.001 SOL per tx. | KR-000019 |

## 5. Literature-only rug precursors (not yet measured by RKD)

Market activity and bundle statistics in the first minutes rank highest in published models (best AUPRC 0.58; F1
~0.78 with forward validation). Label **hypothesis**; do not turn into a score until RKD replicates it (KR-000023).

## Planned updates

- Study 5 holdout (pools 2026-11-05..11-14): confirms or revises the 20.3% freeze-use rate.
- Study 4 (dev funding of block-0 buyers): fills the third row of section 2.
