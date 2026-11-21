import unittest

from research import pump
from research.stats import km, km_median, logrank, mann_whitney, wilson


class StatsTest(unittest.TestCase):
    def test_km_no_censoring_median(self):
        self.assertEqual(km_median([1, 2, 3, 4], [1, 1, 1, 1]), 2)
        self.assertAlmostEqual(km([1, 2], [1, 1])[-1][1], 0.0)

    def test_km_censored_not_reached(self):
        self.assertIsNone(km_median([5, 10, 10, 10], [1, 0, 0, 0]))

    def test_logrank_identical_groups(self):
        chi2, p = logrank([1, 2, 3], [1, 1, 1], [1, 2, 3], [1, 1, 1])
        self.assertAlmostEqual(chi2, 0.0)
        self.assertAlmostEqual(p, 1.0)

    def test_mann_whitney_separated(self):
        u, p, auc = mann_whitney([10, 11, 12, 13, 14], [1, 2, 3, 4, 5])
        self.assertEqual(auc, 1.0)
        self.assertLess(p, 0.02)

    def test_wilson(self):
        lo, hi = wilson(0, 47)
        self.assertAlmostEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.0756, places=3)


class PumpParseTest(unittest.TestCase):
    def tx(self, logs, pre, post):
        return {"blockTime": 100, "slot": 1,
                "transaction": {"signatures": ["S"], "message": {
                    "accountKeys": [{"pubkey": "DEV"}, {"pubkey": "MINT"}, {"pubkey": "ATA"}],
                    "instructions": [{"programId": pump.PUMP, "accounts": ["MINT", "X"]}]}},
                "meta": {"err": None, "logMessages": logs, "preTokenBalances": pre, "postTokenBalances": post,
                         "preBalances": [10, 0, 0], "postBalances": [5, 0, 0], "fee": 5}}

    def test_parse_create(self):
        bal = [{"mint": "MINT", "owner": "DEV", "accountIndex": 2, "programId": "TokenzQd",
                "uiTokenAmount": {"amount": "500", "decimals": 6}}]
        p = pump.parse_create(self.tx(["Program log: Instruction: CreateV2"], [], bal))
        self.assertEqual((p["mint"], p["deployer"], p["dev_raw"], p["dev_ata"]), ("MINT", "DEV", 500, "ATA"))

    def test_non_create_ignored(self):
        self.assertIsNone(pump.parse_create(self.tx(["Program log: Instruction: Buy"], [], [])))


if __name__ == "__main__":
    unittest.main()
