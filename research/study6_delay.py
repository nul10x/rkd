"""Study 6: price drift against a delayed buyer on the Pump.fun curve (plan KR record 'Study 6 plan').

Offline: reads cached Study 3 first-hour mint pages only, makes no API calls.
Price = virtual quote / virtual token reserves from each on-chain TradeEvent. Deviation from the plan: the\nplanned constant-curve price failed its check (49% of trades matched) because launches do not share one curve.
Usage: python3 -m research.study6_delay DAY [--check]
"""
import collections
import glob
import json
import os
import random
import statistics
import struct
import sys

from collectors.study3 import sample
from research.study3_parse import ordered

RAW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
EVENT_PREFIX = bytes.fromhex("e445a52e51cb9a1dbddb7fd34ee661ee")  # Anchor event CPI tag + TradeEvent
ANCHORS, DELAYS = (25, 150), (1, 2, 5, 10, 25, 75)
FEE_BREAKEVEN = 2.548


def b58(text):
    n = 0
    for c in text:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(text) - len(text.lstrip("1"))) + raw


def trade_events(tx, mint):
    """Pump.fun TradeEvents for `mint` in tx order: exact reserves after each trade."""
    want, out = b58(mint), []
    for group in (tx.get("meta") or {}).get("innerInstructions") or []:
        for ins in group.get("instructions") or []:
            if ins.get("programId") != PUMP or "data" not in ins:
                continue
            try:
                d = b58(ins["data"])
            except ValueError:
                continue
            if d[:16] != EVENT_PREFIX or len(d) < 137 or d[16:48] != want:
                continue
            b = d[16:]
            quote, tok = struct.unpack("<QQ", b[32:48])
            vs, vt, rs, rt = struct.unpack("<QQQQ", b[89:121])
            if vs and vt and tok:
                out.append({"buy": bool(b[48]), "quote": quote, "tok": tok, "vs": vs, "vt": vt, "rs": rs, "rt": rt})
    return out


def pages(wanted):
    out = {}
    for f in glob.glob(os.path.join(RAW, "helius", "*.json")):
        try:
            o = json.load(open(f))
            q = o["request"]
            if q.get("method") != "getTransactionsForAddress":
                continue
            a, c = q["params"][0], q["params"][1]
            if a not in wanted or c.get("sortOrder") != "asc" or c.get("limit") != 100 or "paginationToken" in c:
                continue
            fl = c.get("filters") or {}
            bt = fl.get("blockTime") or {}
            if fl.get("status") != "succeeded" or bt.get("gte") != wanted[a]["t0"] or bt.get("lte") != wanted[a]["t0"] + 3600:
                continue
            out[a] = o["response"]["result"]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def curve_path(page, l):
    """[(slot, price, is_buy, migrated)] from on-chain TradeEvents, in order, ending at any Migrate."""
    txs = ordered(page.get("data") or [])
    if not any(e["transaction"]["signatures"][0] == l["signature"] for e in txs):
        return None, txs
    path = []
    for e in txs:
        if any("Instruction: Migrate" in x for x in (e.get("meta") or {}).get("logMessages") or []):
            path.append((e["slot"], None, False, True))
            break
        for ev in trade_events(e, l["mint"]):
            path.append((e["slot"], ev["vs"] / ev["vt"], ev["buy"], False))
    return path, txs


def drifts(path, full, launch_slot, anchor):
    i = next((j for j, x in enumerate(path) if x[2] and x[0] >= launch_slot + anchor), None)
    if i is None or path[i][1] is None:
        return None
    s, p0 = path[i][0], path[i][1]
    last = path[-1][0]
    out = {}
    for d in DELAYS:
        window = [x for x in path[i + 1:] if x[0] <= s + d]
        if any(x[3] for x in window) or (full and last < s + d):
            out[d] = None
            continue
        ps = [x[1] for x in window if x[1] is not None]
        out[d] = 100.0 * ((ps[-1] if ps else p0) / p0 - 1)
    return out


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))]


def boot(v, fn, n=2000, seed=6):
    r = random.Random(seed)
    b = sorted(fn([r.choice(v) for _ in v]) for _ in range(n))
    return round(b[int(.025 * n)], 3), round(b[int(.975 * n)], 3)


