# Paper trading environment: audit and launch plan (v1, 2026-11-22)

Author: Validator. Status: **plan only, nothing built.** Every trade this environment ever produces is
**PAPER** (simulated). No wallets, keys, signing or real orders exist or are planned. A paper result is
never called profit; a strategy is never called profitable unless a pre-registered out-of-sample test
passes net of costs (KR-000027, cost model KR-000018/KR-000019).

Audit inputs: README, docs/ARCHITECTURE.md, docs/PROJECT_STATUS.md, docs/knowledge/INDEX.md, all 40
Logbook records (KR-000001..040), code on every branch, the cache in `data/raw` (read only), the
Builder's `build/token-scanner` worktree (read only), and 8 free keyless live calls (§3).

## 0. Verdict

- **No strategy in the Logbook is ready for an honest paper test today.** Every candidate is either a
  null/unreplicated result, a risk description its own record says is "not a tradable edge", or a
  literature claim with no RKD rules. Details in §6.
- **The engine can still be built and validated now**, on a benchmark that makes no edge claim: random
  entry with real costs on a launch-time sample. That run calibrates the cost/slippage model and gives
  every later strategy the benchmark the edge gate requires.
- **Main blockers:** (1) master holds only the Logbook foundation; every collector and research tool is on
  unmerged branches; (2) no historical trade-level price/reserve series after T+1h exists in the cache
  (hourly vendor candles only, median 8 candles per graduate); (3) no Helius key in this agent's
  environment, so chain history must come from the Researcher's cache or a key the user grants;
  (4) failed-fill rate for a careful trader is unmeasured.

## 1. What already works (reusable)

| Piece | Where (branch @ commit) | What a paper engine reuses | Limits |
|---|---|---|---|
| Logbook (records, versions, links, tasks, budgets, rkd/1) | master @ fb56f8d | experiment records, append-only history, task budgets | no `experiment` template yet |
| `collectors/client.py` 2.0 (cached(), throttle, pauses, budget, usage files) | research/study4-funding, build/token-scanner | all history reads; offline re-runs byte-identical | not on master |
| `client.live()` + `helius_live`, `dexscreener_token_pairs_live` | build/token-scanner @ 557204c | forward (live) paper mode: timestamped append-only snapshots, `max_age_s` reuse | returns `{response, fetched_at, raw_path, reused}`; not merged |
| `research/trade_costs.py` | research/study4-funding (from 00139af) | curve buy/sell math (constant product on virtual reserves 30 SOL / 1.073e9), 1.25 % fee per side, breakeven | flat curve fee; per-tx cost is an assumption; no PumpSwap pool math; app Platform Fee not modelled |
| `research/curve_ratios.py` | same | curve state ↔ progress, migration pool state (~85 SOL / 206.9M tok, unverified) | constants not re-verified on-chain |
| `research/pump.py` | same | jsonParsed Pump.fun tx parsers (create, buys/sells, DEX program list) | Pump.fun only |
| `research/study3_parse.py` (`block0`, `pool_state`) | same | PumpSwap reserves at a time from pool txs; block-0 buyers | needs pool tx pages |
| `research/stats.py` | same | Wilson, bootstrap, Mann-Whitney, KM, log-rank | stdlib |
| Launch-time sampling (stage1, study 3 cohorts, seeds) | same | survivorship-free universe: 3,858 launches 2026-11-11, 6,593 launches 2026-11-09 | two days, one regime |
| `tools/token_scanner` 0.1.0 | build/token-scanner @ a14c288 | mint permission facts (freeze/mint authority, Token-2022 blockers) as entry exclusions | not merged |
| Platform design KR-000026 / PLATFORM_ARCHITECTURE.md §0.2, §5 | docs/platform-architecture @ 6412553 | `market.db` tables `strategy_run`, `paper_fill`, `trade`, `snapshot`; event-driven design | design only, nothing built |

### Cached data (offline inventory, `data/raw`, 2026-11-22)

