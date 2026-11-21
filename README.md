# RKD: Research, Knowledge & Development Ecosystem

Three agents — **Researcher → Logbook → Builder** — that share one SQLite knowledge base.
Python 3.8+ standard library only. Runs the same on macOS, Linux, or Termux/Ubuntu on Android.

Status: Phase 2 (foundation) and Phase 3 core (Logbook) are built and tested. See `docs/PROJECT_STATUS.md`.

## Use

```bash
python3 -m unittest discover -s tests -t . -v          # 15 tests
python3 -m ecosystem.cli stats
python3 -m ecosystem.cli search "developer wallet" --status validated
python3 -m ecosystem.cli get KR-000001
python3 -m ecosystem.cli history KR-000001
python3 -m ecosystem.cli stale --days 30
echo '<rkd/1 JSON message>' | python3 -m ecosystem.cli msg
```

The database lives at `data/logbook.db`. Set `RKD_DB=/path/to.db` to use another file.
On Android keep the repo and database under Termux `$HOME`, not `/sdcard` or `~/storage/shared`: shared storage cannot use WAL, so the database falls back to the slower rollback journal there.

## Layout

```
ecosystem/   schema.sql, db.py, logbook.py, protocol.py, tasks.py, cli.py
config/      limits.json   (task budgets, caps, provider daily limits)
tests/       test_foundation.py
docs/        ARCHITECTURE.md, PROJECT_STATUS.md
data/        logbook.db (git-ignored), exports/
```

Planned: `agents/researcher/`, `agents/builder/`, `collectors/` (read-only market data), `tools/` (Builder output).

## Safety rules built in

- Records cannot be deleted (DB trigger). Every update first saves the previous version.
- `historically_supported` and `validated` are refused unless methodology, sample size, evidence, limitations and a source are present.
- Every task needs an objective and a done condition. A task pauses when it goes over its budget, and its progress is kept.
- Provider daily caps and rate-limit pauses are enforced. Nothing retries by itself.
- No trading, no wallet keys and no secrets anywhere in this repo.
