"""Study 7 infographics. Run with ~/.rkd-analysis/bin/python -m research.study7_charts (reads the stored dataset only)."""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

ROOT = "/Users/null/Documents/Projects/null/data/datasets/study7_first_hour"
DAY = "2026-11-11"
LAUNCH = 30 / 1.073e9
COL = {"graduate": "#2a78d6", "active_non_graduate": "#eb6834"}
NAME = {"graduate": "Graduated", "active_non_graduate": "Active, did not graduate"}
INK, MUTED, GRID, BG = "#1f1f1d", "#6b6a63", "#e6e5e0", "#fcfcfb"
T = np.arange(0, 3605, 5)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": .7, "figure.facecolor": BG, "axes.facecolor": BG})


def load():
    tr = pl.read_csv(os.path.join(ROOT, "trades_{}.csv.gz".format(DAY)), schema_overrides={"tx_index": pl.Int64})
    meta = {r["mint"]: r for r in csv.DictReader(open(os.path.join(ROOT, "exports", "study7_{}_tokens.csv".format(DAY))))}
    return tr.filter(pl.col("is_main_market")).sort(["mint", "slot", "tx_index"]), meta


def build(tr, meta):
    P, V, N, L, BUY, SELL, groups, mints = [], [], [], [], [], [], [], []
    for (m,), d in tr.group_by(["mint"], maintain_order=True):
        cov = float(meta[m]["covered_s"])
        t = d["t_sec"].to_numpy().astype(float)
        p, liq = d["price_sol"].to_numpy().astype(float), d["liquidity_sol"].to_numpy().astype(float)
        sol = np.nan_to_num(d["quote_sol"].to_numpy().astype(float))
        buy = (d["side"] == "buy").to_numpy()
        ok = ~np.isnan(p)
        idx = np.searchsorted(t[ok], T, side="right") - 1
        pr = np.where(idx >= 0, p[ok][np.clip(idx, 0, None)], LAUNCH) / LAUNCH
        lq = np.where(idx >= 0, liq[ok][np.clip(idx, 0, None)], 0.0)
        cut = T > cov
        pr, lq = pr.astype(float), lq.astype(float)
        pr[cut], lq[cut] = np.nan, np.nan
        j = np.searchsorted(t, T, side="right")
        cv = np.r_[0, np.cumsum(sol)][j].astype(float)
        seen, first = set(), []
        for u, x in zip(d["user"].to_list(), t):
            if u not in seen:
                seen.add(u)
                first.append(x)
        nt = np.searchsorted(np.array(first), T, side="right").astype(float)
        cv[cut], nt[cut] = np.nan, np.nan
        cb, cs = np.r_[0, np.cumsum(sol * buy)][j].astype(float), np.r_[0, np.cumsum(sol * ~buy)][j].astype(float)
        cb[cut], cs[cut] = np.nan, np.nan
        P.append(pr); V.append(cv); N.append(nt); L.append(lq); BUY.append(cb); SELL.append(cs)
        groups.append(meta[m]["group"]); mints.append(m)
    return {k: np.array(v) for k, v in zip("PVNLBS", (P, V, N, L, BUY, SELL))}, np.array(groups), mints


def med(a):
    n = np.sum(~np.isnan(a), axis=0)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m, lo, hi = np.nanmedian(a, 0), np.nanpercentile(a, 25, 0), np.nanpercentile(a, 75, 0)
    for x in (m, lo, hi):
        x[n < 10] = np.nan
    return m, lo, hi, n


def band(ax, x, a, g, fill=True):
    m, lo, hi, _ = med(a)
    if fill:
        ax.fill_between(x, lo, hi, color=COL[g], alpha=.14, lw=0)
    ax.plot(x, m, color=COL[g], lw=2, label=NAME[g])


def minutes(ax, mx):
    ax.set_xlim(0, mx)
    ax.set_xlabel("Minutes after launch")