| Source | Files | Contains | Use for paper engine |
|---|---|---|---|
| Helius `getTransactionsForAddress` full, address = mint | 650 | first pages of mint history (sample of 400: 179 full 100-tx pages, median span **96 s**) | block-0 / first-minutes curve trades only; not a price series |
| Helius full, other addresses | 2,992 | deployer ATAs, PumpSwap pools (1,836 files mention the PumpSwap program), study-4 wallets | pool reserves at T via `pool_state` |
| Helius signatures | ~350 | signature lists | timing only |
| Migration events | 370 files contain `Instruction: Migrate` | graduation time and migration tx | yes |
| GeckoTerminal `ohlcv_hour` | 146 | hourly candles from T for 52 + 94 study-3 graduates; median 8 candles, 141/146 have missing hours (hours with no trades are omitted) | coarse exit path only; vendor USD prices |
| GeckoTerminal daily `ohlcv` | 72 | daily candles (study 2 peaks) | no |
| GeckoTerminal `pools` | 177 | pool list per token (reserve_in_usd, no token amounts) | pool discovery |
| DexScreener | 299 + live snapshots | listings, pumpswap pair liquidity | KR-000004: not a universe |
| Robinhood RPC, traces | 515 / 122 | study 2 | out of scope for v1 |
| Failed transactions | **1 file** | all mint pages were fetched with `status: succeeded` | **no historical failed-fill data** |

## 2. Data needs vs sources

| Need | Historical (backtest) | Forward (live paper) | Status |
|---|---|---|---|
| Timestamped prices, trade level | Helius mint/pool history (key needed; pages cover ~96 s each, so a full day of a busy token is many calls) | GeckoTerminal `/pools/{pool}/trades`: last 300 trades only (live probe: 300 trades spanned 93 s on the top pool) | **gap** for history beyond first minutes |
| Prices, candle level | GeckoTerminal hourly (cached), minute candles **available historically** (probe: 75 one-minute candles from a 13-day-old pool, gaps where no trades) | same | usable for coarse tests; next-candle fills only |
| Curve depth (slippage on curve) | derived exactly from curve progress (virtual reserves), progress from the latest trade's post-balances | same, or `getAccountInfo` on the curve account | **works** (math in trade_costs.py) |
| Pool depth (PumpSwap) | reserves from pool txs (`pool_state`), only where pool pages are cached (at T) | DexScreener `liquidity.base/quote` (probe: present on a pumpswap pair, e.g. 836,266,551 tok / 6.87 SOL) | history after T is a **gap**; live works |
| Migration events | cached Migrate txs; curve `complete` byte via getMultipleAccounts (KR-000013) | same | **works** |
| Failed transactions | not cached | public RPC `getSignaturesForAddress` includes `err` (probe below) | parameter only; see §4.4 |
| Fees | dated table from KR-000019 | same | curve fee works; PumpSwap tiers listed in KR-000019, not yet a table in code |
| Universe (survivorship-free) | stage-1 launch-time samples, two days | live: new creates on the Pump.fun mint authority (KR-000002) | **works** for history; forward collector not built |

## 3. Live probe (8 free keyless calls, no rate limit, 2026-11-22 ~00:50 UTC)

