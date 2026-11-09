import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

sc = load("trader-broker", "scalable")
ticket = load("trader-broker", "ticket")

SFX = os.path.join(FIX, "trader-broker")
TARGETS = os.path.join(ROOT, "trader-copycat", "targets.example.json")


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


def fx(name):
    with open(os.path.join(SFX, name), encoding="utf-8") as fh:
        return json.load(fh)


class Isin(unittest.TestCase):
    def test_from_cusip(self):
        self.assertEqual(sc.isin_from_cusip("037833100"), "US0378331005")   # Apple
        self.assertEqual(sc.isin_from_cusip("191216100"), "US1912161007")   # Coca-Cola
        self.assertEqual(sc.isin_from_cusip("02079K305"), "US02079K3059")   # Alphabet A

    def test_valid(self):
        self.assertTrue(sc.valid_isin("IE00B4L5Y983"))    # iShares Core MSCI World
        self.assertTrue(sc.valid_isin("DE0007164600"))    # SAP
        self.assertFalse(sc.valid_isin("IE00B4L5Y984"))
        self.assertFalse(sc.valid_isin("AAPL"))

    def test_bad_cusip(self):
        with self.assertRaises(sc.ScalableError):
            sc.isin_from_cusip("1234")

    def test_map_from_copycat_keeps_hand_entries(self):
        with open(TARGETS, encoding="utf-8") as fh:
            targets = json.load(fh)
        m, added, missing = sc.build_map(targets, {"EUNL": "IE00B4L5Y983", "AAPL": "US0378331005"})
        self.assertEqual(m["AXP"], "US0258161092")
        self.assertEqual(m["GOOGL"], "US02079K3059")
        self.assertEqual(m["EUNL"], "IE00B4L5Y983")
        self.assertNotIn("AAPL", added)
        self.assertEqual(missing, [])


