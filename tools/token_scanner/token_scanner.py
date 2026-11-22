"""Token scanner: pure analysis of already-fetched responses (no network, no clock).

Every function takes raw provider responses and returns plain dicts. Missing data is reported as
missing (None plus a reason in `missing`), never as zero. Nothing here ranks, scores or advises.
"""
import re

from research.study3_parse import block0, fee_payer, ordered

TOOL = "token_scanner"
VERSION = "0.2.0"
FINDINGS = ["KR-000038", "KR-000026", "KR-000004", "KR-000015", "KR-000022", "KR-000046", "KR-000048"]
RISK_SPEC = "docs/RISK_SIGNALS.md v1 (Researcher, 2026-11-22)"
DISCLAIMER = "Measured facts and labelled risk flags only. Not a rating, not a safety verdict, not advice."

B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SPL_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
PUMP_DEXES = {"pumpfun", "pumpswap"}

# Heuristic thresholds. Not validated by any study (KR-000015); shown so the user can judge.
TOP1_HEURISTIC_PCT = 10.0
TOP10_HEURISTIC_PCT = 30.0

# Token-2022 extensions that can restrict or reverse transfers (Solana ExtensionType list, KR-000026 sec. 3).
EXT_BENIGN = {"metadataPointer", "tokenMetadata", "groupPointer", "groupMemberPointer", "tokenGroup",
              "tokenGroupMember", "immutableOwner", "interestBearingConfig", "scaledUiAmountConfig"}


def valid_mint(s):
    return isinstance(s, str) and bool(B58.match(s))


