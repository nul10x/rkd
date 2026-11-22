import unittest

from research import study5_parse as P


def tx(keys, ins=(), inner=(), pre=(), post=(), t=100):
    return {"blockTime": t, "transaction": {"message": {"accountKeys": [{"pubkey": k} for k in keys], "instructions": list(ins)}},
            "meta": {"innerInstructions": [{"index": 0, "instructions": list(inner)}] if inner else [],
                     "preTokenBalances": list(pre), "postTokenBalances": list(post)}}


def cpmm(accts):
    return {"programId": P.CPMM, "accounts": accts, "data": "x"}


def freeze(acct, mint, auth):
    return {"program": "spl-token", "parsed": {"type": "freezeAccount", "info": {"account": acct, "mint": mint, "freezeAuthority": auth}}}


class Creates(unittest.TestCase):
    def test_base_mint_excludes_quote_and_lp(self):
        t = tx(["PAYER", P.CPMM], [cpmm(["a", "b", "c", "d", P.WSOL, "TOK", "LPMINT", "x"])])
        self.assertEqual(P.cpmm_creates(t), [("TOK", False)])

    def test_launchpad_flag_and_stable_quote(self):
        t = tx(["PAYER", "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"], inner=[cpmm(["a", "b", "c", "d", "TOK", P.USDT, "LP"])])
        self.assertEqual(P.cpmm_creates(t), [("TOK", True)])

    def test_no_cpmm(self):
        self.assertEqual(P.cpmm_creates(tx(["PAYER"])), [])


class Freezes(unittest.TestCase):
    def test_counts_holder_freezes_only(self):
        bal = lambda i, o: {"accountIndex": i, "mint": "M", "owner": o, "uiTokenAmount": {"amount": "1"}}
        t = tx(["AUTH", "ACC1", "ACC2"], [freeze("ACC1", "M", "AUTH"), freeze("ACC2", "M", "AUTH"), freeze("ACC1", "OTHER", "AUTH")],
               pre=[bal(1, "VICTIM"), bal(2, "AUTH")])
        self.assertEqual(P.freeze_events([t], "M", "AUTH"), [(100, "ACC1", "VICTIM")])

    def test_other_signer_ignored(self):
        t = tx(["X", "ACC1"], [freeze("ACC1", "M", "SOMEONE")])
        self.assertEqual(P.freeze_events([t], "M", "AUTH"), [])


class Caps(unittest.TestCase):
    def test_flags(self):
        facts = {"freeze_authority": None, "mint_authority": "A", "program": "token-2022"}
        raw = [{"extension": "transferHook", "state": {"programId": "HOOK"}}, {"extension": "transferHook2"},
               {"extension": "defaultAccountState", "state": {"accountState": "initialized"}}]
        c = P.capabilities(facts, raw)
        self.assertTrue(c["transfer_hook_set"] and c["any_sell_block_capability"] and c["mint_authority"])
        self.assertFalse(c["default_frozen"] or c["freeze_authority"])

    def test_none(self):
        c = P.capabilities({"freeze_authority": None, "mint_authority": None, "program": "spl-token"}, [])
        self.assertFalse(c["any_sell_block_capability"])


if __name__ == "__main__":
    unittest.main()