class Parsing(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(sc.num("1.234,56"), 1234.56)
        self.assertEqual(sc.num("1,234.56"), 1234.56)
        self.assertEqual(sc.num("12,5"), 12.5)
        self.assertEqual(sc.num("1.234"), 1.234)          # a single dot is a decimal point
        self.assertEqual(sc.num("3.6628"), 3.6628)
        self.assertEqual(sc.num("1.234.567"), 1234567.0)
        self.assertEqual(sc.num({"amount": "7.5", "currency": "EUR"}), 7.5)
        self.assertIsNone(sc.num(None))
        self.assertIsNone(sc.num(True))

    def test_holdings(self):
        rows = sc.parse_holdings(fx("scalable-holdings.json"))
        by = {r["isin"]: r for r in rows}
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(by["US0378331005"]["shares"], 3.6628)
        self.assertAlmostEqual(by["US0378331005"]["price"], 1150.40 / 3.6628, 4)
        self.assertAlmostEqual(by["US0378331005"]["avg_cost"], 292.10)
        self.assertEqual(by["IE00B4L5Y983"]["price"], 107.0)
        self.assertEqual(rows[0]["isin"], "IE00B4L5Y983")   # biggest first

    def test_nested_security_object(self):
        doc = {"positions": [{"security": {"isin": "DE0007164600", "name": "SAP"},
                              "quantity": 2, "marketValue": "450.00"}]}
        rows = sc.parse_holdings(doc)
        self.assertEqual(rows[0]["isin"], "DE0007164600")
        self.assertEqual(rows[0]["price"], 225.0)

    def test_empty_depot(self):
        self.assertEqual(sc.parse_holdings(fx("scalable-holdings-empty.json")), [])

    def test_unknown_rows_next_to_an_empty_list_are_not_an_empty_depot(self):
        with self.assertRaises(sc.ScalableError):
            sc.parse_holdings({"items": [{"securityId": "US0378331005", "quantity": 2}], "crypto_items": []})

    def test_nested_position_is_counted_once(self):
        doc = {"items": [{"security": {"isin": "US0378331005"},
                          "position": {"isin": "US0378331005", "quantity": 2, "price": 100}}]}
        rows = sc.parse_holdings(doc)
        self.assertEqual(rows[0]["shares"], 2)
        self.assertEqual(rows[0]["value"], 200)

    def test_unknown_shape_fails_loudly(self):
        with self.assertRaises(sc.ScalableError):
            sc.parse_holdings({"items": [{"isin": "US0378331005", "weird": 3}]})
        with self.assertRaises(sc.ScalableError):
            sc.parse_holdings({"hello": "world"})

    def test_cash_is_not_buying_power(self):
        self.assertEqual(sc.parse_cash(fx("scalable-cash.json")), 812.35)
        with self.assertRaises(sc.ScalableError):
            sc.parse_cash({"buying_power": "5000"})

    def test_quote_mid(self):
        isin, price = sc.parse_quote(fx("scalable-quote-AXP.json"))
        self.assertEqual(isin, "US0258161092")
        self.assertAlmostEqual(price, 266.30)

    def test_text_that_is_not_json(self):
        with self.assertRaises(sc.ScalableError):
            sc.unwrap({"content": [{"type": "text", "text": "Please reconnect"}]})


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.map = os.path.join(self.tmp, "isin_map.json")
        with open(self.map, "w") as fh:
            json.dump({"isins": {"AAPL": "US0378331005", "KO": "US1912161007", "AXP": "US0258161092"}}, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def sync(self):
        return run(sc, ["sync", "--holdings", os.path.join(SFX, "scalable-holdings.json"),
                        "--cash", os.path.join(SFX, "scalable-cash.json"),
                        "--quote", os.path.join(SFX, "scalable-quote-AXP.json"),
                        "--isin-map", self.map, "--portfolio", os.path.join(self.tmp, "portfolio.json"),
                        "--prices", os.path.join(self.tmp, "prices.json"), "--today", "2026-11-09"])

    def test_writes_portfolio_and_prices_in_eur(self):
        code, out, err = self.sync()
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.tmp, "portfolio.json")) as fh:
            pf = json.load(fh)
        with open(os.path.join(self.tmp, "prices.json")) as fh:
            pr = json.load(fh)
        self.assertEqual(pf["cash"], 812.35)
        self.assertEqual(pf["currency"], "EUR")
        tickers = {p["ticker"] for p in pf["positions"]}
        self.assertEqual(tickers, {"AAPL", "KO", "IE00B4L5Y983"})
        self.assertIn("IE00B4L5Y983", out)          # unmapped ETF is reported
        self.assertAlmostEqual(pr["prices"]["AXP"], 266.3)
        aapl = [p for p in pf["positions"] if p["ticker"] == "AAPL"][0]
        self.assertAlmostEqual(aapl["lots"][0]["cost"], round(292.10 * 3.6628, 2))

    def test_keeps_existing_lots_when_shares_match(self):
        lots = [{"id": "AAPL-1", "date": "2026-10-13", "shares": 3.6628, "cost": 1100.0}]
        with open(os.path.join(self.tmp, "portfolio.json"), "w") as fh:
            json.dump({"cash": 0, "positions": [{"ticker": "AAPL", "shares": 3.6628, "lots": lots}]}, fh)
        self.assertEqual(self.sync()[0], 0)
        with open(os.path.join(self.tmp, "portfolio.json")) as fh:
            pf = json.load(fh)
        aapl = [p for p in pf["positions"] if p["ticker"] == "AAPL"][0]
        self.assertEqual(aapl["lots"], lots)

    def test_rebalance_and_risk_read_the_synced_files(self):
        self.assertEqual(self.sync()[0], 0)
        rebalance = load("trader-rebalance", "rebalance")
        check = load("trader-risk", "check")
        with open(os.path.join(self.tmp, "portfolio.json")) as fh:
            pf = json.load(fh)
        with open(os.path.join(self.tmp, "prices.json")) as fh:
            prices = json.load(fh)["prices"]
        weights = {"IE00B4L5Y983": 70.0, "AAPL": 15.0, "KO": 15.0}
        cfg = {"budget": 5000, "cash_buffer_pct": 5, "max_position_pct": 80, "max_order_usd": 2000,
               "min_order_usd": 25, "max_orders_per_day": 10, "fractional": True, "broker": "scalable"}
        res = rebalance.plan(pf, prices, weights, cfg, band=5)
        self.assertIsInstance(res, dict)
        orders = res["orders"]
        self.assertTrue(orders)
        verdict = check.check(orders, cfg, pf, prices, {}, "2026-11-09")
        self.assertEqual(len(verdict["results"]), len(orders))
        forms = [sc.order_form(o, {"AAPL": "US0378331005", "KO": "US1912161007"}, prices) for o in orders]
        for f in forms:
            self.assertEqual(f["problems"], [], f)