Calls: public Solana RPC 4 (one returned an error and was counted), GeckoTerminal 3, DexScreener 1.
Raw snapshots and the usage file are in the Validator's own folder
(`probe_raw/`, not in the repo's `data/raw`). Script: Validator `scripts/live_probe.py`.

- Pump.fun program, last 1,000 signatures (4 s window): **693 failed** (69 %). PumpSwap program, last
  1,000 (2 s window): **512 failed** (51 %). Top error codes: Pump.fun Custom 9020, 7, 111, 7101;
  PumpSwap Custom 6040, 1003. Error-code meanings were **not verified** against program IDLs. The
  sample is program-wide and dominated by bots, so it is **not** a failure rate for a careful trader.
- One failed tx (failed inside another program, 7JwTi9…94ZG) still paid **5,908 lamports** in fees: a
  failed fill costs the network fee. One example, not a distribution.
- Public RPC `getTransaction` needs `maxSupportedTransactionVersion: 1` (same error is in
  `data/raw/usage.json`). Pass 1, not 0, in every getTransaction call.
- GeckoTerminal trades endpoint fields: block_timestamp, block_number, kind, from/to amounts, prices in
  token and USD, tx_from_address, tx_hash, is_anomalous. Good enough for forward paper fills.
- GeckoTerminal historical minute candles work for a 13-day-old pool.

## 4. Minimum engine design

Stdlib only, event-driven, one process per run, same strategy code for backtest and forward paper mode
(KR-000026 §5). Proposed location `tools/paper/` (Builder) and `research/paper_rules/` (Validator).

### 4.1 Modules

| Module | Job | Owner |
|---|---|---|
| `events.py` | Normalise sources into one time-ordered stream: `Trade`, `Candle`, `PoolState`, `CurveState`, `Migration`, `Missing`. Each event has `ts`, `source`, `raw_path`. Never interpolates; a gap emits `Missing`. | Builder |
| `venues.py` | Pure fill math: Pump.fun curve (virtual reserves), PumpSwap constant product `out = dx(1-f)y/(x+dx(1-f))`; dated fee table per venue; refuses to fill when reserves are unknown. | Builder (Validator writes the test vectors) |
| `costs.py` | Per-tx network + priority fee (parameter), sandwich tax as a function of slippage tolerance and venue (KR-000018 table, parameter), failed-fill model (§4.4). | Builder, parameters from Validator |
| `broker.py` | Paper broker: market orders fill at the **next** event after the signal, size capped by a liquidity limit (default ≤ 2 % price impact), partial exits, delayed fills (latency parameter in events), failed fills (fee charged, no position). Writes `paper_fill`. | Builder |
| `strategy.py` | Interface `on_event(state, event) -> [Order]`; strategies are versioned rule files, never edited in place. | Validator |
| `runner.py` | Backtest replay over a frozen event file, or forward mode over `client.live()` snapshots. Truncation test built in. | Builder |
| `metrics.py` | Fixed definitions (§4.5), gross vs net, by position size. | Validator |
| `benchmarks.py` | Random entry with the same holding-time distribution and costs; hold SOL. | Validator |
| `report.py` | Experiment record (§4.6) to the Logbook through rkd/1, every number labelled PAPER. | Validator |

### 4.2 Data model

Use the KR-000026 `market.db` tables, built minimal first:
- `strategy_run(run_id, strategy, strategy_version, rules_sha256, mode backtest|forward, universe_rule,
  data_window, split, cost_model_version, params_json, git_commit, started_at, metrics_json, label)`
- `paper_fill(run_id, seq, ts_signal, ts_fill, mint, venue, side, intended_qty, filled_qty, price_spot,
  price_fill, impact_pct, fee_sol, network_sol, sandwich_sol, status filled|partial|failed|refused,
  reason, reserves_json, event_raw_path)`
- `missing(run_id, mint, from_ts, to_ts, reason)`: tokens/periods excluded for missing data, counted in
  the report, never filled in.

### 4.3 Cost and slippage model (version cost-v1)

| Item | Value | Source |
|---|---|---|
| Curve fee | 1.25 % per side | KR-000019 (pump.fun docs 2026-11-21) |
| Curve slippage | exact from virtual reserves at fill time | trade_costs.py |
| PumpSwap fee | tier by market cap (1.20 % at $59k–300k … 0.33 % at $19–20M); non-canonical 0.30 % | KR-000019; table to re-check before each experiment |
| PumpSwap slippage | constant product on pool reserves at fill time; unknown reserves → refuse | KR-000026 |
| Network + priority | scenarios 0.0001 / 0.001 / 0.005 SOL per tx (assumption) | KR-000019 |
| Sandwich tax | scenario per slippage tolerance from the KR-000018 table; tolerance = computed impact + 1 pp | KR-000018 (vendor data) |
| Failed fill | probability p_fail scenarios 0 / 10 / 30 %, fee charged, re-try after a latency, at most one retry | §3 probe; not measured for careful traders |
| Graduation fee, app Platform Fee | 0.015 SOL (graduation, not paid by traders); Platform Fee **not modelled** (rate unknown) | KR-000019 |

Every result is reported under the base and the pessimistic scenario; a result that flips sign between
them is reported as cost-sensitive.

### 4.4 Bias controls (from rkd-edge-check)

Launch-time universe only; chronological split only (calibrate on 2026-11-09/11, test on a later,
pre-registered launch day); next-event fills; truncation test must leave earlier signals unchanged;
missing data excluded and counted; rules frozen and hashed before the test period is fetched.

### 4.5 Metrics (fixed definitions)

n trades, period, win rate with Wilson CI (never without n and period), average win, average loss,
profit factor, gross and net return, max drawdown, longest losing streak, total fees, total slippage,
sandwich and failed-fill cost, refused/missing count, all by position size (0.1 / 0.5 / 1 SOL) and vs the
random-entry benchmark.

### 4.6 Experiment record format (Logbook kind `experiment`)

Title starts with `PAPER`. Description sections: ID, strategy + version + rules hash, tool versions +
git commit, data (sources, raw paths, fetched_at), period and split, universe rule, conditions
(cost-v1 scenario, latency, p_fail, size), config, results (§4.5 table, gross and net, benchmark),
bugs found, edge-check checklist answers, conclusion with label (hypothesis / survives costs / null).
Links: `tests` → the strategy or hypothesis record; `derived_from` → data records. New record per run;
never overwrite.

## 5. Who builds what

**Builder** (tools/, shared code, tests): merge path for `collectors/client.py` + `live()` and the
research helpers to master (or a stated alternative); `events.py`, `venues.py`, `costs.py`, `broker.py`,
`runner.py`, minimal `market.db`; a forward collector for new Pump.fun creates + DexScreener/Gecko live
snapshots under the daily budget.

**Validator**: versioned rule files, test vectors for venue math (from trade_costs.py and hand
calculations), metrics and benchmarks, the cost-v1 parameter file with sources, truncation and
leakage tests, QA of every Builder module, experiment records.

**Researcher**: explicit, pre-registered rules for any strategy to be tested (entry, exit, size, universe,
holding limit, outcome), and a decision on which launch day is the test period.

## 6. Which strategy could be tested honestly

| Record | Result | Testable as a strategy now? |
|---|---|---|
| KR-000006 dev-buy size → 7-day survival | not replicated (p=0.41) | no: null; also survival ≠ return |
| KR-000005/009 deployer hold time | null / inconsistent | no |
| KR-000038 block-0 clusters ↔ graduation | replicated association (H3a) | no: entry would be in the creation slot, against the cluster itself; risk context only |
| KR-000037 H3c low pool share at T+1h → later ≥90 % fall | replicated, partly mechanical | not as an edge (record: "not a tradable edge"); spot memecoins cannot be shorted here. Candidate only as an **exit/avoid filter** for a long rule, which nobody has specified |
| KR-000038 traders/SOL vs runner_2x | holdout-only, exploratory | no: not replicated |
| KR-000015/021 literature (curve accumulation speed, non-bot share) | relayed, no fees, small n | no RKD rules or data (needs full curve trade history) |

**First test that can be done honestly (engine validation, not a strategy):**
`PAPER-BENCH-001 v1`: random entry into study-3 graduates at T = pool creation + 1 h (52 + 94 graduates
with pool reserves at T and hourly candles), fixed holding times (1 h, 6 h, 24 h, day 7), exits at the
next available candle, cost-v1 base and pessimistic, sizes 0.1/0.5/1 SOL. Purpose: check engine and cost
plumbing, measure how much the costs take, and produce the benchmark every later strategy must beat. It
claims nothing about an edge; graduates are one sub-universe; hourly vendor candles make the exit price
coarse (logged as a limitation).

**First real strategy candidate (needs the Researcher):** an H3c-based long-with-filter rule, e.g. "at
T+1h, only enter graduates whose pool already holds ≥ X % of supply", pre-registered with X frozen,
tested on a new launch day not yet collected, against PAPER-BENCH. Until the Researcher writes those
rules, it does not exist.

## 7. Launch steps

1. Builder: shared code on master (or agreed branch) → engine modules with offline tests on cached
   fixtures.
2. Validator: cost-v1 file, venue test vectors, metrics/benchmarks, QA report per module.
3. Validator: PAPER-BENCH-001 on cached 2026-11-09/11 graduates, truncation test, experiment record.
4. Researcher: pre-registered rule file for the first strategy + test day.
5. Collect the test day (forward collector or Helius with a key the user grants), run once, file result.

## 8. Requests to send (not sent yet)

- **Builder**: (a) merge or rebase plan so master has client.py 2.0 + live() + research helpers;
  (b) build events/venues/costs/broker/runner per §4 with acceptance tests (next-event fill, refuse on
  unknown reserves, partial exit, failed fill charges fee, truncation test); (c) forward collector spec
  with a daily call budget; (d) note: getTransaction needs `maxSupportedTransactionVersion: 1`.
- **Researcher**: (a) is there any rule you would pre-register for a long-only H3c filter (entry time,
  threshold, exit, holding limit)? (b) which launch day is the out-of-sample test period? (c) can study
  pipelines record failed txs (drop `status: succeeded`) on the next collection, so failed-fill rates can
  be measured? (d) confirm PumpSwap fee tiers and the Platform Fee rate.
- **User**: whether a Helius key may be made available to the Validator for history pulls (free plan),
  and approval for any merge to master.
