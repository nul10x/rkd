import unittest

from research import study3_parse as P

MINT, DEV, CURVE, POOL, WSOL = "M", "DEV", "CURVE", "POOL", "So11111111111111111111111111111111111111112"


def bal(owner, amt, mint=MINT):
    return {"mint": mint, "owner": owner, "uiTokenAmount": {"amount": str(int(amt)), "uiAmountString": str(amt)}}


def tx(sig, slot, idx, pre, post, t=100, payer="P", logs=()):
    return {"slot": slot, "transactionIndex": idx, "blockTime": t,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [{"pubkey": payer}]}},
            "meta": {"preTokenBalances": pre, "postTokenBalances": post, "logMessages": list(logs)}}


LAUNCH = {"mint": MINT, "deployer": DEV, "slot": 10, "signature": "C", "t0": 100}
S = P.SUPPLY_RAW


class Block0(unittest.TestCase):
    def test_net_receivers_exclude_pool_and_senders(self):
        create = tx("C", 10, 0, [], [bal(CURVE, 0.98 * S), bal(DEV, 0.02 * S)])
        buy = tx("B", 10, 1, [bal(CURVE, 0.98 * S)], [bal(CURVE, 0.48 * S), bal("A", 0.5 * S)])
        mig = tx("G", 10, 2, [bal(CURVE, 0.48 * S)], [bal(CURVE, 0), bal(POOL, 0.48 * S)], logs=["Program log: Instruction: Migrate"])
        sell = tx("S", 10, 3, [bal(POOL, 0.48 * S)], [bal(POOL, 0.38 * S), bal("B2", 0.1 * S)])
        later = tx("L", 11, 0, [bal(POOL, 0.38 * S)], [bal(POOL, 0.28 * S), bal("Z", 0.1 * S)])
        r = P.block0([create, buy, mig, sell, later], LAUNCH)
        self.assertAlmostEqual(r["block0_share"], 60.0)  # A 50% + B2 10%; pool excluded (it sends), Z is slot 11
        self.assertEqual(r["block0_buyers"], 2)
        self.assertTrue(r["graduated_in_block0"])

    def test_no_block0(self):
        create = tx("C", 10, 0, [], [bal(CURVE, S)])
        r = P.block0([create, tx("X", 12, 0, [bal(CURVE, S)], [bal(CURVE, 0.9 * S), bal("Q", 0.1 * S)])], LAUNCH)
        self.assertEqual(r["block0_share"], 0.0)
        self.assertFalse(r["graduated_in_block0"])

    def test_create_missing(self):
        self.assertFalse(P.block0([], LAUNCH)["create_found"])


class DevExit(unittest.TestCase):
    def test_exit_time_and_horizon(self):
        a = tx("C", 10, 0, [], [bal(DEV, 1000)], t=100)
        b = tx("D", 11, 0, [bal(DEV, 1000)], [bal(DEV, 5)], t=160)
        self.assertEqual(P.dev_exit([a, b], LAUNCH, 3600), 60)
        self.assertIsNone(P.dev_exit([a, b], LAUNCH, 30))


class Pool(unittest.TestCase):
    def test_latest_state_skips_sol_only_tx(self):
        arb = tx("A", 20, 0, [], [bal(POOL, 1.5, WSOL)])
        full = tx("F", 19, 0, [], [bal(POOL, 2.0, WSOL), bal(POOL, 1e8)])
        s, t, _ = P.latest_state([arb, full], POOL, MINT, WSOL)
        self.assertEqual((s, t), (2.0, 1e8))
        # liq/MC identity: 2*s / (s/t*1e9) == 2*t/1e9
        self.assertAlmostEqual(2 * s / (s / t * 1e9), 2 * t / 1e9)

    def test_sol_volume(self):
        e = tx("V", 1, 0, [bal(POOL, 3.0, WSOL)], [bal(POOL, 2.5, WSOL)])
        self.assertAlmostEqual(P.sol_volume(e, POOL, WSOL), 0.5)


if __name__ == "__main__":
    unittest.main()
