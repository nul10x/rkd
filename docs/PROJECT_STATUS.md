# Project status

## Cancelled / archived

- **3D animation / animation-production project: CANCELLED 2026-11-21.** Removed from the roadmap. No more animation tooling, pipelines or research.
  Nothing was deleted or uninstalled. (Manim and that project's files were not found on this Mac; any on the phone are left untouched.)

## Log

### 2026-11-21: Phases 1–3 (core)
- Done: audited the Mac (see ARCHITECTURE §1). Hermes is not installed here.
- Done: schema, DB layer, Logbook, task queue with budgets, rkd/1 protocol, CLI.
- Tested: 15 unit tests pass, covering save, search, FTS-safe queries, versioned updates, evidence gate, no-delete, exact and near duplicates, contradictions, stale, restart persistence, message round trip, budgets, provider caps.
- Not done: phone audit, Researcher, Builder, coordinator, backup/export.

## Phone audit commands (run in Termux/Ubuntu)

```bash
uname -a; free -m; df -h ~; python3 --version
python3 -c "import sqlite3;c=sqlite3.connect(':memory:');c.execute('create virtual table t using fts5(x)');print('FTS5 ok')"
which hermes && hermes --version; ls ~/.hermes 2>/dev/null; git --version
```

## Next task

Phase 4 first study: "How long do deployer wallets hold their supply after liquidity is added, and does hold time differ between tokens that survive 7 days and those that don't?" Budget: ≤ 2 LLM requests, ≤ 500 API calls, launches sampled by launch date.
