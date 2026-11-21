# Wallet alert tracker architecture (v1, 2026-11-21)

How to build "tell me in Discord when wallet X buys or sells" on the user's Mac/Windows laptop.
Builds on `docs/BOT_ARCHITECTURE.md` (bot = front door) and `docs/SCRAPING_ARCHITECTURE.md`
(fetch layer). Read-only: alerts only, no trading.

Studied: the user's own `~/Documents/Projects/solana-cluster-tracker` (TypeScript, Helius
webhooks, discord.js, SQLite: the most complete sample), open-source trackers (Handi Cat,
imcrazysteven's tracker, LamboPoewert's tracker), Helius webhook and rate-limit docs, Solana
`logsSubscribe` docs. Sources at the end.

## 1. Three ways to hear about a wallet's transactions

| Feed | How | Latency | Free-plan limits (Helius, 2026-11-21) | Laptop fit |
|---|---|---|---|---|
| **A. Poll** | `getSignaturesForAddress(wallet, until=<last seen sig>)`, then fetch/parse the new txs | the poll interval (e.g. 15–60 s) | RPC 10 req/s | ✓ stdlib, survives sleep, nothing is lost |
| **B. Websocket** | `logsSubscribe {mentions:[wallet]}`, **one address per subscription** | ~seconds | Standard websockets; 5 concurrent connections | ~ needs a websocket library; drops silently on reconnect |
| **C. Webhook** | Helius POSTs enhanced txs for up to 100k addresses per webhook (5 webhooks on Free) | ~seconds | 1 credit per event | ✗ needs a public HTTPS URL (tunnel such as cloudflared/ngrok); must answer `200` within **1 s**; Helius retries only **3×, 1 s apart**, so a sleeping laptop loses events |