def active_90(tr):
    r = []
    for _, x in tr.filter(pl.col("group") == "active_non_graduate").group_by(["mint"], maintain_order=True):
        t, s = x["t_sec"].to_numpy(), np.nan_to_num(x["quote_sol"].to_numpy().astype(float))
        cs = np.cumsum(s)
        r.append(float(t[np.searchsorted(cs, .9 * cs[-1])]))
    return {"n": len(r), "median_min": round(float(np.median(r)) / 60, 2), "p25": round(float(np.percentile(r, 25)) / 60, 2),
            "p75": round(float(np.percentile(r, 75)) / 60, 2), "within_5m": int(sum(v <= 300 for v in r))}


def main():
    tr, meta = load()
    D, grp, mints = build(tr, meta)
    stats = json.load(open(os.path.join(ROOT, "exports", "study7_{}_stats.json".format(DAY))))
    x = T / 60
    fig = plt.figure(figsize=(17, 21))
    gs = fig.add_gridspec(5, 3, left=.055, right=.975, top=.885, bottom=.055, hspace=.46, wspace=.2)
    fig.text(.055, .965, "Failed launches are usually over in about two minutes", fontsize=25, weight="bold", color=INK)
    fig.text(.055, .94, "First hour of 50 SOL-paired Pump.fun launches from 2026-11-11: 25 graduated, 25 active but did not graduate", fontsize=13, color=MUTED)
    fig.text(.055, .92, "Lines are medians, bands the middle 50%. A line stops when fewer than 10 tokens have data, which cuts graduates at about 15 minutes. Research, not a trade signal.", fontsize=11, color=MUTED)
    for c, (mx, title) in enumerate(((5, "First 5 minutes"), (30, "First 30 minutes"), (60, "Full hour"))):
        ax = fig.add_subplot(gs[0, c])
        for g in COL:
            band(ax, x, D["P"][grp == g], g)
        ax.axhline(1, color=MUTED, lw=1, ls="--")
        ax.set_yscale("log"); ax.set_yticks([.25, .5, 1, 2, 4, 8, 16]); ax.set_yticklabels(["0.25×", "0.5×", "1×", "2×", "4×", "8×", "16×"])
        ax.set_ylim(.2, 24); minutes(ax, mx); ax.set_title("Price vs launch · " + title, loc="left", weight="bold", color=INK)
        if c == 0:
            ax.legend(frameon=False, loc="upper right")
    specs = (("V", "Cumulative volume (SOL)", True), ("N", "Unique traders so far", True), ("L", "Liquidity in curve or pool (SOL)", False))
    for c, (k, title, lg) in enumerate(specs):
        ax = fig.add_subplot(gs[1, c])
        for g in COL:
            band(ax, x, D[k][grp == g], g)
        if lg:
            ax.set_yscale("symlog", linthresh=1)
        minutes(ax, 60); ax.set_title(title, loc="left", weight="bold", color=INK)
    ax = fig.add_subplot(gs[2, 0])
    step = 12
    for g in COL:
        b, s = D["B"][grp == g], D["S"][grp == g]
        db, ds = np.diff(b[:, ::step], axis=1), np.diff(s[:, ::step], axis=1)
        tb, ts = np.nansum(db, 0), np.nansum(ds, 0)
        with np.errstate(all="ignore"):
            share = 100 * tb / (tb + ts)
        share[(tb + ts) < 5] = np.nan
        ax.plot(x[::step][1:], share, color=COL[g], lw=2, marker="o", ms=3, label=NAME[g])
    ax.axhline(50, color=MUTED, lw=1, ls="--"); ax.set_ylim(0, 100); minutes(ax, 15)
    ax.set_title("Buy share of SOL volume, per minute (%)", loc="left", weight="bold", color=INK)
    ax = fig.add_subplot(gs[2, 1])
    for g in COL:
        p = D["P"][grp == g][:, ::step]
        with np.errstate(all="ignore"):
            r = np.abs(np.diff(np.log(p), axis=1)) * 100
        ax.plot(x[::step][1:], med(r)[0], color=COL[g], lw=2, label=NAME[g])
    minutes(ax, 15); ax.set_title("Typical 1-minute price move (abs %, median)", loc="left", weight="bold", color=INK)
    ax = fig.add_subplot(gs[2, 2])
    w = .36
    cs = ("5m", "30m", "60m")
    for i, g in enumerate(COL):
        vals = [stats["by_group"][g][c]["insider_sold_pct"].get("median") or 0 for c in cs]
        ns = [stats["by_group"][g][c]["insider_sold_pct"].get("n") for c in cs]
        bars = ax.bar(np.arange(3) + (i - .5) * w, vals, w * .9, color=COL[g], label=NAME[g])
        for b, v, n in zip(bars, vals, ns):
            ax.text(b.get_x() + b.get_width() / 2, v + 2, "{:.0f}%\nn={}".format(v, n), ha="center", fontsize=8.5, color=INK)
    ax.set_xticks(range(3)); ax.set_xticklabels(["5 min", "30 min", "60 min"]); ax.set_ylim(0, 125); ax.grid(axis="x", visible=False)
    ax.set_title("Bundle + sniper tokens already sold", loc="left", weight="bold", color=INK)
    ax = fig.add_subplot(gs[3, 0])
    data = []
    for g in COL:
        data.append([float(meta[m]["bundle_pct"]) for m, q in zip(mints, grp) if q == g])
    bp = ax.boxplot(data, orientation="horizontal", widths=.5, patch_artist=True, medianprops={"color": INK})
    for p, g in zip(bp["boxes"], COL):
        p.set_facecolor(COL[g]); p.set_alpha(.5); p.set_edgecolor(COL[g])
    ax.set_yticklabels(["Graduated", "Active"]); ax.set_xlabel("% of supply bought in the launch block")
    ax.set_title("Bundle size", loc="left", weight="bold", color=INK); ax.grid(axis="y", visible=False)
    ax = fig.add_subplot(gs[3, 1])
    data = [[float(meta[m]["sniper_pct"]) for m, q in zip(mints, grp) if q == g] for g in COL]
    bp = ax.boxplot(data, orientation="horizontal", widths=.5, patch_artist=True, medianprops={"color": INK})
    for p, g in zip(bp["boxes"], COL):
        p.set_facecolor(COL[g]); p.set_alpha(.5); p.set_edgecolor(COL[g])
    ax.set_yticklabels(["Graduated", "Active"]); ax.set_xlabel("% of supply bought by snipers (slots 1-10)")
    ax.set_title("Sniper size", loc="left", weight="bold", color=INK); ax.grid(axis="y", visible=False)
    ax = fig.add_subplot(gs[3, 2])
    sc = stats["shape_counts"]
    names = [("no_pump", "No 3× pump"), ("pump_and_dump", "Pump, then fell 50%+"), ("pump_and_hold", "Pump, held")]
    vals = [sc[k]["n"] for k, _ in names]
    ax.barh([n for _, n in names][::-1], vals[::-1], color="#2a78d6", height=.55)
    for i, (k, _) in enumerate(names[::-1]):
        ax.text(sc[k]["n"] + .3, i, "{} of {} ({:.0f}%, CI {:.0f}-{:.0f}%)".format(sc[k]["n"], stats["with_full_60m"], sc[k]["pct"], *sc[k]["ci95"]), va="center", fontsize=9, color=INK)
    ax.set_xlim(0, 40); ax.grid(axis="y", visible=False); ax.set_xlabel("Tokens with full 60-minute coverage")
    ax.set_title("Chart shape after one hour", loc="left", weight="bold", color=INK)
    ax = fig.add_subplot(gs[4, :]); ax.axis("off")
    rows, labels = [], [("mc_sol", "Market cap (SOL)"), ("liq_sol", "Liquidity (SOL)"), ("volume_sol", "Volume so far (SOL)"), ("traders", "Traders so far"), ("drawdown_pct", "Below peak (%)"), ("sell_share", "Sell share of volume")]
    for f, lab in labels:
        row = [lab]
        for g in COL:
            for c in cs:
                d = stats["by_group"][g][c][f]
                v = d.get("median")
                row.append("—" if v is None else ("{:.0f}%".format(100 * v) if f == "sell_share" else "{:,.1f}".format(v)))
        rows.append(row)
    row = ["Tokens measured (n)"]
    for g in COL:
        for c in cs:
            row.append(str(stats["by_group"][g][c]["index"].get("n")))
    rows.append(row)
    head = ["Median at checkpoint"] + ["Graduated {}".format(c) for c in cs] + ["Active {}".format(c) for c in cs]
    tb = ax.table(cellText=rows, colLabels=head, loc="center", cellLoc="center", colWidths=[.22] + [.13] * 6)
    tb.auto_set_font_size(False); tb.set_fontsize(10); tb.scale(1, 1.75)
    for (r, c), cell in tb.get_celld().items():
        cell.set_edgecolor(GRID); cell.set_facecolor(BG)
        if r == 0:
            cell.set_text_props(weight="bold", color=INK)
    fig.text(.055, .025, "Caution: only 5 of 25 graduates have 30 and 60 minute data, and they lean toward quieter coins. One launch day, not confirmed on a holdout. Source: Solana on-chain trades via Helius; plan KR-000068.", fontsize=10, color=MUTED)
    os.makedirs(os.path.join(ROOT, "charts"), exist_ok=True)
    fig.savefig(os.path.join(ROOT, "charts", "first_hour_infographic.png"), dpi=130); plt.close(fig)
    order = sorted(range(len(mints)), key=lambda i: (grp[i] != "graduate", -np.nanmax(D["P"][i])))
    fig, axes = plt.subplots(10, 5, figsize=(18, 24), sharex=True, sharey=True)
    fig.subplots_adjust(left=.04, right=.985, top=.93, bottom=.03, hspace=.28, wspace=.07)
    fig.text(.04, .968, "All 50 first-hour charts", fontsize=23, weight="bold", color=INK)
    fig.text(.04, .948, "Price vs launch on a log scale. Blue graduated, orange did not. Sorted by peak within each group. A line that stops is where saved data ends.", fontsize=12, color=MUTED)
    for ax, i in zip(axes.flat, order):
        ax.plot(x, D["P"][i], color=COL[grp[i]], lw=1.2); ax.axhline(1, color=MUTED, lw=.6, ls="--"); ax.set_yscale("log")
        ax.set_ylim(.05, 200); ax.set_xlim(0, 60); ax.set_xticks([5, 30, 60]); ax.set_yticks([.1, 1, 10, 100]); ax.set_yticklabels(["0.1×", "1×", "10×", "100×"])
        ax.minorticks_off(); ax.set_title("{}… peak {:.1f}×".format(mints[i][:5], np.nanmax(D["P"][i])), fontsize=8.5, color=INK, loc="left", pad=2)
    fig.savefig(os.path.join(ROOT, "charts", "all_50_charts.png"), dpi=110); plt.close(fig)
    pk = np.nanmax(D["P"], 1)
    pk_t = T[np.nanargmax(D["P"], 1)] / 60
    print(json.dumps({"tokens": len(mints), "peak_within_5m_all": int((pk_t <= 5).sum()),
                      "peak_within_5m_complete": int(sum(pk_t[i] <= 5 for i, m in enumerate(mints) if meta[m]["complete"] == "True")),
                      "complete": sum(meta[m]["complete"] == "True" for m in mints),
                      "below_launch_at_60": int(np.sum(D["P"][:, -1] < 1)), "active_min_to_90pct_volume": active_90(tr), "n_at_60": int(np.sum(~np.isnan(D["P"][:, -1])))}))


if __name__ == "__main__":
    main()
