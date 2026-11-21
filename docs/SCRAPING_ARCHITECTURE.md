# Scraping and collection architecture (v1, 2026-11-21)

How every collector and scraper in this repo is built. It sits underneath
`docs/BOT_ARCHITECTURE.md`: the Discord bot starts a job, and this document describes the job.
Studied: Scrapy (the standard Python crawling framework), Crawlee (Apify's crawler framework),
HTTP conditional requests (MDN), and our own `collectors/client.py`. Sources at the end.

## 1. The shape every framework converges on

Scrapy's data flow (official docs), reduced to its parts:

```
 seeds ─> Scheduler/queue ─> [request middleware] ─> Downloader ─> [response middleware]
            ▲  (dedup by key)                                         │
            │                                                          ▼
            └──── new requests ◄──── Parser ("spider") ────► items ─> Pipeline ─> Storage
```

| Part | Scrapy | Crawlee | Ours |
|---|---|---|---|
| Work queue with dedup | Scheduler | RequestQueue (one request per unique key) | `tasks` table + request key = hash(method, params) |
| Fetching, separate from parsing | Downloader | crawler + HTTP client | `collectors/client.py` |
| Cross-cutting hooks (throttle, cache, retry, auth) | Downloader middlewares | crawler options | functions in `client.py`, one place |
| Parsing | Spider callbacks | request handlers / router | pure `decode.py` per tool |
| Clean-up, validation, storage | Item pipelines | Dataset (append-only), KeyValueStore | `rules.py` → sink (Logbook / SQLite / Discord) |
| Run statistics | stats collector | Statistics (requests, retries, errors) | per-run summary row |

The lesson: the **fetch layer is one shared module** that every source goes through, so caching,
throttling, budgets and errors behave the same everywhere. Parsers never touch the network.

## 2. Rules we adopt

1. **API first, HTML last.** Use documented JSON APIs and RPCs (DexScreener, Helius, public RPCs)
   before scraping pages. HTML breaks when the layout changes and often conflicts with terms of
   service. Read each source's terms and published rate limits. Respect `robots.txt` for any
   HTML crawl (stdlib `urllib.robotparser`).
2. **Raw first, parse second.** Save the raw response before parsing it (Crawlee's key-value
   store, our `data/raw/`). A parser bug then means re-parsing from disk, not re-fetching. It is
   also the fixture set for offline tests.
3. **Two cache modes, chosen per call.**
   - *Research / immutable* (a finalized transaction, a past block): cache forever. That is
     `client.py` today, and it is why studies reproduce offline.
   - *Tracking / live* (price, liquidity, "latest" lists): cache with a TTL and keep every
     snapshot with `fetched_at`. Never serve a stale "latest" as if it were current. Where
     the server sends `ETag`/`Last-Modified`, revalidate with `If-None-Match`/`If-Modified-Since`:
     a `304` costs almost no bandwidth (MDN).
4. **Adaptive politeness, never faster than the published limit.** Scrapy AutoThrottle:
   start at 5 s delay; target delay = latency / target concurrency (default 1); next delay =
   average of the previous and target; non-200 responses may only *increase* the delay; clamp to
   [DOWNLOAD_DELAY, 60 s]. We keep a fixed ceiling (RKD_RPS) and only slow down from there.
5. **One rate limiter per provider across processes.** With the Discord bot starting jobs as
   subprocesses, an in-memory throttle no longer holds. Keep counters and pauses in SQLite
   (`api_usage`, which already has `paused_until`), not in per-process memory or a JSON file.
6. **Error classes decide the action:**

   | Response | Action |
   |---|---|
   | 2xx | save raw, parse |
   | 304 | reuse cached body, count as cheap |
   | 429 / RPC rate-limit | pause the provider until `Retry-After` (or a default, e.g. 10 min), stop this run |
   | 5xx, timeout, connection reset | bounded retry with exponential backoff (e.g. 3 tries: 1 s, 2 s, 4 s), counted against the budget, then fail the item |
   | other 4xx | no retry, log it, fail the item |
   | 200 with unexpected shape | **schema-drift error**: save the raw body, raise a visible alert |

7. **Crash-safe state.** All state writes are atomic: write to a temp file and `os.replace()`, or
   use one SQLite transaction. Checkpoints advance in the same transaction as the data (see
   BOT_ARCHITECTURE §2). A process killed mid-write must never leave a file the next run can't read.
8. **Dedup by stable key, idempotent writes.** Request key = hash(provider, method, params). Item
   key = natural id (signature, mint, pair+timestamp). `INSERT OR IGNORE` on that key, so re-runs
   after a crash or laptop sleep never duplicate rows.
9. **Validate at the boundary.** Every decoder checks required fields and types and records
   nulls explicitly. Example: DexScreener `liquidity.usd` is null on bonding-curve pairs
   (KR-000004). A source silently changing shape is the main way scrapers rot.
10. **Survivorship-aware sampling.** Lists from aggregators drop dead tokens (KR-000004). Seed
    from the chain by time (KR-000002), and use aggregators only to enrich.
11. **Budget and stats per run.** Each run records calls, cache hits, 304s, retries, errors and
    wall time, and the bot posts that summary to Discord with the result.
12. **Secrets never in URLs we store.** Keys are read from the environment and kept out of cache
    keys and logs. `client.py` already does this.
13. **Out of scope:** anti-bot evasion (fingerprint spoofing, rotating proxies to dodge blocks,
    CAPTCHA solving). Crawlee ships a session pool for this. We don't use it. Being blocked
    means the source doesn't want automated access: find an API or drop the source.

## 3. Gaps found in `collectors/client.py` (reproduced 2026-11-21)

Owned by the Researcher. Reported to them, not changed.

| # | Gap | Reproduced | Smallest fix |
|---|---|---|---|
| 1 | `usage.json` and cache files are written in place. A kill mid-write leaves invalid JSON, and every later run fails with `JSONDecodeError`. | yes | write to temp + `os.replace()` |
| 2 | `rate_limited` is sticky forever. One 429 blocks all future runs until the file is edited by hand. | yes | store `paused_until` (from `Retry-After`, else a default) and clear it after |
| 3 | `Retry-After` header is ignored. | by reading | parse it on 429 |
| 4 | Throttle `_last` is per process. Two bot-started jobs each run at RKD_RPS. | by reading | use SQLite `api_usage`, or keep one collector job at a time |
| 5 | Budget/usage duplicated: JSON file here, `api_usage` table in `ecosystem/tasks.py`. | by reading | one mechanism (SQLite) |
| 6 | No TTL: fine for immutable research data, wrong for live tracking (the docstring already warns). | by reading | add a `max_age` parameter for live calls |
| 7 | No retry on 5xx/timeouts (deliberate "nothing retries" rule). | by reading | user/Researcher decision: allow bounded backoff for transient errors only |

## Sources (retrieved 2026-11-21)

- https://docs.scrapy.org/en/latest/topics/architecture.html
- https://docs.scrapy.org/en/latest/topics/autothrottle.html
- https://crawlee.dev/python/docs/next/concepts/architecture-overview
- https://crawlee.dev/python/docs/next/concepts/requests
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Conditional_requests
- `collectors/client.py` at commit on branch `research/study1-deployer-hold`

Not verified: the retry and resume mechanics inside Crawlee (the architecture page doesn't
describe them), and which of our sources send `ETag`/`Last-Modified` (check per source before relying on 304s).