People do report missed transactions when monitoring many wallets with `onLogs`/`logsSubscribe`
(Solana StackExchange #18100). No push feed is complete on its own.

**Rule:** polling with a per-wallet cursor is the *source of truth*. A push feed (B or C) is an
optional *accelerator*. Both write into the same inbox, deduplicated by signature. That is the
"stream first, REST to heal" pattern from Hummingbot, and it is exactly what
solana-cluster-tracker does: webhooks live, `backfillOnStartup` from cursors after downtime.

## 2. Pipeline

```
 feeds (poll / ws / webhook)
        │  raw tx JSON
        ▼
 inbox table ──(persist BEFORE ack / before cursor moves)──  dedupe: signature UNIQUE
        │ drain serially, oldest slot first
        ▼
 decode ── swap / transfer / funding, from balance deltas (not per-DEX instruction layouts)
        ▼
 state ─── trades ledger (append-only) · positions (avg cost) · cursors per wallet
        ▼
 rules ─── pure: event + state -> alerts (thresholds, wallet labels, mutes)
        ▼
 alert outbox (dedupe key) ──> batcher ──> Discord (edit-in-place for bursts)
```

## 3. Patterns worth copying from solana-cluster-tracker

1. **Durable inbox: persist before acknowledging.** The webhook payload goes into
   `webhook_inbox` synchronously before the HTTP `200`. A crash leaves the row PENDING and it is
   processed on restart. Failures retry up to a cap, then are parked as **DEAD** for
   inspection (`/inbox retry_dead`). Nothing is lost silently.
2. **Cursor catch-up after downtime** (one-shot, not a loop). For each wallet, fetch
   signatures `until` its last processed one, sort missed txs **oldest first** (buys before the
   sells that follow), and queue them as `backfill`. The cap per wallet is logged when hit.
3. **Idempotency.** A `processed_signatures` table absorbs webhook retries and duplicates.
   Funding events carry an idempotency key.
4. **Decode amounts from balance deltas** (`accountData`), with program IDs used only to label
   the venue. That survives routing (Jupiter → Raydium) and DEX instruction-layout changes.
   Rent and WSOL wrap/unwrap are handled so they cancel out.
5. **Pure engines, unit-tested.** The average-cost PnL engine (`positions.ts`) is pure. Sells of
   tokens never seen bought are flagged and excluded from ROI, so ROI isn't inflated.
6. **Alert batching without timers.** The first buy posts immediately. More buys of the same
   (cluster, mint) within 15 s edit that message in place, up to 120 s per burst. If the
   message was deleted, it reposts. No background loop.
7. **Recorded fixtures.** `scripts/record-fixture.ts` saves real payloads as decoder regression
   tests. `scripts/simulate.ts` fires synthetic webhooks end to end.
8. **Ops.** A silence watchdog (no events for N minutes means alert), rotating DB backups,
   counters. The bot checks it can post in each channel at startup and refuses to start otherwise.
9. **Registry integrity in the DB.** CHECK constraints and triggers enforce wallet roles
   (PUBLIC / SIDE / EXCHANGE) and unique aliases.

## 4. Patterns from public trackers

- All three public bots use the same stack shape: Helius RPC/websocket or webhook in, a
  database, a chat bot out. Handi Cat adds token context (SOL price of the swap, % of supply
  held) and chart links. Those are useful read-only enrichments.
- We **don't** copy: "buy now" links to trading bots (Handi Cat) and token-gated access
  (LamboPoewert). They're out of scope and add trust and safety risk.

## 5. Our design for the laptop

1. **Poll-first core, stdlib.** One-shot `tools/wallet_watch/run.py`: for each tracked wallet,
   page `getSignaturesForAddress` with `until=cursor`, fetch only new txs, write them to the inbox,
   then decode → rules → outbox, and advance cursors **in the same transaction**. Started every N
   seconds by the Discord bot's timer through the task queue (BOT_ARCHITECTURE §4).
2. **Budget math before adding wallets.** Calls per cycle ≈ wallets + new txs. Example: 50
   wallets every 30 s ≈ 1.7 req/s, under the free 10 req/s. The run refuses a config that would
   exceed the provider cap in `config/limits.json`.
3. **Optional accelerator later.** A websocket subscriber inside the bot process (one
   subscription per wallet, under 5 connections) that only *kicks* an immediate poll run. It never
   writes state itself, so a dropped websocket costs latency, not data. Webhooks only if the
   user wants a tunnel. That's a later decision.
4. **After sleep:** the next run starts from the cursors, processes oldest first, and labels
   alerts older than X minutes as "late (catch-up)" instead of posting them as live.
5. **Wallet registry via Discord:** `/track <address> <label>`, `/untrack`, `/list`, `/mute`.
   Validate the base58 address, cap the list size, and restrict commands to the user's role.
6. **Alerts:** dedupe key = signature + rule, recorded in the outbox before sending. Bursts are
   batched per (wallet group, mint) like §3.6. `allowed_mentions` is off.
7. **Tests:** decoder on recorded real tx fixtures. Rules and batcher pure. One end-to-end run
   on fixtures with a fake clock. Failure paths: 429 → pause provider, killed mid-run → resume,
   duplicate signature → ignored.
8. **Language:** this repo is Python/stdlib. Port the *patterns*, not the TypeScript code.
   solana-cluster-tracker stays the reference implementation.

## Sources (retrieved 2026-11-21)

- `~/Documents/Projects/solana-cluster-tracker` README, `src/services/ingest.ts`, `src/discord/alertBatcher.ts` (local, not a git repo)
- https://www.helius.dev/docs/webhooks
- https://www.helius.dev/docs/faqs/webhooks (retries 3× at 1 s, 200 within 1 s, duplicates possible, public HTTPS, 1 credit/event)
- https://www.helius.dev/docs/billing/rate-limits (Free: 10 RPC req/s, 5 webhooks, 100k addresses/webhook, 5 websocket connections)
- https://solana.com/docs/rpc/websocket/logssubscribe (`mentions` takes a single address)
- https://solana.stackexchange.com/questions/18100
- https://github.com/DracoR22/handi-cat_wallet-tracker
- https://github.com/imcrazysteven/Solana-Wallet-Tracking-Telegram-Bot-Portfolio
- https://github.com/LamboPoewert/solana-wallet-tracker-bot

Not verified: the public trackers' internals (README level only); Helius limits change, so recheck
before building; whether solana-cluster-tracker's tests currently pass (not run).
