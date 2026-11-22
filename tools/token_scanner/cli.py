"""Scan one Solana token: market, holders, mint permissions and Pump.fun launch context.

Usage:
  python3 -m tools.token_scanner.cli <mint> [--text] [--no-launch] [--max-age SECONDS] [--fixtures DIR]

Prints the JSON report (or Discord-ready text with --text) and saves the JSON under
data/exports/token_scanner/. Exit codes: 0 report written (possibly partial; see "missing"),
2 invalid input, 3 nothing could be fetched.

Network goes through collectors/client.py only (throttle, pauses, budget). Calls per scan: 1 DEX Screener
+ 3 Helius (mint, largest accounts, owners) + 1 Helius for the creation page, which is history and
cached forever. Budget: RKD_SCANNER_DAILY_BUDGET calls per UTC day (default 300), counted in
data/raw/usage_token_scanner_<day>.json. Needs HELIUS_API_KEY for the on-chain parts.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from collectors import client
from ecosystem import tasks
from . import token_scanner as ts

ROOT = Path(__file__).resolve().parents[2]
FULL = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}
# Logbook counting (RKD_LOGBOOK_COUNT=1) raises the ecosystem's own budget/pause errors; they stop the run too.
STOP = (client.RateLimited, client.BudgetExceeded, tasks.BudgetExceeded, tasks.ProviderPaused)


class LiveApi:
    """Fresh reads through the shared client. Each method returns client.live()-style dicts."""

    def __init__(self, max_age_s=60):
        self.max_age_s = max_age_s
        day = time.strftime("%Y-%m-%d", time.gmtime())
        client.USAGE = os.path.join(client.RAW, "usage_token_scanner_{}.json".format(day))
        client.BUDGET = int(os.environ.get("RKD_SCANNER_DAILY_BUDGET", "300"))

    def pairs(self, mint):
        return client.dexscreener_token_pairs_live("solana", mint, self.max_age_s)

    def account(self, mint):
        return client.helius_live("getAccountInfo", [mint, {"encoding": "jsonParsed"}], self.max_age_s)

    def largest(self, mint):
        return client.helius_live("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}], self.max_age_s)

    def owners(self, accounts):
        # Token-account owners rarely change; a 1 h reuse window saves calls on repeat scans.
        return client.helius_live("getMultipleAccounts", [accounts, {"encoding": "jsonParsed"}],
                                  max(self.max_age_s, 3600))

    def first_page(self, mint):
        before = client.calls_used()
        resp = client.helius_rpc("getTransactionsForAddress",
                                 [mint, dict(FULL, sortOrder="asc", limit=100, filters={"status": "succeeded"})])
        return {"response": {"result": resp}, "fetched_at": time.time(), "raw_path": None,
                "reused": client.calls_used() == before}


class FixtureApi:
    """Replays saved responses from a directory (tests, offline re-runs). Missing file = ApiError."""

    def __init__(self, d):
        self.d = Path(d)

    def _load(self, name):
        p = self.d / (name + ".json")
        if not p.exists():
            raise client.ApiError("fixture {} missing".format(p.name))
        snap = json.loads(p.read_text(encoding="utf-8"))
        if "error" in snap:
            raise getattr(client, snap["error"]["type"])(snap["error"]["message"])
        return {"response": snap["response"], "fetched_at": snap["fetched_at"], "raw_path": str(p), "reused": False}

    def pairs(self, mint):
        return self._load("pairs")

    def account(self, mint):
        return self._load("account")

    def largest(self, mint):
        return self._load("largest")

    def owners(self, accounts):
        return self._load("owners")

    def first_page(self, mint):
        return self._load("first_page")


def scan(mint, api, now_s, launch=True):
    """Run every read, keep going past single failures, stop all calls on a rate limit or budget stop."""
    got, sources, errors = {}, [], {}
    stopped = [None]

    def step(name, provider, endpoint, fn, *args):
        if stopped[0]:
            errors[name] = "not fetched: run stopped ({})".format(stopped[0])
            return None
        try:
            r = fn(*args)
        except STOP as e:
            stopped[0] = "{}: {}".format(type(e).__name__, e)
            errors[name] = "not fetched: " + stopped[0]
            return None
        except client.ApiError as e:
            msg = str(e)
            if "Too many accounts requested" in msg:
                msg = "the RPC refuses a largest-holders query for tokens with this many holders ({})".format(msg[:120])
            errors[name] = "fetch failed: " + msg
            return None
        except (OSError, ValueError) as e:  # network down, bad JSON
            errors[name] = "fetch failed: {}: {}".format(type(e).__name__, e)
            return None
        sources.append({"provider": provider, "endpoint": endpoint, "fetched_at": r["fetched_at"],
                        "reused": r["reused"], "raw_path": r["raw_path"]})
        return r["response"]

    pairs = step("market", "dexscreener", "token-pairs/v1", api.pairs, mint)
    acct = step("mint", "helius", "getAccountInfo", api.account, mint)
    acct = acct.get("result") if isinstance(acct, dict) else None
    largest = step("holders", "helius", "getTokenLargestAccounts", api.largest, mint)
    largest = ((largest or {}).get("result") or {}).get("value") if largest else None
    owners = None
    if largest:
        o = step("holder_owners", "helius", "getMultipleAccounts", api.owners, [a["address"] for a in largest])
        owners = ((o or {}).get("result") or {}).get("value") if o else None
    first = None
    if launch and ts.is_pump_launch(mint, pairs):
        f = step("launch_context", "helius", "getTransactionsForAddress(asc)", api.first_page, mint)
        first = ((f or {}).get("result") or {}).get("data") if f else None
    if not sources:
        got["nothing"] = True
    report = ts.build_report(mint, now_s, pairs=pairs, mint_acct=acct, largest=largest, owner_accts=owners,
                             first_page=first, sources=sources, errors=errors)
    return report, got.get("nothing", False)


def save(report, out_dir=None):
    d = Path(out_dir or os.environ.get("RKD_EXPORTS") or ROOT / "data" / "exports") / "token_scanner"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "{}_{}.json".format(report["mint"], report["generated_at"])
    client._atomic_write_json(str(p), report, indent=1, sort_keys=True)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tools.token_scanner.cli", description=__doc__.split("\n")[0])
    ap.add_argument("mint")
    ap.add_argument("--text", action="store_true", help="print Discord-ready text instead of JSON")
    ap.add_argument("--no-launch", action="store_true", help="skip the Pump.fun creation-slot read")
    ap.add_argument("--max-age", type=int, default=60, help="reuse snapshots younger than this (s)")
    ap.add_argument("--fixtures", help="replay saved responses from this directory (no network)")
    ap.add_argument("--now", type=float, help=argparse.SUPPRESS)  # fixed clock for tests
    ap.add_argument("--out", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if not ts.valid_mint(a.mint):
        print(json.dumps({"error": "invalid Solana address", "input": a.mint[:60]}), file=sys.stderr)
        return 2
    api = FixtureApi(a.fixtures) if a.fixtures else LiveApi(a.max_age)
    report, nothing = scan(a.mint, api, a.now or time.time(), launch=not a.no_launch)
    path = save(report, a.out)
    sys.stdout.write((ts.render_text(report) if a.text else json.dumps(report, indent=1, sort_keys=True)) + "\n")
    print("saved " + str(path), file=sys.stderr)
    return 3 if nothing else 0


if __name__ == "__main__":
    sys.exit(main())
