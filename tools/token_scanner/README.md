# token_scanner

Version 0.2.0 · based on Logbook findings KR-000038 (historically_supported, n=415) and design KR-000026 ·
also uses KR-000004 (DEX Screener gaps) and KR-000015 (ratios are not validated screens).

Measured facts and labelled risk flags for one Solana token. **Not a rating, not a safety verdict, not advice.**
Outputs are ordered by risk (facts, then heuristics), never by upside, and nothing is scored or ranked.

## Objective
Report a Solana token's market, holder and mint-permission facts with timestamps, plus Pump.fun block-0
risk context, for the Discord `/scan` command and the command line.

## Go/no-go gate (2026-11-22)
| Item | Score | Why |
|---|---|---|
| Evidence | 2 | Permission facts are mechanical; launch context uses KR-000038 (historically_supported, replicated on two days). Market numbers are descriptive only and are labelled so. |
| Usefulness | 2 | The user asks for it; it shows risk flags (freeze/mint authority, Token-2022 sell blockers, bought graduation) before anyone looks at price. |
| Data | 2 | DEX Screener (free, keyless) + Helius free plan (KR-000003). 4–5 calls per scan. |
| Maintenance | 2 | One-shot process behind the one supervised bot; stdlib only; failures appear in `missing`. |
| Not a duplicate | 2 | No `tool` record for a scanner in the Logbook. |
| **Total** | **10** | build |

## Requirements
- Input: one Solana mint address. Read-only public data. No wallets, keys for trading, or paid APIs.
- Output: deterministic JSON (sorted keys) with tool, version, findings, `generated_at`, and per-source
  `fetched_at`; optional Discord-ready text (`--text`, ≤ 4000 chars). Saved to `data/exports/token_scanner/`.
- Budget: `RKD_SCANNER_DAILY_BUDGET` calls per UTC day (default 300), counted in
  `data/raw/usage_token_scanner_<day>.json`. Shared throttle and rate-limit pauses with every other collector.
- Python 3.8+ stdlib; macOS/Windows first, Termux-portable; one process per scan.

## Architecture
- `token_scanner.py`: pure functions over raw responses (no network, no clock).
  `market` → `mint_facts` → `holders` → `launch_context` (reuses `research/study3_parse.block0`) → `build_report` → `render_text`.
- `cli.py`: validates input, reads through `collectors/client.py` (`live()` path: fresh, each response kept as a
  timestamped snapshot under `data/raw/<provider>/live/<day>/`), keeps going past single failures, stops all
  calls on a rate limit or budget stop.
- `FixtureApi` replays recorded responses (`--fixtures DIR`), used by the tests.

Calls per scan:
| Read | Endpoint | Freshness |
|---|---|---|
| pairs | DEX Screener `GET /token-pairs/v1/solana/{mint}` | live, reused if < 60 s old |
| mint | Helius `getAccountInfo` (jsonParsed) | live, < 60 s reuse |
| holders | Helius `getTokenLargestAccounts` | live, < 60 s reuse |
| owners | Helius `getMultipleAccounts` (jsonParsed) of those accounts | live, < 1 h reuse |
| creation page | Helius `getTransactionsForAddress(mint, asc, 100)` | history, cached forever; Pump.fun tokens only |

## What it reports and how
- **Permission facts:** mint authority, freeze authority (a frozen holder cannot sell), and Token-2022
  extensions that can block or reverse transfers: transfer hook, permanent delegate, non-transferable,
  default-frozen accounts, transfer fee, pausable, mint close authority, confidential transfers.
  Metadata extensions are not flagged. Unknown extensions are flagged as `unrecognised_extension`.
- **Holders:** the largest token accounts, grouped by owner wallet. Owners equal to a listed pair address
  are venues (the Pump.fun pair address is the bonding curve: checked on 3 of 3 cached cases; PumpSwap
  pools own their vaults, as in `study3_parse.pool_state`). Top 1 and top 10 shown with and without venues.
  Concentration flags (top 1 ≥ 10 %, top 10 ≥ 30 % of non-venue wallets) are **heuristics with
  unvalidated thresholds**.
- **Launch context (Pump.fun only):** creation-slot buyers and supply share, and same-slot graduation, from
  the Researcher's `block0()`. "Graduated" means DEX Screener lists a PumpSwap pair. It is risk context,
  never quality (KR-000038).