def _num(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _pct(part, whole):
    return None if part is None or not whole else round(100.0 * part / whole, 4)


# ---------- market (DEX Screener /token-pairs) ----------

def main_pair(pairs):
    """Stated rule: highest liquidity.usd; when no pair reports liquidity, highest volume.h24."""
    if not pairs:
        return None, "no pairs listed"
    with_liq = [p for p in pairs if _num((p.get("liquidity") or {}).get("usd")) is not None]
    if with_liq:
        return max(with_liq, key=lambda p: _num(p["liquidity"]["usd"])), "highest liquidity.usd"
    return max(pairs, key=lambda p: _num((p.get("volume") or {}).get("h24")) or 0.0), \
        "highest volume.h24 (no pair reports liquidity.usd)"


def _txn(p, w):
    t = (p.get("txns") or {}).get(w) or {}
    b, s = t.get("buys"), t.get("sells")
    return b, s


def pair_summary(p, now_ms):
    liq = p.get("liquidity") or {}
    created = p.get("pairCreatedAt")
    out = {
        "dex": p.get("dexId"), "pair_address": p.get("pairAddress"), "url": p.get("url"),
        "quote": (p.get("quoteToken") or {}).get("symbol"),
        "price_usd": _num(p.get("priceUsd")), "price_native": _num(p.get("priceNative")),
        "market_cap_usd": _num(p.get("marketCap")), "fdv_usd": _num(p.get("fdv")),
        "liquidity_usd": _num(liq.get("usd")),
        "volume_usd": {w: _num((p.get("volume") or {}).get(w)) for w in ("m5", "h1", "h6", "h24")},
        "price_change_pct": {w: _num((p.get("priceChange") or {}).get(w)) for w in ("m5", "h1", "h6", "h24")},
        "txns": {}, "pair_created_at_ms": created,
        "pair_age_s": None if not created else max(0, int((now_ms - created) / 1000)),
        "labels": p.get("labels") or [],
    }
    for w in ("m5", "h1", "h6", "h24"):
        b, s = _txn(p, w)
        tot = (b or 0) + (s or 0) if b is not None and s is not None else None
        out["txns"][w] = {"buys": b, "sells": s,
                          "buy_share_pct": None if not tot else round(100.0 * b / tot, 2)}
    return out


def base_pairs(pairs, mint):
    """Pairs where the token is the base. /token-pairs also returns pairs where it is only the quote."""
    return [p for p in (pairs or []) if isinstance(p, dict) and (p.get("baseToken") or {}).get("address") == mint]


def is_pump_launch(mint, pairs):
    return mint.endswith("pump") or any(p.get("dexId") == "pumpfun" for p in base_pairs(pairs, mint))


def market(pairs, now_ms, mint):
    missing = []
    quote_only = len([p for p in (pairs or []) if isinstance(p, dict)])
    pairs = base_pairs(pairs, mint)
    quote_only -= len(pairs)
    mp, rule = main_pair(pairs)
    res = {"pairs_listed": len(pairs), "main_pair_rule": rule, "main_pair": None, "all_pairs": [],
           "quote_side_pairs_ignored": quote_only,
           "totals_h24": None, "oldest_pair_age_s": None, "graduated_listing": None}
    if not pairs:
        missing.append({"field": "market", "reason": "DEX Screener lists no pairs with this token as base "
                        "(it drops inactive tokens, KR-000004)"})
        return res, missing
    summ = [pair_summary(p, now_ms) for p in pairs]
    res["all_pairs"] = sorted(summ, key=lambda s: (s["dex"] or "", s["pair_address"] or ""))
    res["main_pair"] = pair_summary(mp, now_ms)
    if res["main_pair"]["liquidity_usd"] is None:
        missing.append({"field": "liquidity_usd", "reason": "not reported by DEX Screener for this pair "
                        "(Pump.fun curve pairs report none, KR-000004); unknown, not zero"})
    if res["main_pair"]["market_cap_usd"] is None:
        missing.append({"field": "market_cap_usd", "reason": "not reported by DEX Screener"})
    vol = [s["volume_usd"]["h24"] for s in summ]
    buys = [s["txns"]["h24"]["buys"] for s in summ]
    sells = [s["txns"]["h24"]["sells"] for s in summ]
    res["totals_h24"] = {
        "volume_usd": None if any(v is None for v in vol) else round(sum(vol), 2),
        "buys": None if any(v is None for v in buys) else sum(buys),
        "sells": None if any(v is None for v in sells) else sum(sells),
        "note": "summed across all listed pairs; volume is washable, prefer txn counts",
    }
    ages = [s["pair_age_s"] for s in summ if s["pair_age_s"] is not None]
    res["oldest_pair_age_s"] = max(ages) if ages else None
    dexes = {s["dex"] for s in summ}
    if mint.endswith("pump") or "pumpfun" in dexes:
        res["graduated_listing"] = "pumpswap" in dexes
    return res, missing


def ratios(mkt):
    """Descriptive only (KR-000015, KR-000036/038): not a screen, never a rank key."""
    mp = (mkt or {}).get("main_pair") or {}
    mc, liq, v = mp.get("market_cap_usd"), mp.get("liquidity_usd"), (mp.get("volume_usd") or {}).get("h24")
    return {"liquidity_to_mc": None if not mc or liq is None else round(liq / mc, 6),
            "volume_h24_to_mc": None if not mc or v is None else round(v / mc, 6),
            "label": "descriptive only; no study validates these as screens (KR-000015, KR-000036/038)"}


# ---------- mint facts (getAccountInfo jsonParsed) ----------

def _ext_flag(e):
    name, st = e.get("extension"), e.get("state") or {}
    if name in EXT_BENIGN:
        return None
    if name == "transferHook":
        pid = st.get("programId")
        return pid and ("transfer_hook", "a program ({}) runs on every transfer and can reject it".format(pid), st)
    if name == "permanentDelegate":
        d = st.get("delegate")
        return d and ("permanent_delegate", "{} can move or burn any holder's balance".format(d), st)
    if name == "nonTransferable":
        return ("non_transferable", "tokens cannot be transferred", st)
    if name == "defaultAccountState":
        s = st.get("accountState")
        return s == "frozen" and ("default_frozen", "new token accounts start frozen", st)
    if name == "transferFeeConfig":
        fee = (st.get("newerTransferFee") or {}).get("transferFeeBasisPoints")
        return ("transfer_fee", "transfer fee {} bps; fee authority {}".format(
            fee, st.get("transferFeeConfigAuthority")), st)
    if name in ("pausableConfig", "pausable"):
        return ("pausable", "transfers can be paused by {} (paused now: {})".format(
            st.get("authority"), st.get("paused")), st)
    if name == "mintCloseAuthority":
        a = st.get("closeAuthority")
        return a and ("mint_close_authority", "{} can close the mint account".format(a), st)
    if name == "confidentialTransferMint":
        return ("confidential_transfers", "balances can move confidentially; holder data may be incomplete", st)
    return ("unrecognised_extension", "extension '{}' is not classified by this tool".format(name), st)


def mint_facts(acct):
    """Returns (facts, flags, missing). acct is getAccountInfo(jsonParsed) result['value']."""
    if not acct:
        return None, [], [{"field": "mint", "reason": "mint account not found on chain"}]
    data = acct.get("data") or {}
    parsed = data.get("parsed") if isinstance(data, dict) else None
    if not parsed or parsed.get("type") != "mint":
        return None, [], [{"field": "mint", "reason": "account is not a token mint"}]
    info = parsed.get("info") or {}
    program = acct.get("owner")
    exts = info.get("extensions") or []
    facts = {"program": "token-2022" if program == TOKEN_2022 else "spl-token" if program == SPL_TOKEN else program,
             "decimals": info.get("decimals"), "supply_raw": int(info["supply"]) if info.get("supply") else None,
             "mint_authority": info.get("mintAuthority"), "freeze_authority": info.get("freezeAuthority"),
             "extensions": sorted(e.get("extension") for e in exts if e.get("extension"))}
    flags = []
    if facts["mint_authority"]:
        flags.append(_flag("mint_authority_present", "fact", "supply can be increased by {}".format(
            facts["mint_authority"]), {"mintAuthority": facts["mint_authority"]}))
    if facts["freeze_authority"]:
        flags.append(_flag("freeze_authority_present", "fact", "can freeze holders: authority {} can freeze any "
                           "holder's account, and a frozen holder cannot sell (capability, not a confirmed "
                           "honeypot)".format(facts["freeze_authority"]),
                           {"freezeAuthority": facts["freeze_authority"]}))
    for e in exts:
        f = _ext_flag(e)
        if f:
            flags.append(_flag(f[0], "fact", f[1], {"extension": e.get("extension"), "state": f[2]}))
    return facts, flags, []


def _flag(code, cls, text, evidence):
    return {"code": code, "class": cls, "text": text, "evidence": evidence}


# ---------- holders (getTokenLargestAccounts + getMultipleAccounts) ----------

def holders(largest, owner_accts, supply_raw, pair_addresses):
    """Concentration with and without venues (pool or curve accounts). Unresolved owners stay unknown.

    Venues come only from listed pair addresses. With no listed pair (none listed, or the pairs fetch
    failed) venues are unknown: the pool or curve may be among the largest accounts, so venue share and
    concentration excluding venues are not computed and no concentration flag is raised."""
    missing, flags = [], []
    if largest is None:
        return None, flags, [{"field": "holders", "reason": "largest accounts not fetched"}]
    if not supply_raw:
        return None, flags, [{"field": "holders", "reason": "supply unknown"}]
    venues = {a: d for a, d in (pair_addresses or {}).items() if a}
    venues_known = bool(venues)
    rows = []
    for i, a in enumerate(largest):
        o = owner_accts[i] if owner_accts and i < len(owner_accts) else None
        owner = None
        if o and isinstance(o.get("data"), dict):
            owner = ((o["data"].get("parsed") or {}).get("info") or {}).get("owner")
        amt = int(a.get("amount") or 0)
        kind = ("unknown" if owner is None else ("venue:" + venues[owner]) if owner in venues
                else "holder" if venues_known else "unclassified")
        rows.append({"token_account": a.get("address"), "owner": owner, "kind": kind,
                     "pct_supply": _pct(amt, supply_raw)})
    unresolved = sum(1 for r in rows if r["owner"] is None)
    if unresolved:
        missing.append({"field": "holder_owners", "reason": "{} of {} owners unresolved; counted as non-venue "
                        "holders below".format(unresolved, len(rows))})
    venue_pct = round(sum(r["pct_supply"] for r in rows if r["kind"].startswith("venue")), 4)
    non = [r for r in rows if not r["kind"].startswith("venue")]
    # Several token accounts can share one owner: concentration is per owner wallet.
    by_owner = {}
    for r in non:
        k = r["owner"] or ("?" + str(r["token_account"]))
        by_owner[k] = by_owner.get(k, 0.0) + r["pct_supply"]
    top = sorted(by_owner.values(), reverse=True)
    if not venues_known:
        missing.append({"field": "holder_venues", "reason": "venues unknown: DEX Screener lists no pair for this "
                        "token (or the pairs fetch failed), so pool/curve accounts cannot be told apart from "
                        "wallets; concentration excluding venues not computed, no concentration flags"})
        venue_pct, top = None, []
    res = {
        "accounts_returned": len(rows),
        "venues_known": venues_known,
        "top1_pct_incl_venues": rows[0]["pct_supply"] if rows else None,
        "top10_pct_incl_venues": round(sum(r["pct_supply"] for r in rows[:10]), 4) if rows else None,
        "venue_pct": venue_pct,
        "top1_holder_pct_excl_venues": round(top[0], 4) if top else None,
        "top10_holders_pct_excl_venues": round(sum(top[:10]), 4) if top else None,
        "unresolved_owners": unresolved,
        "rows": rows,
        "note": "only the largest token accounts returned by RPC are seen; holder count is not known",
    }
    t1, t10 = res["top1_holder_pct_excl_venues"], res["top10_holders_pct_excl_venues"]
    if t1 is not None and t1 >= TOP1_HEURISTIC_PCT:
        flags.append(_flag("top1_holder_concentration", "heuristic",
                           "largest non-venue wallet holds {:.2f}% (threshold {}%, not validated)".format(
                               t1, TOP1_HEURISTIC_PCT), {"pct": t1}))
    if t10 is not None and t10 >= TOP10_HEURISTIC_PCT:
        flags.append(_flag("top10_holder_concentration", "heuristic",
                           "top 10 non-venue wallets hold {:.2f}% (threshold {}%, not validated)".format(
                               t10, TOP10_HEURISTIC_PCT), {"pct": t10}))
    return res, flags, missing


# ---------- Pump.fun launch context (KR-000038) ----------

def is_create(tx):
    return any("Instruction: Create" in l for l in ((tx.get("meta") or {}).get("logMessages") or []))


def launch_context(first_page, mint):
    """first_page: getTransactionsForAddress(mint, asc, full) result['data']. Uses Researcher's block0()."""
    txs = [t for t in (first_page or []) if t.get("meta") is not None]
    if not txs:
        return None, [], [{"field": "launch_context", "reason": "no transactions with details in the first page"}]
    txs = ordered(txs)
    create = txs[0]
    if not is_create(create):
        return None, [], [{"field": "launch_context", "reason": "first transaction is not a Pump.fun create; "
                           "block-0 measures apply to Pump.fun launches only"}]
    launch = {"mint": mint, "deployer": fee_payer(create), "slot": create["slot"],
              "signature": create["transaction"]["signatures"][0]}
    b = block0(txs, launch)
    in_slot = sum(1 for t in txs if t["slot"] == launch["slot"])
    truncated = len(first_page) >= 100 and all(t["slot"] == launch["slot"] for t in txs)
    res = {"created_block_time": create.get("blockTime"), "creation_slot": launch["slot"],
           "deployer": launch["deployer"], "creation_slot_txs_seen": in_slot,
           "block0_supply_share_pct": round(b.get("block0_share"), 4) if b.get("create_found") else None,
           "block0_buyers": b.get("block0_buyers"),
           "same_slot_graduation": b.get("graduated_in_block0"),
           "page_truncated": truncated,
           "label": "association only, partly mechanical (KR-000038). Block-0 buyers mix dev bundles and "
                    "independent snipers; no funding-link test yet."}
    flags, missing = [], []
    if truncated:
        missing.append({"field": "block0", "reason": "100+ transactions in the creation slot; values are lower bounds"})
    if res["block0_buyers"]:
        flags.append(_flag("block0_buyers", "fact", "{} wallets received {:.2f}% of supply (net) in the creation slot".format(
            res["block0_buyers"], res["block0_supply_share_pct"] or 0.0),
            {"slot": launch["slot"], "buyers": res["block0_buyers"], "share_pct": res["block0_supply_share_pct"]}))
    if res["same_slot_graduation"]:
        flags.append(_flag("same_slot_graduation", "fact", "graduated inside its creation slot: graduation was "
                           "bought, not a sign of organic demand (KR-000038)", {"slot": launch["slot"]}))
    return res, flags, missing


# ---------- report ----------

FLAG_ORDER = {"fact": 0, "heuristic": 1}

# Labels and records per flag, from docs/RISK_SIGNALS.md v1. "source" is the read the flag comes from.
SIGNALS = {
    "freeze_authority_present": ("fact · capability", ["KR-000022", "KR-000046", "KR-000047"], "helius getAccountInfo"),
    "mint_authority_present": ("fact · capability", ["KR-000026"], "helius getAccountInfo"),
    "transfer_hook": ("fact · capability", ["KR-000022", "KR-000048"], "helius getAccountInfo"),
    "permanent_delegate": ("fact · capability", ["KR-000022", "KR-000048"], "helius getAccountInfo"),
    "default_frozen": ("fact · capability", ["KR-000022", "KR-000048"], "helius getAccountInfo"),
    "non_transferable": ("fact · capability", ["KR-000022", "KR-000048"], "helius getAccountInfo"),
    "transfer_fee": ("fact · capability", ["KR-000026"], "helius getAccountInfo"),
    "pausable": ("fact · capability", ["KR-000026"], "helius getAccountInfo"),
    "mint_close_authority": ("fact · capability", ["KR-000026"], "helius getAccountInfo"),
    "confidential_transfers": ("fact · capability", ["KR-000026"], "helius getAccountInfo"),
    "unrecognised_extension": ("fact · unclassified", ["KR-000026"], "helius getAccountInfo"),
    "block0_buyers": ("fact; meaning is a replicated association", ["KR-000036", "KR-000038"],
                      "helius getTransactionsForAddress(asc)"),
    "same_slot_graduation": ("fact", ["KR-000036", "KR-000038"], "helius getTransactionsForAddress(asc)"),
    "top1_holder_concentration": ("heuristic · threshold not validated", ["KR-000015"], "helius getTokenLargestAccounts"),
    "top10_holder_concentration": ("heuristic · threshold not validated", ["KR-000015"], "helius getTokenLargestAccounts"),
}
CONTEXT = {
    "freeze_authority_present": "published freeze abuse: 461 of 100,063 new Orca/Raydium/Meteora tokens (0.46%, CI "
                                "0.42-0.51%, 2025-H1, lower bound); how often a retained authority is used is being "
                                "measured (study 5)",
    "block0_buyers": "creation-slot buyer clusters: 79.5% of graduates vs 25.7% of non-graduates (n=73/300, "
                     "2026-11-11), 88.7% vs 18.0% on the holdout day (n=115/300); dev bundles and independent "
                     "snipers are mixed until study 4 (KR-000039/40) is filed",
    "same_slot_graduation": "41.1% (30/73) and 60.0% (69/115) of graduates graduated in their creation slot",
}
# Established quote assets that keep a freeze authority by design (RISK_SIGNALS.md sec. 1).
KNOWN_STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
                 "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT"}
