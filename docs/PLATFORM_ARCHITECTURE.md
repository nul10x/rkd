# Memecoin intelligence platform: architecture for the six projects (v1, 2026-11-21)

Design study only. Nothing here is built yet; the user asked to learn the architecture first.
Builds on, and does not repeat:
`docs/BOT_ARCHITECTURE.md` (Discord front door, one supervised bot, tools as one-shot subprocesses),
`docs/SCRAPING_ARCHITECTURE.md` (fetch layer, raw-first, caching classes, error classes),
`docs/WALLET_TRACKER_ARCHITECTURE.md` (poll-first wallet feed, cursors, inbox/outbox),
and Logbook KR-000015 (what the evidence says about memecoin strategies, ratios, rugs, bundles).

Constraints that shape every choice: macOS/Windows laptop first, launched from Discord, Termux
portable; Python 3.8+ stdlib; free read-only documented APIs; one-shot resumable runs; no trading,
no wallet keys; paper trading only; never call a token "safe" or a strategy "profitable" without
evidence. Sources and retrieval date at the end. Anything marked **(unverified)** was not confirmed
against a primary source in this study.

---

## 0. Platform shape

```
 Discord bot (front door) ──► task queue (ecosystem/tasks.py) ──► one tool run (subprocess)
                                                                      │
   sources ─► fetch layer (collectors/client.py) ─► raw snapshot ─► decoder ─► facts DB
                                                                      │
                              pure analyzers (scanner, security, smart money, social, lab)
                                                                      │
                         outputs: JSON/CSV exports, Discord embeds, static HTML dashboard
```

Rules carried over: raw response saved before parsing; analyzers are pure functions over the facts
DB (no network); every fact carries `source` and `fetched_at`; missing data is stored as missing
(`null` + reason), never as zero.

### 0.1 One new fetch-layer feature is needed first: live snapshots

`collectors/client.py` caches forever by method+params. That is right for immutable data (a past
transaction, a closed candle) and wrong for live data (price, liquidity, holders, authorities),
which would silently go stale. Add a second path, keeping the first unchanged:

- `client.live(provider, url, body, label)`: always fetches (paused/throttled/budgeted like now),
  then writes the raw response to `data/raw/<provider>/live/<YYYY-MM-DD>/<unix>_<sha>.json` with
  `request`, `fetched_at`, `response`. Never read back as a cache hit.
- Optional `max_age_s`: reuse the newest snapshot of the same request if younger than N seconds
  (protects free limits when Discord users repeat a command).
- Budgets for live tools: one usage file per tool per UTC day (`usage_<tool>_<day>.json`), because
  the current budget is lifetime-per-file, which suits studies but not daily tools.

### 0.2 Shared data model (one SQLite file `data/market.db`, separate from the Logbook)

| Table | Key | Main columns | Written by |
|---|---|---|---|
| `token` | chain, mint | symbol, name, decimals, program (spl/token-2022), first_seen | scanner |
| `pair` | chain, pair_address | mint, quote_mint, dex_id, labels, created_at (from source) | scanner |
| `snapshot` | id | chain, mint/pair, kind (market/holders/authority/security/social), source, fetched_at, raw_path, values JSON | every collector |
| `wallet` | chain, address | label, label_source, label_evidence, added_by | smart money |
| `trade` | chain, signature, index | wallet, mint, side, token_amount, quote_amount, price, slot, block_time, venue, source | smart money, lab |
| `flag` | id | subject (mint/wallet/pair), code, severity_class (fact/heuristic), evidence JSON, rule_version, fetched_at | security, social |
| `strategy_run` | run_id | strategy name+version, params, data window, universe rule, fees/slippage model, metrics JSON, git commit | lab |
| `paper_fill` | run_id, seq | intended vs simulated fill, slippage, fee | lab (paper mode) |

`snapshot` is append-only: history comes for free, and the dashboard only reads. Facts and
heuristics are kept apart (`severity_class`) so a heuristic is never shown as a fact.

---

## 1. Token scanner

**What good scanners do.** DEX Screener, GeckoTerminal and Birdeye all serve a *current snapshot
per pair*; history and per-trader aggregates need a chain indexer. Scanners pick a "main pair" per
token and show pair-level numbers.

