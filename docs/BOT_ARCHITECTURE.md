# Bot and app architecture: lessons from production systems (v1, 2026-11-21)

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

## 4. What we adopt (Termux, 4 GB, stdlib, read-only)

1. **One-shot runs, not daemons.** Each run: load checkpoint → fetch since checkpoint →
   decode → rules → write results and checkpoint in one transaction → exit. Android can kill
   the process at any point, and the next run resumes.
2. **Layout per tool:** `source.py` (adapter, the only network code) · `decode.py` ·
   `rules.py` (pure) · `sink.py` (Logbook / Discord) · `run.py` (wires them, one run) ·
   `fixtures/` (recorded raw responses) · `tests/`.
3. **Record-and-replay tests.** Save real API responses once as fixtures. Tests run decoders
   and rules on fixtures with no network. Live and test share the same code path.
4. **Gaps are data.** Each run logs the range it covered. A missed range is stored and
   backfilled next run, never skipped silently.
5. **Budgets and limits** go through `TaskQueue.provider_request()` (daily caps, rate-limit pause).
   On HTTP 429, honour `Retry-After` and stop the run. No retry loops.
6. **Idempotent sinks.** Alerts carry a dedupe key (e.g. mint + rule), stored before sending,
   so a re-run never double-posts.
7. **Discord = outgoing webhook.** One HTTPS POST per alert from a one-shot run. No gateway
   connection, no bot token, no server. Interactive slash commands need either an always-on
   gateway connection or a public HTTPS endpoint. Both need a host other than the phone.
8. **No execution layer.** Signals end at the alert. Sniping/trading would need keys and
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

Not verified: Discord's exact HTTP-interaction requirements (signature check, response
deadline). The docs page did not render; read it before building slash commands.
