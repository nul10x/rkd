"""Study 7 candle fill (KR-000068 continuation): free GeckoTerminal 1-minute candles for capped tokens' main pools.
Usage: python3 -m collectors.study7_candles DAY [DAY ...] [--limit N]. Env: RKD_USAGE, RKD_CALL_BUDGET."""
import json
import sys

from collectors import client
from collectors.study7 import history, sample
from research.study7_parse import main_pool, trade_events

GT = "https://api.geckoterminal.com/api/v2"


def candle_path(pool, t0):
    return "/networks/solana/pools/{}/ohlcv/minute?aggregate=1&before_timestamp={}&limit=70&currency=token&token=base".format(pool, t0 + 3660)


def capped(day):
    by, groups, _ = sample(day)
    for g, ms in groups.items():
        for m in ms:
            txs, done, _ = history(by[m], offline=True)
            if not done:
                yield g, m, by[m], main_pool([x for e in txs for x in trade_events(e, m)])


def fetch(pool, t0):
    p = candle_path(pool, t0)
    return client.cached("geckoterminal", {"study7_candles": [pool, t0]}, GT + p, None, "ohlcv/minute")


def main():
    args = sys.argv[1:]
    lim = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    days = [a for a in args if a.startswith("20")]
    for d in days:
        for i, (g, m, l, pool) in enumerate(capped(d)):
            if lim is not None and i >= lim:
                break
            if not pool:
                print(d, g, m[:8], "no pool", flush=True)
                continue
            r = fetch(pool, l["t0"])
            c = ((r.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            inside = [x for x in c if l["t0"] <= x[0] <= l["t0"] + 3600]
            print(d, g, m[:8], "candles", len(c), "in_hour", len(inside), "calls", client.calls_used(), flush=True)


if __name__ == "__main__":
    main()
