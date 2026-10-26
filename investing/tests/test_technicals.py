"""trader-technicals: trend, RSI, levels, seasonality on synthetic Yahoo answers."""

import datetime
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import load

tech = load("trader-technicals", "technicals")
UTC = datetime.timezone.utc


def yahoo(points, name="Test Co"):
    """[(date, close)] -> Yahoo chart JSON, timestamps at 09:30 New York."""
    ts = [int(datetime.datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC).timestamp()) for d, _ in points]
    closes = [c for _, c in points]
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": "USD", "symbol": "TEST", "longName": name, "gmtoffset": -14400},
        "timestamp": ts,
        "indicators": {"quote": [{"close": [c * 1.01 if c is not None else None for c in closes]}],
                       "adjclose": [{"adjclose": closes}]}}], "error": None}})


def business_days(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += datetime.timedelta(days=1)
    return out


def month_starts(first_year, last, upto):
    out, y, m = [], first_year, 1
    while (y, m) <= (last, upto):
        out.append(datetime.date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class Math(unittest.TestCase):
    def test_sma_and_rsi(self):
        self.assertEqual(tech.sma([1, 2, 3, 4], 2), 3.5)
        self.assertIsNone(tech.sma([1, 2], 3))
        self.assertEqual(tech.rsi([float(i) for i in range(30)]), 100.0)
        self.assertLess(tech.rsi([float(30 - i) for i in range(30)]), 1)
        self.assertIsNone(tech.rsi([1.0] * 10))

    def test_max_drawdown(self):
        self.assertAlmostEqual(tech.max_drawdown([100, 120, 60, 130, 117]), -50.0)

    def test_trend_labels(self):
        self.assertEqual(tech.trend_label(110, 105, 100, 99)[0], "uptrend")
        self.assertEqual(tech.trend_label(90, 95, 100, 101)[0], "downtrend")
        label, why = tech.trend_label(95, 105, 100, 99)
        self.assertEqual(label, "mixed")
        self.assertIn("price below the 200-day", why)
        self.assertEqual(tech.trend_label(1, None, None, None)[0], "unknown")

    def test_swings(self):
        pts = [(i, c) for i, c in enumerate([5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7, 8, 9, 8, 7, 6, 5, 4])]
        highs, lows = tech.swings(pts)
        self.assertEqual(lows, [(4, 1)])
        self.assertEqual(highs, [(12, 9)])

    def test_brk_b_becomes_yahoo_symbol(self):
        path = tech.chart_path("brk.b", "1mo", datetime.datetime(2026, 10, 26, tzinfo=UTC))
        self.assertTrue(path.startswith("/v8/finance/chart/BRK-B?period1="))
        self.assertIn("interval=1mo", path)


class Seasonality(unittest.TestCase):
    def test_monthly_returns_drop_running_month_and_duplicate_bar(self):
        bars = [(datetime.date(2025, 11, 1), 100.0), (datetime.date(2025, 12, 1), 110.0),
                (datetime.date(2026, 1, 1), 99.0), (datetime.date(2026, 1, 20), 99.0)]
        r = tech.monthly_returns(bars, datetime.date(2026, 1, 20))
        self.assertEqual(list(r), [(2025, 12)])
        self.assertAlmostEqual(r[(2025, 12)], 10.0)

    def test_signal_and_noise_and_excess(self):
        mret, bench = {}, {}
        for y in range(2010, 2025):
            for m in range(1, 13):
                mret[(y, m)] = 5.0 + (y % 3) * 0.5 if m == 11 else (1.0 if y % 2 else -1.0)
                bench[(y, m)] = 1.0
        rows = tech.seasonality(mret, 10, 2024, bench)
        nov, mar = rows[10], rows[2]
        self.assertEqual(nov["n"], 10)
        self.assertTrue(nov["signal"])
        self.assertEqual(nov["up"], 100.0)
        self.assertAlmostEqual(nov["vs_bench"], nov["avg"] - 1.0)
        self.assertFalse(mar["signal"])
        self.assertEqual(mar["up"], 50.0)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        days = business_days(datetime.date(2015, 1, 1), 2900)
        # steady 12 %/year uptrend with a wiggle, so RSI is not pinned at 100
        up = [(d, 100 * 1.12 ** (i / 252) * (1 + 0.01 * math.sin(i))) for i, d in enumerate(days)]
        months = month_starts(2005, days[-1].year, days[-1].month)
        mup = [(d, 100 * (1.01 ** i) * (1.05 if d.month >= 11 else 1.0)) for i, d in enumerate(months)]
        flat = [(d, 100.0 + 0.5 * math.sin(i)) for i, d in enumerate(days)]
        mflat = [(d, 100.0) for d in months]
        for sym, d1, m1 in (("UPCO", up, mup), ("SPY", flat, mflat)):
            with open(os.path.join(self.dir, sym + "-1d.json"), "w") as fh:
                fh.write(yahoo(d1, sym))
            with open(os.path.join(self.dir, sym + "-1mo.json"), "w") as fh:
                fh.write(yahoo(m1, sym))
        self.last = days[-1]

    def test_uptrend_report(self):
        out = os.path.join(self.dir, "trader", "technicals.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = tech.main(["UPCO", "NOPE", "--offline", self.dir, "--out", out])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("UPTREND", text)
        self.assertIn("do not predict returns", text)
        with open(out) as fh:
            doc = json.load(fh)
        r = doc["results"][0]
        self.assertEqual(r["date"], self.last.isoformat())
        self.assertEqual(r["trend"]["label"], "uptrend")
        self.assertAlmostEqual(r["performance"]["cagr_5y"], 12.0, delta=1.0)
        self.assertGreater(r["performance"]["vs_benchmark_1y"], 5)
        self.assertEqual(r["seasonality"]["years"], 15)
        self.assertLess(r["levels"]["from_high_pct"], 0.01)
        self.assertEqual(len(r["seasonality"]["next_months"]), 3)
        self.assertIn("NOPE: no offline file", doc["errors"][0])

    def test_nothing_readable_exits_1(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(tech.main(["NOPE", "--offline", self.dir, "--benchmark", ""]), 1)

    def test_yahoo_error_is_reported(self):
        with self.assertRaises(tech.DataError) as cm:
            tech.parse_chart('{"chart": {"result": null, "error": {"description": "No data found"}}}', "ZZZZ")
        self.assertIn("No data found", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
