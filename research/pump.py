"""Pure parsers for Pump.fun transactions (jsonParsed RPC shape). No network."""

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
MINT_AUTHORITY = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"
WSOL = "So11111111111111111111111111111111111111112"
# Swap venues (from solana-cluster-tracker/src/services/helius.ts DEX_PROGRAMS) used to label sells.
DEX_PROGRAMS = {
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C", "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
    PUMP, "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA", "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9t6A3Ha2a8", "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB",
    "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG", "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
}


def account_keys(tx):
    return [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]


def all_instructions(tx):
    out = list(tx["transaction"]["message"].get("instructions", []))
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        out.extend(inner.get("instructions", []))
    return out


def is_create(tx):
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return False
    logs = meta.get("logMessages") or []
    return any(l in ("Program log: Instruction: Create", "Program log: Instruction: CreateV2") for l in logs)


def parse_create(tx):
    """Return launch facts for a Pump.fun create tx, or None."""
    if not is_create(tx):
        return None
    meta = tx["meta"]
    keys = account_keys(tx)
    post = meta.get("postTokenBalances") or []
    mints = {b["mint"] for b in post if b["mint"] != WSOL}
    mint = None
    for ix in all_instructions(tx):
        accts = ix.get("accounts") or []
        if ix.get("programId") == PUMP and accts and accts[0] in mints:
            mint = accts[0]
            break
    if mint is None:
        if len(mints) != 1:
            return None
        mint = next(iter(mints))
    deployer = keys[0]  # fee payer
    dev_raw, ata, decimals, token_program = 0, None, None, None
    for b in post:
        if b["mint"] == mint:
            decimals = b["uiTokenAmount"]["decimals"]
            token_program = b.get("programId")
            if b.get("owner") == deployer:
                dev_raw += int(b["uiTokenAmount"]["amount"])
                ata = keys[b["accountIndex"]]
    return {"mint": mint, "deployer": deployer, "t0": tx["blockTime"], "slot": tx["slot"],
            "signature": tx["transaction"]["signatures"][0], "dev_raw": dev_raw, "dev_ata": ata,
            "decimals": decimals, "token_program": token_program,
            "create_v2": "Program log: Instruction: CreateV2" in (meta.get("logMessages") or [])}


def owner_balance(tx, owner, mint, which):
    """Raw token balance of `owner` for `mint` in pre/postTokenBalances (None if absent)."""
    bals = (tx.get("meta") or {}).get(which) or []
    vals = [int(b["uiTokenAmount"]["amount"]) for b in bals if b["mint"] == mint and b.get("owner") == owner]
    return sum(vals) if vals else None


def lamport_delta(tx, addr):
    keys = account_keys(tx)
    if addr not in keys:
        return 0
    i = keys.index(addr)
    m = tx["meta"]
    return m["postBalances"][i] - m["preBalances"][i]


def touches_dex(tx):
    keys = set(account_keys(tx))
    progs = {ix.get("programId") for ix in all_instructions(tx)}
    return bool((keys | progs) & DEX_PROGRAMS)


def classify_out(tx, owner, mint):
    """'sell' if a DEX program ran and the owner's SOL (or WSOL) rose, else 'transfer'."""
    if not touches_dex(tx):
        return "transfer"
    sol = lamport_delta(tx, owner) + (tx["meta"].get("fee", 0) if account_keys(tx)[0] == owner else 0)
    wsol_pre = owner_balance(tx, owner, WSOL, "preTokenBalances") or 0
    wsol_post = owner_balance(tx, owner, WSOL, "postTokenBalances") or 0
    return "sell" if sol + (wsol_post - wsol_pre) > 0 else "transfer"
