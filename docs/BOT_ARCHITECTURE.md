# Bot and app architecture: lessons from production systems (v2, 2026-11-21)

v2: target changed to macOS/Windows laptop, launched from Discord; phone secondary.

Reference for every tracker, scraper and alert tool built under `tools/`.
Studied: NautilusTrader (institutional-grade engine), Hummingbot (retail market-making
framework), Freqtrade (retail strategy bot), chainstacklabs/pumpfun-bonkfun-bot
(open-source pump.fun bot), shaurya35/solana-realtime-indexer (pump.fun trade indexer),
Discord developer docs. Sources at the end.

## 1. The common shape

Every serious system splits into the same five parts, each behind one interface:

```
 Source adapter ──> Decoder ──> Event bus / queue ──> Strategy / rules ──> Sink
 (websocket, gRPC,   (raw ->     (topics, bounded)     (pure function:      (Logbook, Discord,
  RPC poll, file)    typed obj)                         events -> signals)   order engine*)
                                      │
                                Risk / guard layer  (* execution is out of scope here)
```

- **Adapters are swappable at one boundary.** NautilusTrader runs the same kernel in
  backtest and live; only the data and execution clients change. The pump.fun bot picks its
  listener (`geyser`, `logs`, `blocks`, `shreds`) with one YAML key. Same strategy code, different source.
- **Decoding is separate from deciding.** Indexer: datasources/ → processors/ (decoders) →
  writer. The pump.fun bot: listeners → parsers → buyer/seller.
- **Strategies are pure.** They read events and state and return decisions. They do no I/O.
  That makes them testable offline and replayable.

## 2. Reliability lessons (where hobby bots fail)

| Lesson | Who does it | How |
|---|---|---|
| Record intent before calling the outside world | Hummingbot | Starts tracking an order *before* submitting, so a timeout never loses it |
| Never lose data silently | Indexer | Two gap detectors (30 s silence, slot jump ≥ 50) write to a `stream_gaps` table |
| Backfill and verify | Indexer | `recover` refetches gaps from RPC through the *same* decoders; `verify` compares expected vs stored both ways |
| Checkpoint in the same transaction as the data | Indexer | One-row checkpoint advances only when its batch commits |
| Bounded everything | Indexer | Events queue 10k (block, never drop); lookup queue 1k (drop and count); writes batched 100 rows / 500 ms |
| Different queues, different overflow policy | Indexer | Losing an event is fatal; losing a cache lookup is cheap |
| Determinism | NautilusTrader | Single-threaded core, events in fixed order; production incidents can be replayed |
| Fixed component order | Hummingbot | A clock ticks components in insertion order, so data updates run before strategy |
| Streaming first, REST as backup | Hummingbot | Websocket for latency, REST to heal state |
| Pre-trade risk gate | NautilusTrader | RiskEngine validates every command and rate-limits submissions |
| Rate limits from headers | Discord | Read the limit headers; on 429 sleep exactly `retry_after`; repeated 401/403/429 can get an IP blocked |
| Backtest ≠ live | Freqtrade issue #7502 | Users report backtest vs dry-run mismatches; parity has to be designed in (Nautilus), not assumed |

## 3. Memecoin-specific notes

- **Detection.** The fastest feed is Yellowstone gRPC (Geyser). It filters by program ID and
  decodes the `Create` instruction from its 8-byte discriminator, with no follow-up RPC
  calls. It is paid and an always-on stream. Free tiers: websocket `logsSubscribe` or polling.
  The Researcher confirmed Helius `getTransactionsForAddress` works on the free plan (KR-000003).
- **Survivorship.** DexScreener drops inactive tokens, and `liquidity.usd` is null on
  bonding-curve pairs (KR-000004). Sample launches by time from the chain (KR-000002), not from lists.
- **Pre-buy checks used by bots** (top holders, creator history, name match, max token age)
  are just filters. As read-only scoring they are useful for alerts too.
- **Scams.** The pump.fun bot repo warns that scam bots post wallet-drainer links in its
  issues. Never run untrusted bot code that asks for a private key.

## 4. What we adopt: a laptop (macOS / Windows) driven from Discord

Primary target is the user's Mac or Windows laptop. The phone (Termux) is secondary:
tools stay portable, but the design assumes a desktop.

```
 Discord (you)                       Laptop
 /scan, /status  ───gateway──>  bot/ (one supervised process, discord.py, asyncio)
                                  │ 1. check user/role, validate input
                                  │ 2. defer reply (3 s limit -> 15 min)
                                  │ 3. TaskQueue.add(...)  (SQLite, ecosystem/)
                                  │ 4. run tool in a SUBPROCESS: sys.executable -m tools.<name>.run
                                  │ 5. post result: followup (<15 min) or channel message
                                  ▼
                         tools/<name>/  one-shot, resumable, stdlib-only
                         source -> decode -> rules -> sink, checkpoint + results in one transaction
```

