# RKD memecoin knowledge index

Generated from the Logbook by `python3 -m research.kb_index`. Do not edit by hand. Read a record with
`python3 -m ecosystem.cli get KR-xxxxxx`; search with `python3 -m ecosystem.cli search "<words>"`.
Status ladder: unverified < hypothesis < under_investigation < historically_supported < validated (or rejected).

Records: 48

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
| KR-000037 | hypothesis | historically_supported | 0.55 | 2026-11-21 | H3c: Pump.fun graduates whose PumpSwap pool still holds a small share of supply 1 h after graduation (low liq/MC, low vol/MC) are more likely to fall >=90% from that point by day 7 |

## 5. Contract security and scam detection

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000022 | finding | unverified | 0.60 | 2026-11-21 | Token security checks for memecoins: Solana mint/freeze authority and Token-2022 extensions that enable scams |
| KR-000023 | finding | unverified | 0.50 | 2026-11-21 | Rug-pull precursors and insider-wallet indicators: what the evidence supports at launch time |
| KR-000037 | hypothesis | historically_supported | 0.55 | 2026-11-21 | H3c: Pump.fun graduates whose PumpSwap pool still holds a small share of supply 1 h after graduation (low liq/MC, low vol/MC) are more likely to fall >=90% from that point by day 7 |
| KR-000045 | finding | unverified | 0.55 | 2026-11-22 | EVM honeypot tokens: measured prevalence ranges 10.7%-87.9% depending on definition and detector; sell-reversion is 72% of trap mechanisms; simulation beats static checks |
| KR-000046 | finding | unverified | 0.50 | 2026-11-22 | Solana honeypots: freeze-authority abuse measured in 0.46% of new non-launchpad tokens (461/100,063, 2025-H1); mechanism is readable from mint state, so low base rate dominates detector value |
| KR-000047 | report | n/a | - | 2026-11-22 | Plan, study 5: how often new Solana tokens can block sells (freeze authority, Token-2022 extensions) and how often a retained freeze authority is used within 7 days (2026-11-11 + holdout 2026-11-09) |
| KR-000048 | observation | unverified | 0.80 | 2026-11-22 | Study 5 pilot: CPMM pool-creation fee account gives a daily pool census; LP and stablecoin mints must be excluded; one new token froze 4 buyer accounts within 25 min |

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
| KR-000045 | finding | unverified | 0.55 | 2026-11-22 | EVM honeypot tokens: measured prevalence ranges 10.7%-87.9% depending on definition and detector; sell-reversion is 72% of trap mechanisms; simulation beats static checks |
| KR-000046 | finding | unverified | 0.50 | 2026-11-22 | Solana honeypots: freeze-authority abuse measured in 0.46% of new non-launchpad tokens (461/100,063, 2025-H1); mechanism is readable from mint state, so low base rate dominates detector value |

## 10. MEV, sandwiches, snipers, tx mechanics

| id | kind | status | conf | date | title |
|---|---|---|---|---|---|
| KR-000018 | finding | unverified | 0.60 | 2026-11-21 | MEV on Solana: sandwich attacks on memecoin swaps, where they happen and what reduces exposure |

## Standing projects (keyword match on tags)

- **Traits of successful memecoins**: KR-000021
- **What precedes big moves**: KR-000021
- **Organic vs artificial volume**: KR-000020
- **Narrative identification**: KR-000025
- **Insider wallet behaviour**: KR-000023, KR-000039
- **Liquidity changes vs price**: KR-000015, KR-000016, KR-000017, KR-000037
- **Rug-pull precursors**: KR-000010, KR-000012, KR-000015, KR-000016, KR-000023, KR-000037, KR-000046
- **Strategies vs fees and slippage**: KR-000019, KR-000027, KR-000028, KR-000042

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
| KR-000026 | lesson | n/a | - | 2026-11-21 | Platform architecture for six memecoin projects: live-snapshot fetch path, shared facts DB, facts vs heuristics, event-driven paper/backtest parity |
| KR-000027 | decision | n/a | - | 2026-11-21 | Team rule: optimise for reliable evidence, risk identification and net-of-cost edge tests, never for finding coins that go up |
| KR-000028 | tool | n/a | - | 2026-11-21 | research/trade_costs.py: Pump.fun round-trip breakeven and buy price impact calculator |
| KR-000029 | tool | n/a | - | 2026-11-21 | research/curve_ratios.py: liquidity/MC of a Pump.fun token along the curve and at migration |
| KR-000030 | tool | n/a | - | 2026-11-21 | research/kb_index.py: generates docs/knowledge/INDEX.md from the Logbook by research division |
| KR-000031 | tool | n/a | - | 2026-11-21 | Study 3 pipeline: collectors/study3.py, research/study3_parse.py, research/study3_analyze.py |
| KR-000032 | tool | n/a | - | 2026-11-21 | collectors/client.py: opt-in Logbook counting of API requests (api_usage) and task budgets |
| KR-000033 | tool | n/a | - | 2026-11-21 | Tool collectors/client.py 2.0: atomic usage/cache files, per-provider rate-limit pauses, cross-process per-provider throttle |
| KR-000034 | tool | n/a | - | 2026-11-21 | Tool ecosystem 1.1: Termux/Android review fixes (stuck tasks, silent bad links, empty updates, UTC caps, WAL fallback, FTS5 message, id rollover) |
| KR-000035 | lesson | n/a | - | 2026-11-21 | Offline re-runs from a linked worktree overwrite shared exports; guard by backing up and restoring data/exports (new Builder skills) |
| KR-000036 | report | under_investigation | 0.55 | 2026-11-21 | Study 3 (launches 2026-11-11): block-0 buyer clusters are far more common among Pump.fun graduates; post-graduation ratios at T+1h do not separate later 2x runs (low power) |
| KR-000038 | report | historically_supported | 0.60 | 2026-11-21 | Study 3 holdout (launches 2026-11-09): block-0 buyer clusters among Pump.fun graduates replicate (89% vs 18%); 60% of graduates graduated in their creation slot; post-graduation ratios still not a runner screen |
| KR-000039 | report | n/a | - | 2026-11-22 | Plan, study 4: were Pump.fun block-0 buyers funded by the deployer? Funding-graph test, graduates vs non-graduates (2026-11-11 + holdout 2026-11-09) |
| KR-000040 | observation | unverified | 0.80 | 2026-11-22 | Study 4 pilot: system-transfer parsing misses program and wrapped-SOL funding; 33 of 45 block-0 buyer pages are full 100-tx pages |
| KR-000041 | tool | n/a | - | 2026-11-22 | Tool token_scanner 0.1.1 + Discord bot /scan: market, holders excl. venues (unknown without listed pairs), mint permission facts, Pump.fun block-0 context |
| KR-000042 | report | n/a | - | 2026-11-22 | Validator audit: paper trading readiness for RKD (no strategy ready; engine benchmark first; master lacks the research code) |
| KR-000043 | experiment | n/a | - | 2026-11-22 | Tool QA: token_scanner 0.1.0 offline (97 tests pass; bug B1: pool counted as top holder when DEX Screener lists no pair) |
| KR-000044 | experiment | n/a | - | 2026-11-22 | Tool QA retest: token_scanner 0.1.1 (15cc08c) fixes B1, N1, N2 from KR-000043 |