**Sources (free, documented):**
- DEX Screener `GET /tokens/v1/{chainId}/{addresses}` (up to 30 tokens, 300 req/min) and
  `GET /token-pairs/v1/{chainId}/{token}` (all pools of a token, max 30, 300 req/min). Pair fields:
  `priceUsd`, `priceNative`, `txns.{m5,h1,h6,h24}.{buys,sells}`, `volume.*`, `priceChange.*`,
  `liquidity.{usd,base,quote}` (nullable), `fdv`, `marketCap` (nullable), `pairCreatedAt`
  (nullable), `labels`, `boosts.active`. Profiles/boosts endpoints are 60 req/min.
- GeckoTerminal public API: pools, trades, OHLCV. Keyless limit is **about 10 calls/min** per its
  own docs ("may fluctuate"); our client's 15 s interval keeps us under it.
- Solana RPC: `getAccountInfo` (jsonParsed) on the mint → supply, decimals, `mintAuthority`,
  `freezeAuthority`, owner program, Token-2022 extensions; `getTokenLargestAccounts` → the
  largest token accounts (returns up to 20 **(unverified count; docs example shows the shape only)**);
  `getMultipleAccounts` (jsonParsed) → the owner wallet of each of those token accounts.
- Birdeye: richer holder/trade data but needs an API key and has paid tiers **(unverified free
  limits)**. Not in v1.

**Design:**
1. **Pair selection is explicit.** Store all pairs; report the main pair by a stated rule (highest
   `liquidity.usd`, falling back to highest `volume.h24` when liquidity is null) and sum volume and
   txns across pairs separately. Pump.fun curve pairs report `liquidity.usd = null` (KR-000004):
   report "unknown", never 0.
2. **Holder concentration must exclude venues.** The largest token accounts include the curve or
   pool vault. Resolve each account's owner; mark owners equal to a known pair address or a known
   program-derived pool authority as `venue`, and report top-1/top-10 share both with and without
   venues. Unresolved owners stay "unknown". (KR-000017: in a PumpSwap pool, liq/MC ≈ 2 × pool share
   of supply, so the pool share is itself a fact worth reporting.)
3. **Age:** report `pairCreatedAt` as *pair age*; mint age needs the oldest signature of the mint
   (paging `getSignaturesForAddress`), which is costly for busy tokens: optional, cached forever
   once found.
4. **Ratios are descriptive only.** KR-000015 found no study validating MC/liquidity or volume/MC as
   screens, and on the Pump.fun curve liq/MC is fixed by curve progress. Show them, label them, don't
   rank by them. Prefer buyers/sellers counts and txns over raw volume (volume is washable).
5. **Cost per scan:** 1 DEX Screener call per 30 tokens + 3 RPC calls per token
   (mint info, largest accounts, owners). 30 tokens ≈ 91 calls.

## 2. Smart-money intelligence

**What good trackers do.** Labeling (Nansen/Cielo style) is the product: a wallet list with a
reason. PnL engines replay trades per (wallet, mint) with an accounting method; coordination is
found from timing (same slot / N slots) and funding links.

**Design:**
1. **Feed:** reuse WALLET_TRACKER_ARCHITECTURE (poll-first, per-wallet cursors, balance-delta
   decoding). Trades land in `trade`.
2. **PnL engine (pure):** average-cost per (wallet, mint) as in the user's solana-cluster-tracker;
   FIFO as an option. Report *realized* and *unrealized* separately; unrealized needs a timestamped
   price snapshot and is labeled with its `fetched_at`. Fees (tx fee + venue fee) included.
   Tokens received by transfer (not bought) have unknown cost basis: mark as `cost_unknown`, do not
   treat as zero cost, or PnL is inflated.
3. **Design around staged PnL (KR-000015):** about half of large Pump.fun wins went to wallets that
   were *handed* tokens and ~13% were wash loops. So a wallet's score must split: PnL from bought
   positions vs from transferred-in tokens; self-trade/wash loops (same funder on both sides,
   round-trips within N slots) excluded and counted. Leaderboard import is a *candidate list*, never
   a label.
4. **Coordination detection (heuristics, labeled as such):** co-buys of the same mint within the
   same slot / N slots across a wallet set; shared funding source (first SOL inflow from the same
   wallet within a window); RugCheck's "insider graph" is the same idea as a hosted service.
   KR-000015 (arXiv:2610.39458): group co-buy signals lost their effect under full covariates, and
   a naive co-buy score ranks as well as an elaborate one: start naive.
5. **Patterns:** hold-time distributions, entry-relative-to-launch, win rate per wallet with n and
   CI (Wilson, already in `research/stats.py`). No "copy this wallet" output.

## 3. Security analysis