NEW_MINT_DAYS = 30


def apply_signal_rules(mint, flags, age, sources):
    """Attach label, records, source and fetched_at to each flag; apply the freeze-authority scope rule
    (flag only new mints; never established stablecoins). Returns (flags, not_flagged, missing)."""
    fetched = {}
    for src in sources or []:
        fetched.setdefault("{} {}".format(src["provider"], src["endpoint"]), src["fetched_at"])
    out, not_flagged, missing = [], [], []
    age_s = None if not age else age.get("mint_age_s", age.get("pair_age_s"))
    for f in flags:
        if f["code"] == "freeze_authority_present":
            if mint in KNOWN_STABLES:
                not_flagged.append("freeze authority present on {} (established stablecoin that keeps it by design; "
                                   "see permissions)".format(KNOWN_STABLES[mint]))
                continue
            if age_s is not None and age_s > NEW_MINT_DAYS * 86400:
                not_flagged.append("freeze authority present, but the {} is older than {} days, so it is out of "
                                   "scope for the new-mint honeypot flag (see permissions)".format(
                                       "mint" if "mint_age_s" in age else "oldest pair", NEW_MINT_DAYS))
                continue
            if age_s is None:
                f = dict(f, text=f["text"] + "; mint age unknown, treated as new")
            missing.append({"field": "freeze_used", "reason": "not checked whether the authority has frozen any "
                            "holder (needs the mint's transaction history); study 5 (KR-000047/48) is measuring it"})
        label, records, source = SIGNALS.get(f["code"], (f["class"], [], None))
        g = dict(f, label=label, records=records, source=source, fetched_at=fetched.get(source))
        if f["code"] in CONTEXT:
            g["context"] = CONTEXT[f["code"]]
        out.append(g)
    return out, not_flagged, missing