class Tickets(unittest.TestCase):
    MAP = {"AAPL": "US0378331005", "KO": "US1912161007", "EUNL": "IE00B4L5Y983"}

    def test_buy_by_amount(self):
        f = sc.order_form({"symbol": "EUNL", "side": "buy", "notional": "250", "type": "market"}, self.MAP, {})
        self.assertEqual(f["isin"], "IE00B4L5Y983")
        self.assertEqual(f["amount_eur"], 250.0)
        self.assertEqual(f["preview_tool"], "preview_buy_order")
        self.assertEqual(f["problems"], [])

    def test_sell_is_share_based(self):
        f = sc.order_form({"symbol": "KO", "side": "sell", "notional": "200", "type": "market"}, self.MAP,
                          {"KO": 77.14})
        self.assertEqual(f["shares"], 2.5926)
        g = sc.order_form({"symbol": "KO", "side": "sell", "notional": "200", "type": "market"}, self.MAP, {})
        self.assertTrue(g["problems"])

    def test_problems(self):
        self.assertTrue(sc.order_form({"symbol": "XYZ", "side": "buy", "notional": "10"}, self.MAP, {})["problems"])
        self.assertTrue(sc.order_form({"symbol": "AAPL", "side": "buy", "qty": "1.5"}, self.MAP, {})["problems"])
        self.assertTrue(sc.order_form({"symbol": "AAPL", "side": "buy", "notional": "10", "type": "stop"},
                                      self.MAP, {})["problems"])

    def test_cli(self):
        tmp = tempfile.mkdtemp()
        try:
            orders = os.path.join(tmp, "orders.json")
            m = os.path.join(tmp, "isin_map.json")
            with open(orders, "w") as fh:
                json.dump({"orders": [{"symbol": "EUNL", "side": "buy", "notional": 250, "type": "market",
                                       "time_in_force": "day"}]}, fh)
            with open(m, "w") as fh:
                json.dump({"isins": self.MAP}, fh)
            code, out, err = run(sc, ["tickets", "--orders", orders, "--isin-map", m,
                                      "--prices", os.path.join(tmp, "none.json")])
            self.assertEqual(code, 0, err)
            self.assertIn("IE00B4L5Y983", out)
            self.assertIn("250,00 EUR", out)
        finally:
            shutil.rmtree(tmp)


class TicketScalable(unittest.TestCase):
    def test_german_yes(self):
        o = {"symbol": "KO", "side": "buy", "notional": "200", "type": "market", "time_in_force": "day"}
        self.assertTrue(ticket.parse_yes("ja", o, ["KO", "AAPL"])[0])
        for r in ("ja alle", "ja aber später", "nein", "ja, wenn es fällt", "vielleicht"):
            self.assertFalse(ticket.parse_yes(r, o, ["KO", "AAPL"])[0], r)

    def test_euro_ticket(self):
        o = {"symbol": "KO", "side": "buy", "notional": "200", "type": "market", "time_in_force": "day"}
        self.assertEqual(ticket.plain(o, ticket.currency({"broker": "scalable"})),
                         "BUY 200 EUR of KO, market order, good for today")
        j = ticket.ticket_json(o, 1, {"broker": "scalable"}, None, {"orders": []}, "2026-11-09")
        self.assertEqual(j["tool"], "preview_buy_order")
        self.assertFalse(j["paper"])


if __name__ == "__main__":
    unittest.main()
