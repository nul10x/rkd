"""Study 5 parsers (pure, no network). Plan: Logbook KR-000047 (amended after pilot KR-000048)."""
from research.pump import account_keys, all_instructions

CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
QUOTES = {WSOL, USDC, USDT}
LAUNCHPAD_PREFIXES = ("LanMV9s", "dbcij3", "6EF8rre")  # Raydium LaunchLab, Meteora DBC, Pump.fun


def cpmm_creates(tx):
    """[(base_mint, launchpad_flag)] from the CPMM create instruction of a pool-creation tx.
    Layout (pilot KR-000048): accounts[4], [5] = token_0/token_1 mints, [6] = LP mint."""
    keys = account_keys(tx)
    lp = any(k.startswith(LAUNCHPAD_PREFIXES) for k in keys)
    out = []
    for ins in all_instructions(tx):
        if ins.get("programId") == CPMM and len(ins.get("accounts") or []) >= 7:
            for m in ins["accounts"][4:6]:
                if m not in QUOTES:
                    out.append((m, lp))
            break
    return out


def _owners(tx):
    keys = account_keys(tx)
    out = {}
    meta = tx.get("meta") or {}
    for b in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or []):
        if b.get("owner") is not None and b.get("accountIndex") is not None and b["accountIndex"] < len(keys):
            out[keys[b["accountIndex"]]] = b["owner"]
    return out


def freeze_events(txs, mint, authority):
    """[(blockTime, frozen_token_account, owner)] for freezeAccount on `mint` signed by `authority`,
    excluding accounts owned by the authority itself. owner None = not visible in token balances (kept)."""
    out = []
    for tx in txs or []:
        own = None
        for ins in all_instructions(tx):
            p = ins.get("parsed")
            if not isinstance(p, dict) or p.get("type") != "freezeAccount":
                continue
            info = p.get("info") or {}
            if info.get("mint") != mint:
                continue
            if (info.get("freezeAuthority") or info.get("multisigFreezeAuthority")) != authority:
                continue
            own = _owners(tx) if own is None else own
            owner = own.get(info.get("account"))
            if owner != authority:
                out.append((tx["blockTime"], info.get("account"), owner))
    return out


RISKY_EXTENSIONS = ("transferHook", "permanentDelegate", "nonTransferable", "defaultAccountState", "mintCloseAuthority",
                    "transferFeeConfig", "pausableConfig")


def capabilities(facts, raw_exts):
    """Honeypot capability flags from token_scanner mint_facts output and the raw extension list."""
    exts = {e.get("extension"): (e.get("state") or {}) for e in raw_exts or []}
    hook = exts.get("transferHook", {})
    deleg = exts.get("permanentDelegate", {})
    das = exts.get("defaultAccountState", {})
    return {"freeze_authority": bool(facts["freeze_authority"]), "mint_authority": bool(facts["mint_authority"]),
            "token_2022": facts["program"] == "token-2022",
            "transfer_hook_set": bool(hook.get("programId")), "permanent_delegate_set": bool(deleg.get("delegate")),
            "default_frozen": das.get("accountState") == "frozen", "non_transferable": "nonTransferable" in exts,
            "transfer_fee": "transferFeeConfig" in exts,
            "any_sell_block_capability": bool(facts["freeze_authority"]) or bool(hook.get("programId")) or
            bool(deleg.get("delegate")) or das.get("accountState") == "frozen" or "nonTransferable" in exts}
