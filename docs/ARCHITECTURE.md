# Architecture (v1, 2026-11-21)

## 1. Environment audit (Phase 1)

Audited the machine this agent runs on, 2026-11-21:

| Item | Found |
|---|---|
| Host | macOS 15.8.3, x86_64, 32 GB RAM, 376 GB free. **Not** the Android/Termux target from the directive. |
| Hermes | **Not installed** (`hermes` not on PATH, no `~/.hermes`). |
| Agent runtime available | OpenBot (local multi-agent app) with an existing "Research Desk" agent. |
| Python | 3.9.6 (system) |
| SQLite | 3.43.2, FTS5 works |
| git | 2.56 |
| Manim / animation project | Neither found on this machine. |
| Related prior work | `~/Documents/Projects/solana-cluster-tracker` (Helius webhooks, wallet clusters, SQLite), `robinhood-nft-scanner` |

The Android phone has not been audited. Run `scripts/audit.sh` (planned) or the commands in `PROJECT_STATUS.md` there.

## 2. Dependencies

Required: Python ≥ 3.8 with sqlite3 FTS5. Nothing else.
Termux: `pkg install python git` (its sqlite has FTS5). Collectors will use `urllib` (no `requests`).
Optional later: `numpy`/`pandas` only if the statistics outgrow the standard library. On Termux these are heavy, so avoid them until needed.

## 3. Data model (`ecosystem/schema.sql`)

- `records` holds findings, hypotheses, observations, projects, experiments, tools, lessons, failed approaches, decisions and reports. Each one has an id (`KR-000001`), title, description, category (15 fixed values), validation status (the 6 levels in the directive plus `n/a`), confidence 0–1, methodology, sample size, time period, evidence, limitations, dates, version and content hash.
- `record_versions` stores a full JSON snapshot of the record before each update.
- `sources` stores the url, tx, wallet, dataset, file and api references for each record.
- `links` stores typed relations between records: related, supports, contradicts, supersedes, derived_from, implements, tests.
- `records_fts` is an FTS5 index with porter stemming, kept in sync by triggers.
- `tasks` is the queue. Each task has an objective, a done condition, a JSON budget, usage counters and a progress checkpoint.
- `messages` keeps every protocol message, both requests and replies.
- `api_usage` counts requests per provider per day and records any rate-limit pause.

## 4. Protocol `rkd/1`

```json
{"protocol":"rkd/1","id":"M-…","from":"researcher","to":"logbook",
 "type":"submit_record","reply_to":null,
 "payload":{"record":{…},"sources":[{"kind":"url","ref":"…"}],"links":[{"dst":"KR-000003","relation":"supports"}]}}
```
Request types: `submit_record`, `update_record`, `link`, `query`, `get`, `history`, `contradictions`, `stale`, `task_add`, `task_report`.
Replies have type `result` or `error`, with `reply_to` set to the request id. A duplicate is returned as an error that includes `duplicate_of`.

Agents run one after another and never in parallel. The coordinator loop (Phase 6) claims one task, runs one agent, writes the results through the protocol, and stops. The user doesn't have to copy anything between agents.

## 5. Phased plan

| Phase | Deliverable | Done when |
|---|---|---|
| 1 Audit | this file | ✓ Mac audited; phone pending |
| 2 Foundation | schema, db, queue, protocol, CLI | ✓ tests pass |
| 3 Logbook | save/search/update/history/dupes/contradictions/stale | ✓ core tested; still to do: natural-language Q&A on top of search, JSON export/backup |
| 4 Researcher | read-only collectors (DEX Screener-style public API, Solana RPC), a research report template, one reproducible study on dev-wallet sell timing | report stored with sample size, time period and limitations; a re-run reproduces the numbers |
| 5 Builder | queries the Logbook, builds one small tool (e.g. a dev-wallet hold-time checker) with tests | tests pass, tool record linked `implements` to its finding |
| 6 Integration | `run_once` coordinator: one task per run, budgets enforced | a finding travels Researcher → Logbook → Builder → test result → Logbook |
| 7 Improvement | Validator (tries to disprove findings before they can be promoted), scheduling | promotions to `validated` require a Validator pass |

## 6. Obstacles

- Hermes isn't on this machine. The directive assumes it. Its features need checking on the phone before we depend on them. The Python core doesn't depend on any runtime.
- Some data is hard to get. Labelling developer wallets, tracing funding and seeing liquidity removals need chain-level data (Helius / Solana RPC). Free tiers limit how far back history goes.
- Survivorship bias: launches that died early are under-represented in most APIs. The Researcher has to sample launches by launch time, not by surviving lists.
- Android can kill background processes (Termux). Hence runs are one task at a time and resumable from checkpoints.
- Free LLM quotas are small. The LLM is used only for synthesis; numbers come from Python.

## 7. Resource estimate (4 GB phone)

Measured on the Mac: about 12 MB peak RSS per CLI run, 112 KB database with one record. Expect about 1–3 KB per record including the FTS index, so 100k records would be roughly 100–300 MB on disk. No daemons. One Python process at a time, under 50 MB even with collectors. The LLM runtime (Hermes or another) will use far more memory than this core.
