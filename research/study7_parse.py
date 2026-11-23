"""Study 7 parsers (pure, no network). Decodes Pump.fun curve and PumpSwap trade events. Plan: KR-000068.

Curve: TradeEvent reserves are after the trade. PumpSwap: BuyEvent/SellEvent pool reserves are before the trade;
effective quote = pool quote + signed virtual_quote_reserves (Pump docs, KR-000057/62).
Prices are SOL per whole token (9 / 6 decimals); supply is 1e9 tokens.
"""
import struct

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_IDX = {c: i for i, c in enumerate(B58)}
CPI = bytes.fromhex("e445a52e51cb9a1d")
TRADE = bytes.fromhex("bddb7fd34ee661ee")
BUY = bytes.fromhex("67f4521f2cf57777")
SELL = bytes.fromhex("3e2f370aa503dc2a")
LAUNCH_PRICE = (30e9 / 1e9) / (1.073e15 / 1e6)
DEFAULT_KEY = "11111111111111111111111111111111"
QUOTE_DECIMALS = {DEFAULT_KEY: 9, WSOL: 9}


def b58decode(text):
    n = 0
    for c in text:
        n = n * 58 + _IDX[c]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(text) - len(text.lstrip("1"))) + raw


def b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def _u64(b, p):
    return struct.unpack_from("<Q", b, p)[0]


def curve_quote(b):
    """(quote_mint, quote_amount, virtual_quote, real_quote) from the extended TradeEvent; None if absent."""
    try:
        n = struct.unpack_from("<I", b, 250)[0]
        p = 254 + n + 1 + 32
        holders = struct.unpack_from("<I", b, p)[0]
        p += 4 + holders * 34
        if len(b) < p + 56:
            return None
        return b58encode(b[p:p + 32]), _u64(b, p + 32), _u64(b, p + 40), _u64(b, p + 48)
    except struct.error:
        return None


def decode_curve(d, mint_raw):
    b = d[16:]
    if len(b) < 121 or b[:32] != mint_raw:
        return None
    sol, tok = _u64(b, 32), _u64(b, 40)
    vs, vt, rs = _u64(b, 89), _u64(b, 97), _u64(b, 105)
    if not vt or not tok:
        return None
    q = curve_quote(b)
    quote_mint = q[0] if q else DEFAULT_KEY
    if not vs and q:
        sol, vs, rs = q[1], q[2], q[3]
    decimals = QUOTE_DECIMALS.get(quote_mint)
    if decimals is None or not vs:
        return {"venue": "curve", "buy": bool(b[48]), "user": b58encode(b[49:81]), "sol": None, "tok": tok / 1e6,
                "price": None, "liq": None, "quote_mint": quote_mint}
    return {"venue": "curve", "buy": bool(b[48]), "user": b58encode(b[49:81]), "sol": sol / 10 ** decimals, "tok": tok / 1e6,
            "price": (vs / 10 ** decimals) / (vt / 1e6), "liq": rs / 10 ** decimals, "quote_mint": quote_mint}


def decode_pool(d, is_buy):
    """Returns the event with post-trade price, or None. Pool address is returned for the caller to verify."""
    b = d[16:]
    try:
        base, quote_res = _u64(b, 40), _u64(b, 48)
        amt_base, quote_amt = _u64(b, 8), _u64(b, 56)
        if is_buy:
            n = struct.unpack_from("<I", b, 393)[0]
            p = 397 + n + 32
        else:
            p = 384
        vq = int.from_bytes(b[p:p + 16], "little", signed=True)
        if len(b) < p + 16:
            return None
    except struct.error:
        return None
    eff = quote_res + vq
    base2 = base - amt_base if is_buy else base + amt_base
    eff2 = eff + quote_amt if is_buy else eff - quote_amt
    if base2 <= 0 or eff2 <= 0 or not amt_base:
        return None
    return {"venue": "pool", "buy": is_buy, "user": b58encode(b[144:176]), "pool": b58encode(b[112:144]),
            "sol": quote_amt / 1e9, "tok": amt_base / 1e6, "price": (eff2 / 1e9) / (base2 / 1e6), "liq": eff2 / 1e9}


def main_pool(events):
    """The PumpSwap pool with the most SOL volume for this token, or None."""
    v = {}
    for x in events:
        if x["venue"] == "pool":
            v[x["pool"]] = v.get(x["pool"], 0.0) + x["sol"]
    return max(sorted(v), key=v.get) if v else None


def pools_of(tx, mint):
    """Owners holding both this mint and WSOL: candidate pools for this token in the tx."""
    m = tx.get("meta") or {}
    bal = (m.get("preTokenBalances") or []) + (m.get("postTokenBalances") or [])
    a = {x.get("owner") for x in bal if x.get("mint") == mint}
    w = {x.get("owner") for x in bal if x.get("mint") == WSOL}
    return (a & w) - {None}


def trade_events(tx, mint):
    """Curve and PumpSwap trades of `mint` in instruction order."""
    want, out, pools = b58decode(mint), [], None
    for group in (tx.get("meta") or {}).get("innerInstructions") or []:
        for ins in group.get("instructions") or []:
            pid = ins.get("programId")
            if pid not in (PUMP, PUMPSWAP) or "data" not in ins:
                continue
            try:
                d = b58decode(ins["data"])
            except (KeyError, ValueError):
                continue
            if d[:8] != CPI:
                continue
            tag = d[8:16]
            ev = None
            if pid == PUMP and tag == TRADE:
                ev = decode_curve(d, want)
            elif pid == PUMPSWAP and tag in (BUY, SELL):
                ev = decode_pool(d, tag == BUY)
                if ev:
                    pools = pools_of(tx, mint) if pools is None else pools
                    if ev["pool"] not in pools:
                        ev = None
            if ev:
                out.append(ev)
    return out
