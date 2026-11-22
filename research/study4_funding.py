"""Study 4 parsers (pure functions, no network). Definitions: Logbook plan KR-000039.

A wallet page is the list of txs returned by getTransactionsForAddress for that wallet in [t0 - 7 d, t0].
"""
from research.pump import account_keys, all_instructions

MIN_LAMPORTS = 10_000_000  # 0.01 SOL; smaller transfers are dust (KR-000039)
HUB_MIN_LAUNCHES = 5
PAGE_LIMIT = 100
_KINDS = {"transfer": "destination", "transferWithSeed": "destination",
          "createAccount": "newAccount", "createAccountWithSeed": "newAccount"}


def sol_transfers(tx, min_lamports=MIN_LAMPORTS):
    """[(source, destination, lamports)] from parsed system-program instructions, top-level and inner."""
    out = []
    for ins in all_instructions(tx):
        if ins.get("program") != "system":
            continue
        p = ins.get("parsed")
        if not isinstance(p, dict) or p.get("type") not in _KINDS:
            continue
        info = p.get("info") or {}
        src, dst, lam = info.get("source"), info.get(_KINDS[p["type"]]), int(info.get("lamports") or 0)
        if src and dst and src != dst and lam >= min_lamports:
            out.append((src, dst, lam))
    return out


def delta_flows(tx, w, min_lamports=MIN_LAMPORTS):
    """Balance-change rule (pilot amendment, KR-000039): SOL also moves through wrapped-SOL closes and
    non-system programs, which sol_transfers misses. If w gains >= min_lamports in a tx paid by someone
    else, the fee payer funded w. If w paid the tx, every other account that gains >= min_lamports is a recipient."""
    keys = account_keys(tx) if "accountKeys" in tx["transaction"]["message"] else []
    meta = tx.get("meta") or {}
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    if not keys or w not in keys or len(pre) != len(keys) or len(post) != len(keys):
        return set(), set()
    payer, i = keys[0], keys.index(w)
    if payer != w:
        return ({payer} if post[i] - pre[i] >= min_lamports else set()), set()
    return set(), {k for k, a, b in zip(keys, pre, post) if k != w and b - a >= min_lamports}


def flows(txs, w):
    """(funders, recipients) of wallet w: who sent SOL to w, and to whom w sent SOL.
    Union of parsed system transfers and the balance-change rule."""
    fin, fout = set(), set()
    for tx in txs or []:
        for s, d, _ in sol_transfers(tx):
            if d == w:
                fin.add(s)
            if s == w:
                fout.add(d)
        a, b = delta_flows(tx, w)
        fin |= a
        fout |= b
    fin.discard(w)
    fout.discard(w)
    return fin, fout


def hubs(launch_funders, min_launches=HUB_MIN_LAUNCHES):
    """launch_funders: {launch_id: set of funders of its deployer and block-0 buyers}.
    A hub funds wallets of >= min_launches distinct launches (exchanges, bot services)."""
    n = {}
    for fs in launch_funders.values():
        for f in fs:
            n[f] = n.get(f, 0) + 1
    return {f for f, k in n.items() if k >= min_launches}


def classify(dev, dev_page, buyer_pages, hub_set, hubs_in_2hop=True):
    """dev_page: txs of the deployer; buyer_pages: {buyer: txs or None (missing)}.
    Returns per-launch classes and per-buyer link labels (KR-000039 definitions)."""
    f_dev, out_dev = flows(dev_page, dev)
    per, buyer_funders = {}, {}
    for b, txs in sorted(buyer_pages.items()):
        if txs is None:
            per[b] = {"missing": True}
            continue
        f_b, _ = flows(txs, b)
        buyer_funders[b] = f_b
        direct = b in out_dev or dev in f_b or b in f_dev
        mid = (out_dev & f_b) - {dev, b}
        if not hubs_in_2hop:
            mid -= hub_set
        shared = (f_dev & f_b) - hub_set - {dev, b}
        per[b] = {"direct": direct, "two_hop": bool(mid), "shared_funder": bool(shared),
                  "linked": direct or bool(mid) or bool(shared), "busy": len(txs) >= PAGE_LIMIT,
                  "n_txs": len(txs), "n_funders": len(f_b)}
    cnt = {}
    for b, fs in buyer_funders.items():
        for f in fs - hub_set - {dev}:
            cnt[f] = cnt.get(f, 0) + 1
    shared_among_buyers = any(k >= 2 for k in cnt.values())
    b2b = any(b1 in fs for b2, fs in buyer_funders.items() for b1 in buyer_funders if b1 != b2)
    dev_linked = any(v.get("linked") for v in per.values())
    return {"dev_linked": dev_linked,
            "coordinated_not_dev": (not dev_linked) and shared_among_buyers,
            "buyer_to_buyer_funding": b2b,  # exploratory, not in the plan's class definitions
            "dev_page_busy": len(dev_page or []) >= PAGE_LIMIT, "buyers": per}


def launch_funders(dev, dev_page, buyer_pages):
    fs = set(flows(dev_page, dev)[0])
    for b, txs in buyer_pages.items():
        if txs is not None:
            fs |= flows(txs, b)[0]
    return fs
