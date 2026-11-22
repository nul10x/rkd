# Paper fill spec v1 (Researcher to Builder, 2026-11-23)

Adds measured inputs to `docs/PAPER_TRADING_PLAN.md` (Validator, KR-000042). Where the two differ, this file
wins for fills and costs. Evidence: KR-000058 (Study 6), KR-000059 (costs).

Every result stays **PAPER**. No wallets, keys, signing or real orders. A fill model is not a strategy, and
nothing here is a buy signal.

## 1. Rules that change the plan

| # | Rule | Why (measured or sourced) |
|---|---|---|
| 1 | Price curve fills from the **reserves in the latest on-chain TradeEvent**. Never derive them from curve progress or `30 SOL + real SOL`. | Next small trade within 2% of the event price: 100% (n=5,377 and 7,056). Constant-curve price: 31.9% and 34.4%. |
| 2 | Replay the real path to the fill slot. Do **not** add a flat delay cost. | Median drift after a 5-slot delay is about 0, but the 90th percentile is +15.4% and +26.1% (non-graduates). |
| 3 | Run delay as scenarios: **1, 5, 25 slots**. Report each. | Delay cost depends on the slot gap and is fat-tailed. Real trader latency is not measured. |
| 4 | Fill price beyond the order's slippage limit = **failed fill**: pay the network fee, get no position. | Failures then come from the replayed path. "Price or profit not met" was 47.99% of failed Solana txs (arXiv:2504.18055). |
| 5 | Add a `route` field: `direct` or `pump_app`. `pump_app` adds the Platform Fee of 0.45% per side (0.40% with a referral code). | pump.fun/docs/fees, updated 2026-11-16, in force from 2026-10-17. Fee-only breakeven: 2.548% direct, 3.489% through the app. |
| 6 | Use the full dated fee table in section 2, selected by market cap at fill time. | The plan had only the end points. |

## 2. Fee table `fees-2026-11-16`

Curve: 1.25% per side. Non-canonical PumpSwap pools: 0.30%. Custom Pair coins: curve 1.25%, canonical pool 0.30%.

Canonical PumpSwap, SOL-paired (total fee by market cap in SOL):

| From SOL | Total | From SOL | Total | From SOL | Total |
|---|---|---|---|---|---|
| 0 | 1.250% | 24,560 | 0.800% | 68,770 | 0.450% |
| 420 | 1.200% | 29,470 | 0.750% | 73,681 | 0.425% |
| 1,470 | 1.150% | 34,380 | 0.700% | 78,590 | 0.400% |
| 2,460 | 1.100% | 39,300 | 0.650% | 83,500 | 0.375% |
| 3,440 | 1.050% | 44,210 | 0.600% | 88,400 | 0.350% |
| 4,420 | 1.000% | 49,120 | 0.550% | 93,330 | 0.325% |
| 9,820 | 0.950% | 54,030 | 0.525% | 98,240 | 0.300% |
| 14,740 | 0.900% | 58,940 | 0.500% | | |
| 19,650 | 0.850% | 63,860 | 0.475% | | |

USDC-paired coins use a different table on the same page. Refuse them in v1 unless that table is added.
Market cap = current price x 1 billion tokens. Re-check the page before each experiment and store the table
version in `strategy_run`.

## 3. Fill algorithm

1. A signal at slot `s` creates an order with delay `d` from the scenario.
2. Read the last reserve state with slot <= `s + d`. No state, or a gap in the data: status `refused`, counted.
3. Compute the fill with constant product on those reserves and the fee for the venue, route and market cap.
4. Check the slippage limit (rule 4). Default limit = computed impact + 1 percentage point.
5. Apply `p_fail` for failures that are not price-based: scenarios **0 / 6.22 / 30 / 58.43%**. Failure pays the
   network fee. At most one retry, with a fresh delay.
6. Apply the sandwich scenario (section 4).
7. Write `paper_fill` with spot, fill price, impact, each cost, status and reason.

- **Size cap:** at most 2% price impact (Validator plan). The replay does not move later prices for our trade,
  so larger sizes would be overstated.
- **Exits:** a sell uses the same steps. If the token was frozen, or a Token-2022 setting blocks transfers, the
  status is `exit_blocked`, the position is held at 0 and the loss is reported separately.
- **Pool drained:** fill from the real reserves. Never use the last candle price.
- **Migration:** a curve order at or after a Migrate is refused until a PumpSwap pool state exists.

## 4. Sandwich scenario

Probability per swap from KR-000018 (Bitquery, per 10,000 Jupiter swaps on Pump.fun coins): <0.5% slippage 27,
0.5-1% 17, 1-3% 8, 3-10% 44, 10-20% 87, 20-50% 148, >=50% 33. Vendor data, not reproduced by RKD.

Loss per sandwich is **not measured**. Use a pessimistic loss equal to the unused slippage room
(`limit - impact`), and report results with and without it.

## 5. Parsing notes

- TradeEvent: inner instruction of the Pump program, prefix `e445a52e51cb9a1d` + `bddb7fd34ee661ee`. After the
  prefix: mint at 0, quote and token amounts at 32, is_buy at 48, timestamp at 81, virtual quote, virtual token,
  real quote and real token (u64) at 89. Event length varies (398 to 413 bytes seen), so read by offset and do not
  assert a length. Reference parser: `research/study6_delay.py`.
- PumpSwap: effective quote reserves = quote vault + `virtual_quote_reserves`, which is **signed** (Pump docs).
- A completing v3 buy emits TradeEvent, CompleteEvent, then PostCompleteBuyEvent. The buyer's total is the first
  plus the third (secondary source, check against the Pump IDL).

## 6. Acceptance tests

1. A fixture where constant-curve and event prices differ fills at the event price.
2. Same-slot signal never fills on the signal's own trade. Truncating later events leaves earlier fills unchanged.
3. Fill beyond the limit returns `failed` and charges only the network fee.
4. Unknown reserves return `refused`, never a price.
5. `pump_app` round trip on the curve at zero impact needs a 3.489% rise to break even; `direct` needs 2.548%.
6. Fee tier boundaries select the right row (419.99, 420, 98,240 SOL).
7. Frozen-token exit returns `exit_blocked`.
8. The same run twice gives byte-identical `paper_fill` rows.

## 7. Not measured yet

- Failure rate for a careful trader. The cached pages hold successful txs only.
- Real signal-to-landing latency of our own setup, and sandwich loss size.
- Why virtual reserves jump between trades on about 40% of traded mints. The engine does not need the cause,
  since it reads reserves from events, but a strategy should not treat those jumps as ordinary price moves.
- Delay drift on PumpSwap after graduation. Study 6 covers the curve's first 100 transactions only.
