import unittest

from research import study4_funding as F

SOL = 1_000_000_000


def ix(kind, src, dst, lam, program="system"):
    key = "newAccount" if kind.startswith("createAccount") else "destination"
    return {"program": program, "parsed": {"type": kind, "info": {"source": src, key: dst, "lamports": lam}}}


def tx(top=(), inner=()):
    return {"transaction": {"message": {"instructions": list(top)}},
            "meta": {"innerInstructions": [{"index": 0, "instructions": list(inner)}] if inner else []}}


class Transfers(unittest.TestCase):
    def test_kinds_inner_and_dust(self):
        t = tx([ix("transfer", "A", "B", SOL), ix("transfer", "A", "C", 1000)],
               [ix("createAccount", "A", "D", SOL // 10), ix("transfer", "A", "E", SOL, program="spl-token")])
        self.assertEqual(F.sol_transfers(t), [("A", "B", SOL), ("A", "D", SOL // 10)])

    def test_flows(self):
        page = [tx([ix("transfer", "X", "W", SOL)]), tx([ix("transfer", "W", "Y", SOL)])]
        self.assertEqual(F.flows(page, "W"), ({"X"}, {"Y"}))


class Delta(unittest.TestCase):
    def _tx(self, keys, pre, post, ins=()):
        return {"transaction": {"message": {"accountKeys": [{"pubkey": k} for k in keys], "instructions": list(ins)}},
                "meta": {"preBalances": pre, "postBalances": post, "innerInstructions": []}}

    def test_payer_funds_via_program(self):
        t = self._tx(["FUNDER", "W", "PROG"], [30 * SOL, 1 * SOL, 1], [10 * SOL, 21 * SOL, 1])
        self.assertEqual(F.flows([t], "W"), ({"FUNDER"}, set()))

    def test_w_pays_recipients_gain(self):
        t = self._tx(["W", "CURVE", "B"], [5 * SOL, 0, 0], [3 * SOL, SOL, SOL // 1000])
        self.assertEqual(F.flows([t], "W"), (set(), {"CURVE"}))

    def test_no_gain_no_funder(self):
        t = self._tx(["RELAY", "W"], [SOL, SOL], [SOL, SOL - 5000])
        self.assertEqual(F.flows([t], "W"), (set(), set()))


class Classify(unittest.TestCase):
    def test_direct_two_hop_shared(self):
        dev_page = [tx([ix("transfer", "FUND", "DEV", 5 * SOL)]), tx([ix("transfer", "DEV", "B1", SOL)]),
                    tx([ix("transfer", "DEV", "MID", SOL)])]
        pages = {"B1": [tx([ix("transfer", "DEV", "B1", SOL)])],
                 "B2": [tx([ix("transfer", "MID", "B2", SOL)])],
                 "B3": [tx([ix("transfer", "FUND", "B3", SOL)])],
                 "B4": [tx([ix("transfer", "CEX", "B4", SOL)])], "B5": None}
        r = F.classify("DEV", dev_page, pages, hub_set={"CEX"})
        b = r["buyers"]
        self.assertTrue(b["B1"]["direct"] and b["B2"]["two_hop"] and b["B3"]["shared_funder"])
        self.assertFalse(b["B4"]["linked"])
        self.assertTrue(b["B5"]["missing"])
        self.assertTrue(r["dev_linked"])
        self.assertFalse(r["coordinated_not_dev"])

    def test_hub_excluded_from_shared_but_not_two_hop_by_default(self):
        dev_page = [tx([ix("transfer", "HUB", "DEV", SOL)]), tx([ix("transfer", "DEV", "HUB", SOL)])]
        pages = {"B1": [tx([ix("transfer", "HUB", "B1", SOL)])]}
        self.assertTrue(F.classify("DEV", dev_page, pages, {"HUB"})["dev_linked"])  # via 2-hop
        r = F.classify("DEV", dev_page, pages, {"HUB"}, hubs_in_2hop=False)
        self.assertFalse(r["dev_linked"])

    def test_coordinated_not_dev(self):
        pages = {"B1": [tx([ix("transfer", "Q", "B1", SOL)])], "B2": [tx([ix("transfer", "Q", "B2", SOL)])]}
        r = F.classify("DEV", [], pages, set())
        self.assertFalse(r["dev_linked"])
        self.assertTrue(r["coordinated_not_dev"])
        self.assertTrue(F.classify("DEV", [], pages, {"Q"})["coordinated_not_dev"] is False)

    def test_hubs(self):
        lf = {i: {"CEX", "x%d" % i} for i in range(5)}
        lf[5] = {"x1"}
        self.assertEqual(F.hubs(lf), {"CEX"})


if __name__ == "__main__":
    unittest.main()
