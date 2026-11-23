import struct
import unittest

from research.study7_parse import CPI, TRADE, b58decode, b58encode, decode_curve, decode_pool, main_pool

MINT = bytes(range(32))


def curve_event(sol, tok, vs, vt, rs, buy=True):
    b = MINT + struct.pack("<QQ", sol, tok) + bytes([buy]) + b"\x01" * 32 + struct.pack("<q", 1) + struct.pack("<QQQQ", vs, vt, rs, 1)
    return CPI + TRADE + b + b"\0" * 8


def sell_event(base_in, base, quote, out, vq):
    b = bytearray(440)
    struct.pack_into("<Q", b, 8, base_in)
    struct.pack_into("<QQ", b, 40, base, quote)
    struct.pack_into("<Q", b, 56, out)
    b[384:400] = int(vq).to_bytes(16, "little", signed=True)
    return CPI + b"x" * 8 + bytes(b)


class Study7Parse(unittest.TestCase):
    def test_base58_round_trip(self):
        raw = b"\0\0" + bytes(range(1, 31))
        self.assertEqual(b58decode(b58encode(raw)), raw)

    def test_curve_price_from_reserves(self):
        x = decode_curve(curve_event(10 ** 9, 10 ** 6, 40 * 10 ** 9, 10 ** 15, 10 ** 10), MINT)
        self.assertAlmostEqual(x["price"], 40 / 1e9)
        self.assertEqual(x["liq"], 10.0)

    def test_curve_other_mint_ignored(self):
        self.assertIsNone(decode_curve(curve_event(1, 1, 1, 1, 1), b"\x09" * 32))

    def test_pool_sell_uses_signed_effective_quote(self):
        x = decode_pool(sell_event(10 ** 6, 10 ** 12, 10 ** 10, 10 ** 7, -10 ** 9), False)
        self.assertAlmostEqual(x["liq"], (10 ** 10 - 10 ** 9 - 10 ** 7) / 1e9)
        self.assertAlmostEqual(x["price"], ((10 ** 10 - 10 ** 9 - 10 ** 7) / 1e9) / ((10 ** 12 + 10 ** 6) / 1e6))

    def test_main_pool_by_sol_volume(self):
        ev = [{"venue": "pool", "pool": "a", "sol": 1.0}, {"venue": "pool", "pool": "b", "sol": 5.0}, {"venue": "curve", "sol": 99.0}]
        self.assertEqual(main_pool(ev), "b")


if __name__ == "__main__":
    unittest.main()