- **Market:** main pair by a stated rule (highest `liquidity.usd`, else highest 24 h volume), only pairs
  where the token is the base. Price, market cap, liquidity, volume, buy/sell counts and share per window,
  totals over all pairs. Missing liquidity is "unknown", never 0.
- **Ratios:** liquidity/MC and volume/MC, shown as descriptive only.
- **Age:** from the creation transaction when read, else DEX Screener pair age (labelled as pair age).

## Risk signals (docs/RISK_SIGNALS.md v1, Researcher, 2026-11-22)
Every flag carries `label` (fact · capability, fact, fact whose meaning is a replicated association, or
heuristic), `records` (Logbook ids), `source` (the read it comes from) and that read's `fetched_at`. Flags with
published rates carry `context` with n and CI. No flag means "none seen in the data read", never safe.

| Spec signal | In 0.2.0 |
|---|---|
| Freeze authority retained | ✓ "can freeze holders" (capability, not a confirmed honeypot). Flagged only for new mints: never for USDC/USDT, and not when the mint (or its oldest pair) is older than 30 days; those go to `not_flagged`. Unknown age is treated as new. |
| Freeze authority used (event) | — not checked; reported in `missing` as `freeze_used` whenever the freeze flag is raised |
| Token-2022 sell-block capabilities | ✓ transfer hook, permanent delegate, default-frozen, non-transferable (plus fee, pausable, close authority) |
| Block-0 cluster, same-slot graduation | ✓ with KR-000036/38 rates as context |
| Dev funded block-0 buyers | — waits for study 4 (KR-000039/40) |
| Thin pool 1 h after graduation, dev exit within 1 h | — not shown: low information or mechanical (KR-000037, KR-000012/23) |
| EVM honeypot simulation, slippage > 10 % | — out of scope (Solana only; the scanner does not trade) |

## Testing
`python3 -m unittest discover -s . -t . -v` from the repo root. Scanner tests:
`tools/token_scanner/tests/` (16 tests): pure logic, three offline end-to-end cases on real responses
recorded 2026-11-22 (a graduate, a curve token, USDC), determinism, Discord text size and wording,
and failure paths (invalid input, rate limit stops later calls, nothing fetched).

Measured run (live, 2026-11-22, MacBook, Python 3.9.6): Pump.fun graduate `FiVRbr…pump`,
5 API calls, **3.12 s wall, 27.7 MB peak RSS** (`/usr/bin/time -l`).

## Known limitations
- Holder data covers only the largest accounts the RPC returns (20 seen); total holder count is unknown.
  For tokens with very many holders (e.g. USDC) Helius refuses `getTokenLargestAccounts`; holders are then missing.
- When DEX Screener lists no pair (or the pairs fetch fails), venues are unknown: `venues_known` is false,
  venue share and wallet concentration are not computed, and no concentration flag is raised. Only the
  largest-account shares (pools/curve included) are shown. This is common for dead or unlisted Pump.fun tokens.
- Venues are found only by matching listed pair addresses. Pools that DEX Screener doesn't list, lockers,
  CEX wallets and other program accounts count as ordinary holders.
- Block-0 counts mix dev bundles with independent snipers (no funding-link test yet). If the creation slot
  holds 100+ transactions the values are lower bounds (`page_truncated`). The finding is association only.
- No sell simulation (honeypot test) and no LP burn/lock check: per-venue methods are unverified (KR-000026 §3).
- Metadata mutability (Metaplex update authority) is not read.
- DEX Screener drops inactive tokens (KR-000004): a dead token shows no market data, not zero.
- Prices and volumes are DEX Screener's numbers, not recomputed on chain; volume is washable.
- One chain (Solana). No history: each scan is a snapshot; snapshots are kept in `data/raw/*/live/`.

## Version history
- 0.2.0 (2026-11-22): risk signals v1 from docs/RISK_SIGNALS.md: labels, records, sources and timestamps on
  every flag; freeze authority scoped to new mints, stablecoins excluded; `freeze_used` reported as not checked.
- 0.1.1 (2026-11-22): Validator report KR-000043: venues unknown when no pair is listed (B1); creation-slot
  wording 'received (net)' (N1); fixtures checked against the requested mint (N2).
- 0.1.0 (2026-11-22): first version. Adds `collectors/client.py` `live()`.