def summary(v):
    if not v:
        return {"n": 0}
    return {"n": len(v), "median": round(statistics.median(v), 3), "median_ci": boot(v, statistics.median),
            "mean": round(statistics.mean(v), 3), "mean_ci": boot(v, statistics.mean), "p10": round(pct(v, .1), 3),
            "p90": round(pct(v, .9), 3), "p90_ci": boot(v, lambda x: pct(x, .9)),
            "share_adverse_gt_fee_breakeven": round(sum(x > FEE_BREAKEVEN for x in v) / len(v), 4),
            "share_zero": round(sum(x == 0 for x in v) / len(v), 4)}


def check(rows):
    """Does the reserve price after one trade predict the fill rate of the next small trade (<0.5% of reserves)?
    Compared with the published constant curve (30 SOL + real SOL). Also counts reserve jumps a trade cannot explain."""
    err_event, err_constant, jumps = [], [], []
    trades, jump_mints, mints = 0, set(), set()
    for page, l in rows:
        prev = None
        for e in ordered(page.get("data") or []):
            for ev in trade_events(e, l["mint"]):
                mints.add(l["mint"])
                if prev:
                    trades += 1
                    if ev["tok"] < .005 * ev["vt"]:
                        rate = ev["quote"] / ev["tok"]
                        err_event.append(abs(rate / (prev["vs"] / prev["vt"]) - 1))
                        err_constant.append(abs(rate / ((30e9 + prev["rs"]) / prev["vt"]) - 1))
                    change = (ev["vs"] - (prev["vs"] + (1 if ev["buy"] else -1) * ev["quote"])) / prev["vs"]
                    if abs(change) > .01:
                        jumps.append(change)
                        jump_mints.add(l["mint"])
                prev = ev
    share = lambda v: round(sum(x <= .02 for x in v) / len(v), 4) if v else None
    return {"next_trade_n": len(err_event), "event_price_within_2pct": share(err_event),
            "event_price_median_abs_err_pct": round(100 * statistics.median(err_event), 3) if err_event else None,
            "constant_curve_within_2pct": share(err_constant),
            "constant_curve_median_abs_err_pct": round(100 * statistics.median(err_constant), 3) if err_constant else None,
            "consecutive_trades": trades, "reserve_jumps_gt_1pct": len(jumps), "mints_traded": len(mints),
            "mints_with_jump": len(jump_mints),
            "jump_pct_p25_p50_p75": [round(100 * pct(jumps, q), 2) for q in (.25, .5, .75)] if jumps else None}


def run(day, do_check):
    by, grads, non, _ = sample(day)
    groups = {"graduate": grads, "non_graduate": non}
    wanted = {m: by[m] for ms in groups.values() for m in ms}
    got = pages(wanted)
    res = {"day": day, "pages": len(got), "sampled": len(wanted), "groups": {}}
    chk = []
    for g, ms in groups.items():
        cells = {a: {d: [] for d in DELAYS} for a in ANCHORS}
        cnt = {a: {"no_signal": 0, "censored": {d: 0 for d in DELAYS}} for a in ANCHORS}
        miss = 0
        for m in ms:
            if m not in got:
                miss += 1
                continue
            path, txs = curve_path(got[m], by[m])
            if path is None:
                miss += 1
                continue
            chk.append((got[m], by[m]))
            full = len(txs) >= 100
            for a in ANCHORS:
                r = drifts(path, full, by[m]["slot"], a)
                if r is None:
                    cnt[a]["no_signal"] += 1
                    continue
                for d, x in r.items():
                    if x is None:
                        cnt[a]["censored"][d] += 1
                    else:
                        cells[a][d].append(x)
        res["groups"][g] = {"tokens": len(ms), "missing_page_or_create": miss, "anchors": {
            str(a): {"no_signal": cnt[a]["no_signal"], "censored": {str(d): c for d, c in cnt[a]["censored"].items()},
                     "drift_pct": {str(d): summary(cells[a][d]) for d in DELAYS}} for a in ANCHORS}}
        s = res["groups"][g]["anchors"]["25"]["drift_pct"]["5"]
        res["groups"][g]["H1_median_gt_0"] = bool(s.get("n") and s["median_ci"][0] > 0)
        res["groups"][g]["H2_p90_gt_breakeven"] = bool(s.get("n") and s["p90"] > FEE_BREAKEVEN)
    if do_check:
        res["price_check"] = check(chk)
    os.makedirs(os.path.join(os.path.dirname(RAW), "exports"), exist_ok=True)
    with open(os.path.join(os.path.dirname(RAW), "exports", "study6_{}_stats.json".format(day)), "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    return res


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1], "--check" in sys.argv), indent=1, sort_keys=True))
