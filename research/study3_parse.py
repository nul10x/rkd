"""Study 3 parsers (pure functions, no network). See Logbook KR-000016 for the definitions."""
from research.pump import account_keys

SUPPLY_RAW = 10 ** 15  # 1e9 tokens x 1e6 (Pump.fun mints use 6 decimals)


def balances(tx, mint, which):
    """{owner: raw amount} for `mint` in pre/postTokenBalances."""
    out = {}
    for b in (tx.get("meta") or {}).get(which) or []:
        if b["mint"] == mint and b.get("owner"):
            out[b["owner"]] = out.get(b["owner"], 0) + int(b["uiTokenAmount"]["amount"])
    return out


def deltas(tx, mint):
    pre, post = balances(tx, mint, "preTokenBalances"), balances(tx, mint, "postTokenBalances")
    return {o: post.get(o, 0) - pre.get(o, 0) for o in set(pre) | set(post) if post.get(o, 0) != pre.get(o, 0)}


def curve_owner(create_tx, mint):
    """The bonding curve holds the unsold supply after the create tx: the largest post balance."""
    post = balances(create_tx, mint, "postTokenBalances")
    return max(post, key=post.get) if post else None


def ordered(txs):
    return sorted(txs, key=lambda e: (e["slot"], e.get("transactionIndex", e.get("index", 0))))


def block0(txs, launch):
    """block0_share (% of supply) bought in the create slot by owners other than deployer and curve,
    plus buyer count and whether the create tx was in the page. txs: mint txs, asc."""
    mint, dev, slot = launch["mint"], launch["deployer"], launch["slot"]
    create = next((e for e in txs if e["transaction"]["signatures"][0] == launch["signature"]), None)
    if create is None:
        return {"create_found": False}
    curve = curve_owner(create, mint)
    net, senders, n_tx, curve_out = {}, set(), 0, 0
    for e in txs:
        if e["slot"] != slot or e is create:
            continue
        n_tx += 1
        for o, d in deltas(e, mint).items():
            net[o] = net.get(o, 0) + d
            if d < 0:
                senders.add(o)
            if o == curve and d < 0:
                curve_out -= d
    # Pilot fix (2026-11-21): a token can graduate inside its creation slot; the new pool then receives the
    # curve's remaining tokens and sells them on. Owners that send tokens anywhere in the slot (pools, routers,
    # buy-and-dump wallets) are excluded, so only net receivers count as block-0 buyers.
    buyers = {o: d for o, d in net.items() if d > 0 and o not in (dev, curve) and o not in senders}
    got = sum(buyers.values())
    migrated = any("Instruction: Migrate" in l for e in txs if e["slot"] == slot
                   for l in ((e.get("meta") or {}).get("logMessages") or []))
    return {"create_found": True, "curve_owner": curve, "block0_share": 100.0 * got / SUPPLY_RAW,
            "block0_buyers": len(buyers), "block0_txs": n_tx, "curve_out_share": 100.0 * curve_out / SUPPLY_RAW,
            "graduated_in_block0": migrated}


def dev_exit(txs, launch, horizon):
    """Seconds from t0 until the deployer's balance first falls to <= 1% of its running maximum,
    using only txs with blockTime <= t0 + horizon. None = no exit seen in the window."""
    mint, dev, t0 = launch["mint"], launch["deployer"], launch["t0"]
    bal, peak = 0, 0
    for e in ordered(txs):
        if e["blockTime"] > t0 + horizon:
            break
        d = deltas(e, mint).get(dev)
        if d is None:
            continue
        bal += d
        peak = max(peak, bal)
        if peak > 0 and bal <= 0.01 * peak:
            return e["blockTime"] - t0
    return None


def pool_state(tx, pool, mint, wsol):
    """(sol_reserve, token_reserve) in UI units from the pool vault post-balances (owner = pool)."""
    sol = tok = None
    for b in (tx.get("meta") or {}).get("postTokenBalances") or []:
        if b.get("owner") != pool:
            continue
        amt = float(b["uiTokenAmount"]["uiAmountString"] or 0)
        if b["mint"] == wsol:
            sol = amt
        elif b["mint"] == mint:
            tok = amt
    return sol, tok


def latest_state(txs_desc, pool, mint, wsol):
    """Reserves from the most recent tx that shows both vaults (pilot: arbitrage txs can show only the SOL vault)."""
    for e in txs_desc:
        s, t = pool_state(e, pool, mint, wsol)
        if s is not None and t:
            return s, t, e["blockTime"]
    return None, None, None


def sol_volume(tx, pool, wsol):
    """|change| of the pool's WSOL vault in this tx (SOL)."""
    pre = sum(float(b["uiTokenAmount"]["uiAmountString"] or 0) for b in (tx["meta"].get("preTokenBalances") or [])
              if b.get("owner") == pool and b["mint"] == wsol)
    post = sum(float(b["uiTokenAmount"]["uiAmountString"] or 0) for b in (tx["meta"].get("postTokenBalances") or [])
               if b.get("owner") == pool and b["mint"] == wsol)
    return abs(post - pre)


def fee_payer(tx):
    return account_keys(tx)[0]