def build_report(mint, now_s, pairs=None, mint_acct=None, largest=None, owner_accts=None, first_page=None,
                 sources=None, errors=None):
    """Assemble one deterministic report. Inputs that were not fetched are None; `errors` explains why.

    pairs: DEX Screener token-pairs list. mint_acct: getAccountInfo result. largest: getTokenLargestAccounts
    result['value']. owner_accts: getMultipleAccounts result['value'] for those accounts, same order.
    first_page: getTransactionsForAddress(mint, asc) result['data'].
    """
    missing = [{"field": f, "reason": r} for f, r in (errors or {}).items()]
    flags = []
    mkt, m = market(pairs, int(now_s * 1000), mint) if pairs is not None else (None, [])
    missing += m
    # mint_acct is the getAccountInfo result ({"value": ...}); None means it was not fetched.
    facts, fl, m = mint_facts(mint_acct.get("value")) if mint_acct is not None else (None, [], [])
    flags += fl
    missing += m
    pair_addr = {s["pair_address"]: s["dex"] for s in (mkt or {}).get("all_pairs", [])}
    hold, fl, m = (holders(largest, owner_accts, (facts or {}).get("supply_raw"), pair_addr)
                   if largest is not None else (None, [], []))
    flags += fl
    missing += m
    launch, fl, m = launch_context(first_page, mint) if first_page is not None else (None, [], [])
    flags += fl
    missing += m
    age = None
    if launch and launch.get("created_block_time"):
        age = {"mint_age_s": max(0, int(now_s - launch["created_block_time"])), "source": "creation tx blockTime"}
    elif mkt and mkt.get("oldest_pair_age_s") is not None:
        age = {"pair_age_s": mkt["oldest_pair_age_s"], "source": "DEX Screener pairCreatedAt (pair age, not mint age)"}
    else:
        missing.append({"field": "age", "reason": "no creation tx or pair creation time"})
    graduated = (mkt or {}).get("graduated_listing")
    flags, not_flagged, m = apply_signal_rules(mint, flags, age, sources)
    missing += m
    flags.sort(key=lambda f: (FLAG_ORDER[f["class"]], f["code"]))
    return {
        "tool": TOOL, "version": VERSION, "findings": FINDINGS, "disclaimer": DISCLAIMER,
        "chain": "solana", "mint": mint, "generated_at": int(now_s),
        "risk_flags": flags,
        "not_flagged": not_flagged,
        "risk_spec": RISK_SPEC,
        "missing": sorted(missing, key=lambda x: x["field"]),
        "permissions": facts,
        "holders": hold,
        "launch_context": dict(launch or {}, graduated_listing=graduated,
                               graduated_note="'graduated' is risk context, not quality (KR-000038)") if (launch or graduated is not None) else None,
        "market": mkt,
        "ratios": ratios(mkt) if mkt else None,
        "age": age,
        "sources": sorted(sources or [], key=lambda s: (s["provider"], s["endpoint"])),
    }


