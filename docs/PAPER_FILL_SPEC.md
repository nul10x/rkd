# Paper fill spec v2 (Researcher to Builder, 2026-11-23)

Adds measured inputs to `docs/PAPER_TRADING_PLAN.md` (Validator, KR-000042). Evidence: KR-000058 (Study 6),
KR-000059 (costs). v2 fixes Validator findings S1-S5 (KR-000061).

**Who owns what (S5).** `docs/PAPER_ENGINE_ARCHITECTURE.md` v3 (branch `docs/paper-engine-architecture` @ 8578f0f)
owns **fill order**: arrival, coverage, same-slot handling, exits, own impact and statuses (sections 3.2-3.5).
This spec owns **fees, cost and delay scenarios, and parsing**. If they appear to conflict on fill order, the guide wins.

Every result stays **PAPER**. No wallets, keys, signing or real orders. A fill model is not a strategy, and
nothing here is a buy signal.

## 1. Rules that change the plan

| # | Rule | Why (measured or sourced) |
|---|---|---|
| 1 | Price curve fills from the **reserves in the latest on-chain TradeEvent**. Never derive them from curve progress or `30 SOL + real SOL`. | Next small trade within 2% of the event price: 100% (n=5,377 and 7,056). Constant-curve price: 31.9% and 34.4%. |
| 2 | Replay the real path to the arrival slot under guide 3.2. Do **not** add a flat delay cost. | Median drift after a 5-slot delay is about 0, but the 90th percentile is +15.4% and +26.1% (non-graduates). |
| 3 | Run delay as scenarios: **1, 5, 25 slots**. Report each. | Delay cost depends on the slot gap and is fat-tailed. Real trader latency is not measured. |
| 4 | A swap whose output is below its min-out **reverts**: it pays the network fee and changes no position. Evaluate this at each same-slot insertion point (guide 3.2), keeping the lowest post-slot wealth. A revert must never be used to avoid a rug. | Failures then come from the replayed path. "Price or profit not met" was 47.99% of failed Solana txs (arXiv:2504.18055). |
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
version in `strategy_run`. This table comes from the docs page and has **not been checked against on-chain fee tiers**
(open in T-000012), so keep it a versioned scenario until it has been.

## 3. Fill order and cost inputs

Fill order is **defined only in guide v3**, and is not restated here:

- **S1, same slot (3.2):** try the order at all n + 1 insertion points, apply the rest of the slot, and keep the
  lowest wealth after the slot.
- **S2, exits (3.2, 3.5):** an exit with no state or no coverage is `unresolved`, with worst case value 0 as the
  headline. It is never `refused`.
- **S3, coverage (3.2):** silence means "no change" only inside per-token coverage proven by exhausted pagination.
  Anything else is a gap. An entry in a gap is `refused` with reason `feed_gap`.
- **S4, own impact (3.4):** carry cumulative impact across all entry and exit legs and all concurrent positions in
  the token. The 2% cap applies to the cumulative position.

This spec supplies these inputs to that loop:

1. **Delay:** `delay` in {1, 5, 25} slots, one run each. Arrival follows the guide's formula.
2. **Fee:** venue, route and market cap at the fill, from section 2.
3. **Slippage tolerance:** default min-out = computed impact + 1 percentage point.
4. **Non-price failure:** `p_fail` scenarios **0 / 6.22 / 30 / 58.43%**, drawn with the guide's seeded hash. A failure
   pays the network fee. At most one retry, with a fresh delay. A failed exit leaves the position open.
5. **Sandwich:** section 4.

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

These add to guide section 3.7.

1. A fixture where constant-curve and event prices differ fills at the event price.
2. Same-slot signal never fills on the signal's own trade. Truncating later events leaves earlier fills unchanged.
3. **Same-slot rug:** buy 1 SOL into a 100/100 pool, fees 0, in the slot of a 99% liquidity removal. The result is the
   buy-first wealth of 0.505 SOL, not a revert that costs only the network fee.
4. Output below min-out returns `failed` and charges only the network fee.
5. Unknown reserves or a coverage gap: an entry returns `refused`, an exit returns `unresolved` at worst case value 0.
6. **Own impact:** 50 units into a 100/100 pool in 50 slices returns 33.333 in total, the same as one order
   (49.505 would mean the carry is missing). A split exit also gains nothing.
7. `pump_app` round trip on the curve at zero impact needs a 3.489% rise to break even; `direct` needs 2.548%.
8. Fee tier boundaries select the right row (419.99, 420, 98,240 SOL).
9. A freeze by the token's authority after entry returns `blocked` at value 0.
10. The same run twice gives an identical canonical dump.

## 7. Not measured yet

- PumpSwap buy prediction gap: 22.5% of buys are unexplained (KR-000057), so PumpSwap buy fills are unproven.
- Failure rate for a careful trader. The cached pages hold successful txs only.
- Real signal-to-landing latency of our own setup, and sandwich loss size.
- Why virtual reserves jump between trades on about 40% of traded mints. The engine does not need the cause,
  since it reads reserves from events, but a strategy should not treat those jumps as ordinary price moves.
- Delay drift on PumpSwap after graduation. Study 6 covers the curve's first 100 transactions only.