**What is technically checkable on Solana (facts, read from the mint):**
- `mintAuthority` present → supply can grow. `freezeAuthority` present → holders' accounts can be
  frozen (the classic Solana "honeypot": you can buy, then can't sell).
- Token-2022 extensions on the mint (from Solana's `ExtensionType` list): `TransferHook` (a program
  runs on every transfer and can reject it), `PermanentDelegate` (can move/burn anyone's balance),
  `NonTransferable`, `DefaultAccountState` (new accounts frozen by default), `TransferFeeConfig`
  (fee on transfers, check rate and whether its authority can change it), `Pausable` (transfers can
  be halted), `MintCloseAuthority`. Each is a fact with the authority address as evidence.
- Metadata mutability (update authority) **(unverified field path; read the Metaplex account)**.
- Liquidity facts: share of supply in pools; LP tokens burned or locked for AMM pools that issue LP
  tokens (burn = LP supply held by the incinerator / supply reduced) **(unverified per-DEX method;
  PumpSwap/Raydium CPMM specifics need research)**.

**Hosted checkers (optional cross-checks, not truth):**
- RugCheck: `GET /v1/tokens/{mint}/report` and `/report/summary`; report sections include
  authorities, holders, markets, liquidity, detected risks, an aggregate score, creator info, and an
  insider-network endpoint. Free tier listed at 3 req/s; bulk endpoints are paid. Field names must
  be read from its Swagger at build time.
- GoPlus: `GET /api/v1/solana/token_security` (Solana marked beta). Its docs page needs an
  authorization token and lists no rate limit or field names we could read **(unverified; check
  free access before relying on it)**.
- honeypot.is-style *sell simulation* is an EVM technique (simulate buy+sell against the router).
  On Solana the equivalent is `simulateTransaction` of a swap, which needs a constructed swap
  transaction for each venue: out of scope for v1; the mint-level facts above cover the known
  Solana sell-blockers.

**Design:** two layers, never merged. *Facts* (authority set, extension present, top-10 share =
x%) and *heuristics* (bundle detected, suspicious funding) each stored as `flag` rows with
evidence and rule version. Output wording: "mint authority: present (address)", not "risky"/"safe".
No overall safety score in v1: KR-000015 notes early rug classifiers reach only F1 ≈ 0.78 with
authors saying it is not deployment-ready.

## 4. Social intelligence

**Data availability is the binding constraint:**
| Source | Free, legal access | Notes |
|---|---|---|
| X (Twitter) API | ✗ | Pay-per-use since Feb 2026: $0.005 per post read, no free tier for new developers. Conflicts with the no-paid-APIs rule. |
| Reddit Data API | ✓ (non-commercial) | 100 queries/min per OAuth client; needs an app registration (OAuth credentials). Commercial use needs a paid agreement. |
| Telegram Bot API | ~ | A bot only receives channel posts where it is an administrator; it cannot read arbitrary public channels. User-account scraping (MTProto) is a ToS/ban risk: not used. |
| DEX Screener profiles/boosts | ✓ | 60 req/min. Boosts are **paid promotion**: measures marketing spend, not organic attention. |
| Google Trends | ✗ | Official API is a limited alpha (announced Jul 2025), no public quota; scraping trends.google.com is not used. |
| Farcaster | ? | **(unverified)** free read access via hubs/Neynar not checked. |
| Discord servers | ~ | Only servers the bot is in, with the user's consent; message content intent required. |

**Design:**
1. Collect *counts per keyword per time bucket* (mentions, unique authors, engagement), not full
   texts; store raw posts only where terms allow.
2. Burst detection (pure): rolling z-score of bucket counts against a trailing baseline (with a
   minimum-count floor), and optionally Kleinberg's two-state burst automaton (Kleinberg 2002) for
   a less noisy signal. Keywords = token symbols/names + n-grams from titles.
3. Attention vs trading: align a token's mention series with its `snapshot` volume/txns series by
   time bucket; report lead/lag correlation with n, and flag "attention without trading" and
   "trading without attention". Both are descriptive.
4. Bot/shill filtering: unique authors and account age weigh more than raw counts.
5. Gate: low data availability → start with Reddit + DEX Screener profiles + the user's own Discord.

## 5. Strategy laboratory

**What good backtesters do:**
- *Event-driven* (NautilusTrader, Hummingbot, Freqtrade's loop, backtesting.py's `next()`): the
  strategy sees one bar/event at a time, so lookahead is structurally hard; same code can run live
  or in paper mode. *Vectorized* (vectorbt, Freqtrade's indicator precompute): fast parameter
  sweeps, easy to leak future data. Freqtrade ships `lookahead-analysis` (re-runs backtests on
  truncated data and compares signals) and `recursive-analysis` (checks indicator warm-up) because
  this bias is common.
- backtesting.py models `commission` (applied on entry **and** exit since v0.4.0), a constant
  `spread`, and fills market orders on the **next bar's open** unless `trade_on_close=True`; it
  reports win rate, max drawdown, profit factor, expectancy, SQN, and buy-and-hold return as a
  baseline.

**Our design (stdlib, event-driven):**
1. **Event replay core.** Input = time-ordered events (trades or candles) from the facts DB or
   recorded raw files. Strategy = pure object with `on_event(state, event) -> orders`. The same
   strategy class runs in backtest and paper mode; paper mode just feeds live snapshots instead of
   history (NautilusTrader's backtest/live parity).
2. **Fills:** orders fill at the *next* event, never the signal bar. AMM slippage from the pool's
   reserves at fill time using constant product: `out = (dx·(1−f)·y) / (x + dx·(1−f))`; the curve
   uses its virtual reserves (Pump.fun curve is Uniswap-V2-style on synthetic reserves). When
   reserves are unknown, the run fails rather than assuming zero slippage.
3. **Fees from config with sources:** Pump.fun bonding curve 1.25% total (0.30% creator, 0.95%
   protocol); PumpSwap fees are now tiered by market cap (0.30% shown for canonical pools in one
   table) → store a dated fee table per venue, plus Solana base/priority fees and a configurable
   failed-tx rate.
4. **Universe rule against survivorship bias:** sample tokens by *launch time* from chain data
   (the Researcher's stage-1 method), not from lists of surviving tokens; dead tokens stay in with
   their last price. DEX Screener drops inactive tokens (KR-000004), so it cannot be the universe.
5. **Bias checks built in:** truncation test (run on data up to t, then up to t+k; signals before t
   must not change), parameter count logged, out-of-sample window held back, walk-forward option.
6. **Metrics (definitions fixed in code):** win rate = winning closed trades / closed trades;
   profit factor = gross profit / |gross loss|; max drawdown = max peak-to-trough fall of the
   equity curve; expectancy; exposure; all with n and bootstrap CIs. **Benchmarks:** hold SOL,
   random entry with the same holding-time distribution and same fees (the honest baseline for
   memecoins), and "buy at launch, hold N minutes".
7. **Reporting rule:** a strategy is reported with its numbers, sample, window, fees and the
   benchmark gap. The word "profitable" is not used unless the out-of-sample CI excludes the random
   benchmark; even then it is "outperformed the benchmark in this sample".

## 6. Dashboard

**What others do:** FreqUI is a separate web front end talking to the bot's REST API; Hummingbot's
dashboard is a Streamlit app, and the Hummingbot API is a FastAPI server with PostgreSQL and an
MQTT broker. Both need long-running servers and third-party stacks.

**Our options:**
| Option | Server process | Deps | Works when laptop sleeps | Secrets exposure |
|---|---|---|---|---|
| Static HTML generated from `market.db` (stdlib `string.Template`, inline SVG charts) | — | — | ✓ (file stays) | none if no keys in data |
| Local web server (`http.server`, 127.0.0.1 only) | ✓ | — | — | low, local only |
| Discord embeds / attached HTML file | — (uses the existing bot) | discord.py (already) | ✓ | none |

**Design:** a one-shot `dashboard` tool renders a static HTML file (and optionally posts it to
Discord as an attachment) from the facts DB: market overview, trending (by txns/buyers, labeled
source), risk facts per token, smart-money activity, liquidity changes, social bursts, strategy
runs. Read-only, no JavaScript network calls, every panel shows `fetched_at` and source, stale
panels are greyed out. A local server is a later option only if interactivity is needed.

---

## 7. Build order and go/no-go (0–2 each; build when total ≥ 7 and no zero)

| # | Project | Evidence | Usefulness | Data | Maintenance | Not dup | Total | Call |
|---|---|---|---|---|---|---|---|---|
| 0 | Fetch-layer `live()` + `market.db` | 2 (infrastructure) | 2 | 2 | 2 | 2 | 10 | first |
| 1 | Token scanner | 1 (descriptive only) | 2 | 2 | 2 | 2 | 9 | go |
| 3 | Security facts (authorities, Token-2022, concentration) | 2 (mechanical facts) | 2 | 2 | 2 | 2 | 10 | go (with 1) |
| 5 | Strategy lab (core + metrics + benchmarks) | 1 | 2 | 1 (history: GeckoTerminal OHLCV slow; chain trades via Helius) | 2 | 2 | 8 | go after 1 |
| 2 | Smart money | 1 (KR-000015: staged PnL) | 2 | 2 (needs wallet list) | 1 | 1 (wallet tracker design exists) | 7 | go once the user names wallets |
| 6 | Dashboard (static HTML) | 2 (display) | 1 (until 1–5 have data) | 2 | 2 | 2 | 9 | after 1+3 have data |
| 4 | Social | 0–1 | 2 | 0 (X paid, Telegram/Trends closed) | 1 | 2 | 5–6 | **no-go now**; revisit with Reddit OAuth + own Discord |

---

## 8. Open questions for the Researcher (suggested Logbook topics)

1. **Holder exclusion:** which program-derived accounts hold the vaults for Pump.fun curve, PumpSwap,
   Raydium CPMM/AMM v4, Meteora DBC, and how to recognise them from `getMultipleAccounts` output
   (`token_launch_analysis`).
2. **LP burn/lock:** how to verify LP burn or lock per Solana DEX, including whether PumpSwap pools
   issue LP tokens (`market_structure`).
3. **PumpSwap dynamic fee schedule:** the current tier table by market cap, with source and date, for
   the lab's fee model (`market_structure`).
4. **History for backtests:** free sources for per-trade or 1-minute history of *dead* tokens (survivorship),
   and how far back the free Helius tier reaches (`data_sources`).
5. **Does any scanner metric predict anything?** A pre-registered test of buyers/sellers counts and
   top-10 share (venue-excluded) at T+1 h against 7-day survival, on launch-time samples
   (`token_launch_analysis`).
6. **Staged-PnL detection:** a validated rule for "handed tokens" and wash loops in wallet PnL, with
   precision on a labeled sample (`wallet_behaviour`).
7. **Social data:** whether Farcaster or other free sources carry memecoin chatter at useful volume;
   whether Reddit mention bursts lead DEX volume at all (`social_signals`).
8. **GoPlus/RugCheck free access:** actual free limits and field lists, and agreement rate between
   their flags and our mint-level facts on a sample (`security_analysis`).

## Sources (retrieved 2026-11-21)

- DEX Screener API reference: https://docs.dexscreener.com/api/reference
- GeckoTerminal API docs: https://api.geckoterminal.com/docs/index.html ; CoinGecko keyless API: https://docs.coingecko.com/docs/keyless-public-api
- Solana RPC `getTokenLargestAccounts`: https://solana.com/docs/rpc/http/gettokenlargestaccounts
- Solana Token Extensions (`ExtensionType`): https://solana.com/docs/tokens/extensions
- RugCheck API: https://rugcheck.xyz/api ; endpoint list (FluxRPC mirror of RugCheck docs): https://fluxrpc.com/docs/rugcheck ; Swagger: https://api.rugcheck.xyz/swagger/index.html (not opened)
- GoPlus Solana token security reference: https://docs.gopluslabs.io/reference/solanatokensecurityusingget
- Pump.fun fees: https://pump.fun/docs/fees ; bonding curve: https://pump.fun/docs/bonding-curve ; public docs repo: https://github.com/pump-fun/pump-public-docs
- Freqtrade lookahead analysis: https://www.freqtrade.io/en/stable/lookahead-analysis/ ; recursive analysis: https://www.freqtrade.io/en/stable/recursive-analysis/
- backtesting.py API: https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html
- Hummingbot dashboard: https://hummingbot.org/dashboard/ ; Hummingbot API architecture: https://hummingbot.org/hummingbot-api/
- X API pricing: https://docs.x.com/x-api/getting-started/pricing
- Reddit API limits (r/redditdev announcement): https://www.reddit.com/r/redditdev/comments/13wsiks/ ; Reddit Data API terms: https://redditinc.com/policies/data-api-terms (not opened)
- Telegram Bot API: https://core.telegram.org/bots/api ; admin requirement for channel posts (Stack Overflow, community source): https://stackoverflow.com/questions/45002999
- Google Trends API alpha: https://developers.google.com/search/blog/2025/07/trends-api
- Kleinberg, J. "Bursty and Hierarchical Structure in Streams", KDD 2002 (from prior knowledge, not re-read)
- Logbook: KR-000004, KR-000014, KR-000015, KR-000017
