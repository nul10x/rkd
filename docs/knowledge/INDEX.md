# RKD memecoin knowledge index

Generated from the Logbook by `python3 -m research.kb_index`. Do not edit by hand. Read a record with
`python3 -m ecosystem.cli get KR-xxxxxx`; search with `python3 -m ecosystem.cli search "<words>"`.
Status ladder: unverified < hypothesis < under_investigation < historically_supported < validated (or rejected).

Records: 25

## 1. Blockchain and on-chain analytics

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000020 | finding | unverified | 0.50 | 2026-11-21 | Organic vs artificial memecoin volume: wash volume rarely attracts real traders; new-wallet formation is the better signal |
| KR-000021 | finding | unverified | 0.35 | 2026-11-21 | What precedes big memecoin moves and what successful launches share: fast real accumulation, then sudden wallet inflows; most shared traits are not predictive |
| KR-000023 | finding | unverified | 0.50 | 2026-11-21 | Rug-pull precursors and insider-wallet indicators: what the evidence supports at launch time |

## 2. Technical analysis and market structure

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000019 | finding | unverified | 0.70 | 2026-11-21 | Costs that a memecoin strategy must beat: Pump.fun fees, fixed per-tx costs, buy price impact, and evidence on strategies after costs |

## 3. Social intelligence and narratives

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000025 | finding | unverified | 0.35 | 2026-11-21 | Social signals, narratives and trader psychology in memecoins: what is supported and what is not |

## 4. Tokenomics and liquidity

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000019 | finding | unverified | 0.70 | 2026-11-21 | Costs that a memecoin strategy must beat: Pump.fun fees, fixed per-tx costs, buy price impact, and evidence on strategies after costs |

## 5. Contract security and scam detection

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000022 | finding | unverified | 0.60 | 2026-11-21 | Token security checks for memecoins: Solana mint/freeze authority and Token-2022 extensions that enable scams |
| KR-000023 | finding | unverified | 0.50 | 2026-11-21 | Rug-pull precursors and insider-wallet indicators: what the evidence supports at launch time |

## 6. Trading psychology

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000025 | finding | unverified | 0.35 | 2026-11-21 | Social signals, narratives and trader psychology in memecoins: what is supported and what is not |

## 7. Market cycles and history

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000024 | finding | unverified | 0.55 | 2026-11-21 | Memecoin market cycles 2021-2026: sector peaks, the 2025 collapse, and the launchpad boom-bust |

## 8. Strategies and statistics

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000019 | finding | unverified | 0.70 | 2026-11-21 | Costs that a memecoin strategy must beat: Pump.fun fees, fixed per-tx costs, buy price impact, and evidence on strategies after costs |
| KR-000020 | finding | unverified | 0.50 | 2026-11-21 | Organic vs artificial memecoin volume: wash volume rarely attracts real traders; new-wallet formation is the better signal |

## 9. DEXs, launchpads and launches

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000021 | finding | unverified | 0.35 | 2026-11-21 | What precedes big memecoin moves and what successful launches share: fast real accumulation, then sudden wallet inflows; most shared traits are not predictive |

## 10. MEV, sandwiches, snipers, tx mechanics

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000018 | finding | unverified | 0.60 | 2026-11-21 | MEV on Solana: sandwich attacks on memecoin swaps, where they happen and what reduces exposure |

## Standing projects (keyword match on tags)

- **Traits of successful memecoins**: KR-000021
- **What precedes big moves**: KR-000021
- **Organic vs artificial volume**: KR-000020
- **Narrative identification**: KR-000025
- **Insider wallet behaviour**: KR-000023
- **Liquidity changes vs price**: KR-000015, KR-000016, KR-000017
- **Rug-pull precursors**: KR-000010, KR-000012, KR-000015, KR-000016, KR-000023
- **Strategies vs fees and slippage**: KR-000019

## Studies, plans and lessons not tagged with a division

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000001 | report | n/a | - | 2026-11-21 | Study plan: deployer-wallet hold time after liquidity add vs 7-day survival (Solana / Pump.fun) |
| KR-000002 | observation | historically_supported | 0.85 | 2026-11-21 | Pilot: Pump.fun mint authority TSLvdd1p...okM appears only in create txs and samples launches by time |
| KR-000003 | observation | historically_supported | 0.85 | 2026-11-21 | Pilot: Helius getTransactionsForAddress works on the free plan (signatures and full, blockTime filters) |
| KR-000004 | observation | historically_supported | 0.85 | 2026-11-21 | Pilot: DexScreener lists fresh Pump.fun bonding-curve tokens but drops inactive ones; liquidity.usd is null on bonding-curve pairs |
| KR-000005 | report | under_investigation | 0.50 | 2026-11-21 | Study 1 (day 2026-11-11): Pump.fun deployers exit within seconds whether or not the token survives 7 days; H1 not supported |
| KR-000006 | hypothesis | under_investigation | 0.10 | 2026-11-21 | Pump.fun tokens that survive 7 days had larger deployer dev buys at creation |
| KR-000007 | lesson | n/a | - | 2026-11-21 | Bot architecture lessons from NautilusTrader, Hummingbot, Freqtrade and open-source pump.fun bots |
| KR-000008 | observation | historically_supported | 0.80 | 2026-11-21 | Holdout 2026-11-09: 1 of 25 random DexScreener-unlisted Pump.fun mints was still active on day 7 |
| KR-000009 | report | under_investigation | 0.40 | 2026-11-21 | Study 1 holdout (day 2026-11-09): dev-buy-size effect (KR-000006) does not replicate; H1 hold-time result is inconsistent across days |
| KR-000010 | report | n/a | - | 2026-11-21 | Plan, study 2: cross-chain launch outcomes, Pump.fun (Solana) vs Pons (Robinhood Chain), launches 2026-11-11 |
| KR-000011 | lesson | n/a | - | 2026-11-21 | Scraping/collection architecture: one shared fetch layer, raw-first storage, per-error-class handling |
| KR-000012 | report | under_investigation | 0.50 | 2026-11-21 | Study 2 (launches 2026-11-11): Solana launchpads vs Pons on Robinhood Chain: graduation, survival, dev exits, MC/liquidity/volume, plus a sourced review |
| KR-000013 | lesson | historically_supported | 0.90 | 2026-11-21 | Budget lesson: error-driven range splitting on eth_getLogs burned ~470 of 500 calls; GeckoTerminal 429s at ~1 call/4 s |
| KR-000014 | lesson | n/a | - | 2026-11-21 | Wallet alert tracker architecture: poll-first with per-wallet cursors, push feeds only as accelerators |
| KR-000015 | report | unverified | 0.50 | 2026-11-21 | Review: memecoin trading-strategy evidence, MC/liquidity/volume ratios, rug-pull charts and launch bundles |
| KR-000016 | report | n/a | - | 2026-11-21 | Plan, study 3: block-0 bundles vs graduation and dev exit; post-graduation liq/MC, vol/MC, traders-per-SOL vs later runs and rugs (Pump.fun, 2026-11-11 + holdout 2026-11-09) |
| KR-000017 | observation | unverified | 0.80 | 2026-11-21 | Study 3 pilot: block-0 parsing needs a net-receiver rule (same-slot graduation exists); liq/MC in a PumpSwap pool = 2 x pool share of supply |