# ---------- text for Discord / terminal ----------

def _usd(x):
    if x is None:
        return "unknown"
    for d, s in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= d:
            return "${:.2f}{}".format(x / d, s)
    return "${:.6g}".format(x)


def _dur(s):
    if s is None:
        return "unknown"
    for d, u in ((86400, "d"), (3600, "h"), (60, "m")):
        if s >= d:
            return "{:.1f}{}".format(s / d, u)
    return "{}s".format(s)


def render_text(r, limit=3900):
    L = ["**Scan** `{}`  ({} v{}, at <t:{}:f>)".format(r["mint"], r["tool"], r["version"], r["generated_at"]),
         "_{}_".format(r["disclaimer"]), "", "**Risk flags** (facts first, then heuristics)"]
    if r["risk_flags"]:
        for f in r["risk_flags"]:
            src = ""
            if f.get("source"):
                src = " ({} {}; {})".format(f["source"], "<t:{}:R>".format(int(f["fetched_at"]))
                                            if f.get("fetched_at") else "time unknown", ", ".join(f.get("records") or []))
            L.append("- [{}] {}{}".format(f.get("label", f["class"]), f["text"], src))
            if f.get("context"):
                L.append("  context: " + f["context"])
    else:
        L.append("- none seen in the data read (absence of a flag is not a safety verdict)")
    for n in r.get("not_flagged") or []:
        L.append("- not flagged: " + n)
    p = r.get("permissions")
    if p:
        L += ["", "**Mint** {}, decimals {}, mint authority: {}, freeze authority: {}".format(
            p["program"], p["decimals"], p["mint_authority"] or "none", p["freeze_authority"] or "none")]
        if p["extensions"]:
            L.append("Extensions: " + ", ".join(p["extensions"]))
    h = r.get("holders")
    if h:
        def pc(x):
            return "unknown" if x is None else "{:.2f}%".format(x)
        if h.get("venues_known", True):
            L += ["", "**Holders** (largest {} accounts): top 1 wallet {}, top 10 wallets {} excluding pools/curve; "
                  "pools/curve hold {}".format(h["accounts_returned"], pc(h["top1_holder_pct_excl_venues"]),
                                              pc(h["top10_holders_pct_excl_venues"]), pc(h["venue_pct"]))]
        else:
            L += ["", "**Holders** (largest {} accounts): top 1 account {}, top 10 accounts {}, pools/curve "
                  "included; venues unknown (no listed pair), so no wallet concentration is computed".format(
                      h["accounts_returned"], pc(h["top1_pct_incl_venues"]), pc(h["top10_pct_incl_venues"]))]
    lc = r.get("launch_context")
    if lc:
        L += ["", "**Launch context** (KR-000038, association only)"]
        if lc.get("graduated_listing") is not None:
            L.append("Graduated (DEX Screener lists a PumpSwap pair): {}. Risk context, not quality.".format(
                "yes" if lc["graduated_listing"] else "no"))
        if "block0_buyers" in lc:
            L.append("Creation slot: {} net receivers, {} of supply; graduated in same slot: {}{}".format(
                lc["block0_buyers"], "unknown" if lc["block0_supply_share_pct"] is None
                else "{:.2f}%".format(lc["block0_supply_share_pct"]),
                "yes" if lc["same_slot_graduation"] else "no", " (lower bound)" if lc["page_truncated"] else ""))
    m = r.get("market")
    if m and m.get("main_pair"):
        mp = m["main_pair"]
        t = mp["txns"]["h24"]
        L += ["", "**Market** main pair {} ({}; {} pairs listed)".format(mp["dex"], m["main_pair_rule"], m["pairs_listed"]),
              "Price {} | MC {} | liquidity {} | 24h vol {}".format(
                  _usd(mp["price_usd"]), _usd(mp["market_cap_usd"]), _usd(mp["liquidity_usd"]),
                  _usd(mp["volume_usd"]["h24"])),
              "24h txns: {} buys / {} sells (buy share {})".format(
                  t["buys"], t["sells"], "unknown" if t["buy_share_pct"] is None else "{}%".format(t["buy_share_pct"]))]
    if r.get("age"):
        a = r["age"]
        L.append("Age: {} ({})".format(_dur(a.get("mint_age_s", a.get("pair_age_s"))), a["source"]))
    if r.get("ratios"):
        q = r["ratios"]
        L.append("Ratios (descriptive only): liq/MC {}, vol24/MC {}".format(q["liquidity_to_mc"], q["volume_h24_to_mc"]))
    if r["missing"]:
        L += ["", "**Missing or unreliable**"] + ["- {}: {}".format(x["field"], x["reason"]) for x in r["missing"]]
    if r.get("sources"):
        L += ["", "Sources: " + "; ".join("{} {} <t:{}:R>{}".format(s["provider"], s["endpoint"], int(s["fetched_at"]),
                                                                    " (reused)" if s.get("reused") else "")
                                        for s in r["sources"])]
    text = "\n".join(L)
    return text if len(text) <= limit else text[:limit - 20] + "\n…(truncated)"