1. **The bot is only the front door.** It parses commands, checks permissions, queues the
   task and starts the tool. It does no analysis itself. Blocking code in the bot stalls its
   heartbeat ("Heartbeat blocked for more than N seconds", discord.py FAQ) and Discord drops
   the connection.
2. **Work runs in a subprocess, not in the bot.** That keeps the event loop free and contains
   crashes. Each job's memory is freed when it exits. The same command works without Discord:
   `python3 -m tools.<name>.run`.
3. **Defer, then follow up.** An interaction must be answered within 3 seconds. Deferring
   extends that to 15 minutes. Longer jobs post a fresh channel message when they finish.
4. **One supervisor, one instance.** macOS: a `launchd` LaunchAgent in `~/Library/LaunchAgents`
   with `RunAtLoad` + `KeepAlive` restarts the bot after a crash or login. Windows: Task
   Scheduler "at log on" with restart-on-failure. The bot takes a lock file at start so a
   second copy (supervisor plus a manual run) exits instead of double-replying.
5. **Laptop sleep is normal.** When the lid closes, the bot goes offline and scheduled scans
   don't run. On wake, discord.py reconnects, and the next run reads its checkpoint and
   backfills the missed range (gap table), so nothing is skipped silently. 24/7 alerts need an
   always-on machine. That is a later decision.
6. **Schedules go through the same queue.** Periodic scans are tasks added by the bot's timer
   (or launchd `StartCalendarInterval` / Task Scheduler), so budgets, caps and checkpoints apply
   to every run.
7. **Dependencies.** `ecosystem/` and `tools/` stay standard-library. The bot alone may use
   `discord.py` (the stdlib has no websocket client for the gateway), pinned in
   `bot/requirements.txt` inside a venv. Plain alerts don't need the bot: an outgoing webhook is
   one HTTPS POST with `urllib`.
8. **Secrets.** The bot token and webhook URL come from the environment, loaded from a
   git-ignored `.env` or the OS keychain (macOS Keychain, Windows Credential Manager). Never in
   the repo, the Logbook or chat.
9. **Cross-platform code.** `pathlib` everywhere, `sys.executable` for subprocesses, UTF-8 I/O,
   no shell built-ins, no hard-coded `/tmp` (use `tempfile`). The SQLite DB stays on a local disk.
   Keep it out of iCloud/OneDrive/Dropbox-synced folders, because sync tools can corrupt a live
   SQLite file with its `-wal`/`-shm` side files.
10. **Discord hygiene.** Slash commands registered to the user's server only, restricted to the
    user's role. `allowed_mentions` off, so alerts can't ping @everyone. Validate token/mint
    addresses before use. discord.py handles REST rate limits. Our own code honours `Retry-After`.
11. **Idempotent alerts.** Each alert has a dedupe key (e.g. mint + rule), stored before
    sending, so re-runs after sleep never double-post.
12. **Testing.** Tools: record-and-replay fixtures, no network (as before). Bot: command
    handlers are thin functions tested with a fake interaction object. The Discord connection itself
    is checked manually once per release.
13. **No execution layer.** Signals end at the alert. Sniping/trading would need keys and
    paid low-latency infrastructure. Out of scope by rule.

## Sources (retrieved 2026-11-21)

- https://nautilustrader.io/docs/latest/concepts/architecture/
- https://nautilustrader.io/blog/why-nautilustrader-exists/
- https://hummingbot.org/blog/hummingbot-architecture---part-1/
- https://hummingbot.org/blog/hummingbot-architecture---part-2/
- https://www.freqtrade.io/en/stable/bot-basics/
- https://github.com/freqtrade/freqtrade/issues/7502
- https://github.com/chainstacklabs/pumpfun-bonkfun-bot
- https://docs.chainstack.com/docs/solana-listening-to-pumpfun-token-mint-using-geyser
- https://github.com/shaurya35/solana-realtime-indexer/blob/main/DESIGN.md
- https://docs.discord.com/developers/events/gateway
- https://support-dev.discord.com/hc/en-us/articles/6223003921559-My-Bot-is-Being-Rate-Limited
- https://discordpy.readthedocs.io/en/stable/faq.html
- https://gist.github.com/cibere/7e1356575780e716d2e3a23ea2bcf6da (defer: 3 s -> 15 min)
- https://www.launchd.info/

Not verified: Discord HTTP-interaction details (signature check), the exact Windows Task
Scheduler restart settings, and whether `~/Documents` on this Mac is iCloud-synced (the check
hung). The 3 s / 15 min interaction limits come from a discord.py gist and tutorial, not the
official page, which did not render.
