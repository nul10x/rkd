"""token_scanner tests. No network: fixtures are real responses recorded 2026-11-22 (see fixtures/*/)."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from collectors import client
from tools.token_scanner import cli, token_scanner as ts

FX = Path(__file__).parent / "fixtures"
GRAD = "FiVRbrKNxzVotLBc8QMrhEJSK9qtF3uu5QkY3GcHpump"
CURVE = "5XQU1muH94yyTJCCgHp2Smh6UoVaSSz9YrJ16bk6pump"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
NOW = 1795308200.0


def run(mint, case, *extra):
    with tempfile.TemporaryDirectory() as d:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main([mint, "--fixtures", str(FX / case), "--now", str(NOW), "--out", d] + list(extra))
        saved = list(Path(d).rglob("*.json"))
        return code, out.getvalue(), err.getvalue(), saved


def report(mint, case):
    code, out, _, _ = run(mint, case)
    return code, json.loads(out)


def pair(dex, base, addr="P1", liq=None, vol=None, buys=1, sells=1, created=None):
    p = {"dexId": dex, "pairAddress": addr, "baseToken": {"address": base}, "quoteToken": {"symbol": "SOL"},
         "txns": {"h24": {"buys": buys, "sells": sells}}, "volume": {"h24": vol}, "priceUsd": "1"}
    if liq is not None:
        p["liquidity"] = {"usd": liq}
    if created:
        p["pairCreatedAt"] = created
    return p


class PureLogicTest(unittest.TestCase):
    def test_valid_mint(self):
        self.assertTrue(ts.valid_mint(GRAD))
        for bad in ("", "abc", "0" * 44, GRAD + "!", None, "O" * 40):
            self.assertFalse(ts.valid_mint(bad))

    def test_main_pair_rule_and_null_liquidity(self):
        ps = [pair("a", "M", "A", liq=5, vol=100), pair("b", "M", "B", liq=9, vol=1)]
        self.assertEqual(ts.main_pair(ps)[0]["pairAddress"], "B")
        ps = [pair("a", "M", "A", vol=100), pair("b", "M", "B", vol=1)]
        mp, rule = ts.main_pair(ps)
        self.assertEqual(mp["pairAddress"], "A")
        self.assertIn("no pair reports liquidity", rule)
        mkt, missing = ts.market(ps, 0, "M")
        self.assertIsNone(mkt["main_pair"]["liquidity_usd"])  # unknown, never 0
        self.assertIn("liquidity_usd", [m["field"] for m in missing])

    def test_quote_side_pairs_are_ignored(self):
        mkt, _ = ts.market([pair("raydium", "OTHER", liq=10), pair("orca", "M", "B", liq=1)], 0, "M")
        self.assertEqual(mkt["pairs_listed"], 1)
        self.assertEqual(mkt["quote_side_pairs_ignored"], 1)
        self.assertIsNone(mkt["graduated_listing"])  # not a Pump.fun token

    def test_missing_volume_makes_total_unknown(self):
        mkt, _ = ts.market([pair("a", "M", "A", vol=5), pair("b", "M", "B", vol=None)], 0, "M")
        self.assertIsNone(mkt["totals_h24"]["volume_usd"])
        self.assertEqual(mkt["totals_h24"]["buys"], 2)

    def test_token2022_extension_flags(self):
        acct = {"owner": ts.TOKEN_2022, "data": {"parsed": {"type": "mint", "info": {
            "decimals": 6, "supply": "100", "mintAuthority": None, "freezeAuthority": None, "extensions": [
                {"extension": "metadataPointer", "state": {}},
                {"extension": "transferHook", "state": {"programId": "HookProg", "authority": "X"}},
                {"extension": "transferHook", "state": {"programId": None}},
                {"extension": "permanentDelegate", "state": {"delegate": "Del"}},
                {"extension": "defaultAccountState", "state": {"accountState": "initialized"}},
                {"extension": "transferFeeConfig", "state": {"newerTransferFee": {"transferFeeBasisPoints": 500}}},
                {"extension": "somethingNew", "state": {}}]}}}}
        facts, flags, missing = ts.mint_facts(acct)
        codes = sorted(f["code"] for f in flags)
        self.assertEqual(codes, ["permanent_delegate", "transfer_fee", "transfer_hook", "unrecognised_extension"])
        self.assertTrue(all(f["class"] == "fact" for f in flags))
        self.assertEqual(facts["program"], "token-2022")

    def test_not_a_mint(self):
        _, _, missing = ts.mint_facts({"owner": "x", "data": {"parsed": {"type": "account", "info": {}}}})
        self.assertEqual(missing[0]["field"], "mint")
        _, _, missing = ts.mint_facts(None)
        self.assertIn("not found", missing[0]["reason"])

    def test_holders_excludes_venues_and_groups_by_owner(self):
        largest = [{"address": "t1", "amount": "50"}, {"address": "t2", "amount": "20"},
                   {"address": "t3", "amount": "15"}, {"address": "t4", "amount": "5"}]
        own = lambda o: {"data": {"parsed": {"info": {"owner": o}}}}
        res, flags, missing = ts.holders(largest, [own("POOL"), own("W1"), own("W1"), None], 100, {"POOL": "pumpswap"})
        self.assertEqual(res["venue_pct"], 50.0)
        self.assertEqual(res["top1_holder_pct_excl_venues"], 35.0)  # W1 owns two accounts
        self.assertEqual(res["top10_holders_pct_excl_venues"], 40.0)
        self.assertEqual(res["unresolved_owners"], 1)
        self.assertEqual([f["class"] for f in flags], ["heuristic", "heuristic"])
        self.assertIn("holder_owners", [m["field"] for m in missing])


class OfflineEndToEndTest(unittest.TestCase):
    def test_graduate(self):
        code, r = report(GRAD, "graduate")
        self.assertEqual(code, 0)
        self.assertEqual((r["tool"], r["version"]), ("token_scanner", ts.VERSION))
        self.assertIn("KR-000038", r["findings"])
        lc = r["launch_context"]
        self.assertTrue(lc["graduated_listing"])
        self.assertEqual(lc["block0_buyers"], 4)
        self.assertAlmostEqual(lc["block0_supply_share_pct"], 15.16, places=2)
        self.assertFalse(lc["same_slot_graduation"])
        h = r["holders"]
        self.assertAlmostEqual(h["venue_pct"], 13.71, places=2)
        self.assertAlmostEqual(h["top1_holder_pct_excl_venues"], 3.72, places=2)
        self.assertAlmostEqual(h["top10_holders_pct_excl_venues"], 27.55, places=2)
        self.assertEqual(r["market"]["main_pair"]["dex"], "pumpswap")
        self.assertIsNone(r["permissions"]["mint_authority"])
        self.assertEqual(r["missing"], [])
        self.assertTrue(all("fetched_at" in s for s in r["sources"]))

    def test_curve_token_liquidity_unknown(self):
        code, r = report(CURVE, "curve")
        self.assertEqual(code, 0)
        self.assertIsNone(r["market"]["main_pair"]["liquidity_usd"])
        self.assertIsNone(r["ratios"]["liquidity_to_mc"])
        self.assertIn("liquidity_usd", [m["field"] for m in r["missing"]])
        self.assertFalse(r["launch_context"]["graduated_listing"])
        self.assertEqual(r["launch_context"]["block0_buyers"], 2)
        self.assertGreater(r["holders"]["venue_pct"], 99.9)  # bonding curve holds the supply

    def test_usdc_facts_and_partial_failure(self):
        code, r = report(USDC, "usdc")
        self.assertEqual(code, 0)
        codes = [f["code"] for f in r["risk_flags"]]
        self.assertEqual(codes, ["mint_authority_present"])  # 0.2.0: stablecoin freeze authority not flagged
        self.assertIn("USDC", r["not_flagged"][0])
        self.assertEqual(r["permissions"]["freeze_authority"], "7dGbd2QZcCKcTndnHcTL8q7SMVXAkp688NTQYwrRCrar")
        self.assertEqual(r["permissions"]["program"], "spl-token")
        self.assertIsNone(r["holders"])
        self.assertIsNone(r["launch_context"])  # not a Pump.fun launch, no creation-page call
        self.assertIn("refuses a largest-holders query", {m["field"]: m["reason"] for m in r["missing"]}["holders"])

    def test_deterministic_and_saved(self):
        a = run(GRAD, "graduate")
        b = run(GRAD, "graduate")
        self.assertEqual(a[1], b[1])
        self.assertEqual(len(a[3]), 1)

    def test_text_is_discord_sized_and_flags_first(self):
        code, out, _, _ = run(GRAD, "graduate", "--text")
        self.assertLessEqual(len(out), 4000)
        self.assertLess(out.index("Risk flags"), out.index("Market"))
        self.assertIn("Not a rating", out)
        for word in ("safe", "profitable", "buy now", "gem"):
            self.assertNotIn(word, out.lower().replace("not a safety verdict", ""))


class FailurePathTest(unittest.TestCase):
    def test_invalid_mint_exit_2_no_calls(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["not-a-mint", "--fixtures", str(FX / "graduate")]), 2)

    def test_rate_limit_stops_remaining_calls(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("pairs", "account", "largest", "owners", "first_page"):
                (Path(d) / (n + ".json")).write_text((FX / "graduate" / (n + ".json")).read_text())
            (Path(d) / "account.json").write_text(json.dumps(
                {"error": {"type": "RateLimited", "message": "helius HTTP 429; paused for 900 s"}}))
            code, out, _, _ = run(GRAD, d)
            r = json.loads(out)
            self.assertEqual(code, 0)
            reasons = {m["field"]: m["reason"] for m in r["missing"]}
            for f in ("mint", "holders", "launch_context"):
                self.assertIn("RateLimited", reasons[f])
            self.assertEqual([s["provider"] for s in r["sources"]], ["dexscreener"])

    def test_review_3_logbook_budget_errors_stop_cleanly(self):
        """Finding 3: with RKD_LOGBOOK_COUNT=1 the ecosystem's ProviderPaused/BudgetExceeded escaped scan()."""
        from ecosystem import tasks

        class Api(cli.FixtureApi):
            def account(self, mint):
                raise tasks.ProviderPaused("helius reached its daily cap of 5")

            def pairs(self, mint):
                raise tasks.BudgetExceeded("T-1 over budget for api_calls (1/1)")
        r, nothing = cli.scan(GRAD, Api(FX / "graduate"), NOW)
        self.assertTrue(nothing)
        reasons = {m["field"]: m["reason"] for m in r["missing"]}
        self.assertIn("BudgetExceeded", reasons["market"])
        for f in ("mint", "holders", "launch_context"):
            self.assertIn("not fetched: run stopped", reasons[f])

    def test_nothing_fetched_exit_3(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _, _ = run(GRAD, d)
            self.assertEqual(code, 3)
            self.assertIsNone(json.loads(out)["market"])

    def test_live_api_uses_daily_usage_file_and_budget(self):
        old = (client.USAGE, client.BUDGET)
        try:
            os.environ["RKD_SCANNER_DAILY_BUDGET"] = "7"
            cli.LiveApi()
            self.assertRegex(os.path.basename(client.USAGE), r"^usage_token_scanner_\d{4}-\d\d-\d\d\.json$")
            self.assertEqual(client.BUDGET, 7)
        finally:
            client.USAGE, client.BUDGET = old
            os.environ.pop("RKD_SCANNER_DAILY_BUDGET", None)


class ValidatorReportTest(unittest.TestCase):
    """Regressions for Validator report KR-000043 (B1, N1, N2) on master 6bbdeca."""

    def _case(self, mutate):
        d = tempfile.mkdtemp()
        for f in (FX / "graduate").iterdir():
            (Path(d) / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        mutate(Path(d))
        return d

    def _check_venues_unknown(self, d):
        code, out, _, _ = run(GRAD, d)
        r = json.loads(out)
        codes = [f["code"] for f in r["risk_flags"]]
        self.assertNotIn("top1_holder_concentration", codes)
        self.assertNotIn("top10_holder_concentration", codes)
        h = r["holders"]
        self.assertFalse(h["venues_known"])
        self.assertIsNone(h["venue_pct"])
        self.assertIsNone(h["top1_holder_pct_excl_venues"])
        self.assertAlmostEqual(h["top1_pct_incl_venues"], 13.71, places=2)  # the pool, reported as an account
        self.assertIn("holder_venues", [m["field"] for m in r["missing"]])
        _, text, _, _ = run(GRAD, d, "--text")
        self.assertNotIn("0.00%", text)
        self.assertNotIn("non-venue wallet", text)
        self.assertIn("venues unknown", text)

    def test_b1_no_pairs_listed(self):
        def empty(d):
            snap = json.loads((d / "pairs.json").read_text(encoding="utf-8"))
            snap["response"] = []
            (d / "pairs.json").write_text(json.dumps(snap), encoding="utf-8")
        self._check_venues_unknown(self._case(empty))

    def test_b1_pairs_fetch_failed(self):
        self._check_venues_unknown(self._case(lambda d: (d / "pairs.json").unlink()))

    def test_b1_listed_pairs_unchanged(self):
        code, r = report(GRAD, "graduate")
        self.assertTrue(r["holders"]["venues_known"])
        self.assertAlmostEqual(r["holders"]["venue_pct"], 13.71, places=2)

    def test_n1_block0_wording_says_received(self):
        code, r = report(GRAD, "graduate")
        f = next(f for f in r["risk_flags"] if f["code"] == "block0_buyers")
        self.assertIn("received", f["text"])
        self.assertNotIn("bought", f["text"])

    def test_n2_fixture_for_another_mint_is_rejected(self):
        code, out, _, _ = run(CURVE, "graduate")
        r = json.loads(out)
        self.assertIsNone(r["permissions"])
        self.assertIsNone(r["holders"])
        reasons = {m["field"]: m["reason"] for m in r["missing"]}
        self.assertIn("another mint", reasons["mint"])
        self.assertIn("another mint", reasons["market"])


class RiskSignalsV1Test(unittest.TestCase):
    """docs/RISK_SIGNALS.md v1 (Researcher): labels, records, timestamps, freeze-authority scope rule."""

    def _with_freeze(self):
        d = Path(tempfile.mkdtemp())
        for f in (FX / "graduate").iterdir():
            (d / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        snap = json.loads((d / "account.json").read_text(encoding="utf-8"))
        snap["response"]["result"]["value"]["data"]["parsed"]["info"]["freezeAuthority"] = "FrzAuth1111111111111111111111111111111111111"
        (d / "account.json").write_text(json.dumps(snap), encoding="utf-8")
        return d

    def test_freeze_flagged_on_new_mint_with_label_records_and_time(self):
        d = self._with_freeze()
        _, out, _, _ = run(GRAD, d)  # graduate fixture: mint age 10.4 days
        r = json.loads(out)
        f = next(f for f in r["risk_flags"] if f["code"] == "freeze_authority_present")
        self.assertEqual(f["label"], "fact · capability")
        self.assertIn("KR-000046", f["records"])
        self.assertEqual(f["source"], "helius getAccountInfo")
        self.assertIsInstance(f["fetched_at"], (int, float))
        self.assertIn("can freeze holders", f["text"])
        self.assertIn("not a confirmed honeypot", f["text"])
        self.assertIn("0.46%", f["context"])
        self.assertIn("freeze_used", [m["field"] for m in r["missing"]])

    def test_freeze_not_flagged_on_mint_older_than_30_days(self):
        d = self._with_freeze()
        with tempfile.TemporaryDirectory() as o:
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
                cli.main([GRAD, "--fixtures", str(d), "--now", str(NOW + 40 * 86400), "--out", o])
        r = json.loads(out.getvalue())
        self.assertNotIn("freeze_authority_present", [f["code"] for f in r["risk_flags"]])
        self.assertIn("older than 30 days", r["not_flagged"][0])
        self.assertNotIn("freeze_used", [m["field"] for m in r["missing"]])

    def test_freeze_with_unknown_age_is_flagged_as_new(self):
        acct = {"value": {"owner": ts.SPL_TOKEN, "data": {"parsed": {"type": "mint", "info": {
            "decimals": 6, "supply": "100", "mintAuthority": None, "freezeAuthority": "Frz"}}}}}
        r = ts.build_report(GRAD, NOW, mint_acct=acct)
        f = next(f for f in r["risk_flags"] if f["code"] == "freeze_authority_present")
        self.assertIn("mint age unknown, treated as new", f["text"])
        self.assertIsNone(f["fetched_at"])  # no source recorded: not invented

    def test_every_flag_has_label_and_records(self):
        for mint, case in ((GRAD, "graduate"), (CURVE, "curve"), (USDC, "usdc")):
            _, r = report(mint, case)
            for f in r["risk_flags"]:
                self.assertTrue(f["label"] and f["records"] and f["source"], f)
            self.assertIn("RISK_SIGNALS", r["risk_spec"])

    def test_no_flag_text_says_not_seen_not_safe(self):
        r = ts.build_report(GRAD, NOW)
        text = ts.render_text(r)
        self.assertIn("none seen in the data read", text)
        for word in ("safe ", "legit", "rug-proof", "will pump"):
            self.assertNotIn(word, text.lower().replace("not a safety verdict", ""))


if __name__ == "__main__":
    unittest.main()
