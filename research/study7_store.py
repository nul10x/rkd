"""Store the Study 7 dataset (plan KR-000068). Offline; never edits data/raw.

Writes to data/datasets/study7_first_hour/ in the main checkout:
  trades_DAY.csv.gz   one row per decoded trade
  manifest.json       every token and raw page, with SHA-256, plus hashes of the files here
  exports/            copies of the stats, token and path files
Usage: python3 -m research.study7_store DAY [DAY ...]
"""
import csv
import gzip
import hashlib
import json
import os
import shutil
import sys

from collectors import client
from collectors.study3 import FULL
from collectors.study7 import PAGE_CAP, sample
from research.study3_parse import ordered
from research.study7_parse import main_pool, trade_events

OUT = os.path.join(os.path.dirname(os.path.realpath(client.RAW)), "datasets", "study7_first_hour")
EXPORTS = os.path.join(os.path.dirname(os.path.realpath(client.RAW)), "exports")
COLS = ("day", "group", "mint", "slot", "tx_index", "block_time", "t_sec", "signature", "venue", "side", "user",
        "quote_sol", "tokens", "price_sol", "liquidity_sol", "pool", "is_main_market")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pages(l):
    """Yield (cache path, result) for each cached page, reading the cache only."""
    flt = {"blockTime": {"gte": l["t0"], "lte": l["t0"] + 3600}, "status": "succeeded"}
    opts, n = dict(FULL, sortOrder="asc", limit=100, filters=flt), 0
    while n < PAGE_CAP:
        path = client._cache_path("helius", {"method": "getTransactionsForAddress", "params": [l["mint"], opts]})
        if not os.path.exists(path):
            yield path, None
            return
        r = json.load(open(path))["response"]["result"]
        yield path, r
        n += 1
        if not r.get("paginationToken"):
            return
        opts = dict(FULL, sortOrder="asc", limit=100, paginationToken=r["paginationToken"], filters=flt)


def store_day(day):
    by, groups, frame = sample(day)
    tokens = []
    path = os.path.join(OUT, "trades_{}.csv.gz".format(day))
    with gzip.GzipFile(path, "wb", mtime=0) as gz:
        import io
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        w = csv.writer(text)
        w.writerow(COLS)
        for g, ms in groups.items():
            for m in ms:
                l, txs, refs, complete = by[m], [], [], False
                for p, r in pages(l):
                    if r is None:
                        refs.append({"file": os.path.basename(p), "missing": True})
                        break
                    refs.append({"file": os.path.basename(p), "sha256": sha(p)})
                    txs += r.get("data") or []
                    complete = not r.get("paginationToken")
                n = 0
                txs = ordered(txs)
                main = main_pool([x for e in txs for x in trade_events(e, m)])
                for e in txs:
                    for x in trade_events(e, m):
                        w.writerow((day, g, m, e["slot"], e.get("transactionIndex", e.get("index")), e["blockTime"],
                                    e["blockTime"] - l["t0"], e["transaction"]["signatures"][0], x["venue"],
                                    "buy" if x["buy"] else "sell", x["user"], x["sol"], x["tok"], x["price"], x["liq"], x.get("pool", ""),
                                    x["venue"] == "curve" or x.get("pool") == main))
                        n += 1
                tokens.append({"mint": m, "group": g, "launch_slot": l["slot"], "t0": l["t0"], "deployer": l["deployer"],
                               "txs": len(txs), "trades": n, "complete_first_hour": complete, "raw_pages": refs})
        text.flush()
        text.detach()
    return {"frame": frame, "tokens": tokens, "trades_file": os.path.basename(path), "trades_sha256": sha(path)}


def main(days):
    os.makedirs(os.path.join(OUT, "exports"), exist_ok=True)
    man = {"study": "Study 7", "plan": "KR-000068", "raw_cache": "data/raw/helius", "columns": COLS, "days": {}}
    for d in days:
        man["days"][d] = store_day(d)
        for kind in ("stats.json", "tokens.csv", "paths.json"):
            f = "study7_{}_{}".format(d, kind)
            if os.path.exists(os.path.join(EXPORTS, f)):
                shutil.copy2(os.path.join(EXPORTS, f), os.path.join(OUT, "exports", f))
    man["exports"] = {f: sha(os.path.join(OUT, "exports", f)) for f in sorted(os.listdir(os.path.join(OUT, "exports")))}
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(man, f, indent=1, sort_keys=True)
    print(json.dumps({d: {"tokens": len(v["tokens"]), "complete": sum(t["complete_first_hour"] for t in v["tokens"]),
                          "trades": sum(t["trades"] for t in v["tokens"]),
                          "missing_pages": sum(1 for t in v["tokens"] for p in t["raw_pages"] if p.get("missing"))}
                      for d, v in man["days"].items()}))


if __name__ == "__main__":
    main(sys.argv[1:])
