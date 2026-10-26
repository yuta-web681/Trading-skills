"""trader-technicals setups: stage 2, VCP, gaps and catalysts, Multi-Edge, PEAD, bursts, volume."""

import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load

st = load("trader-technicals", "setups")
UTC = datetime.timezone.utc


def business_days(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += datetime.timedelta(days=1)
    return out


def path(start, legs):
    """Piecewise straight closes: legs = [(days, target)]."""
    out, x = [], start
    for n, target in legs:
        step = (target - x) / n
        for _ in range(n):
            x += step
            out.append(x)
    return out


def make(closes, vols=None, first=datetime.date(2024, 1, 1)):
    days = business_days(first, len(closes))
    vols = vols or [1000000] * len(closes)
    bars, prev = [], closes[0]
    for d, c, v in zip(days, closes, vols):
        o = prev
        bars.append(st.Bar(d, o, max(o, c) * 1.003, min(o, c) * 0.997, c, v))
        prev = c
    return bars


def gap_day(bars, gap=6.0, day=8.0, vol=4000000, clv=0.9):
    """Append a gap-up day to bars."""
    p = bars[-1]
    o = p.c * (1 + gap / 100)
    c = p.c * (1 + day / 100)
    lo = min(o, c) * 0.995
    hi = lo + (c - lo) / clv
    d = p.d + datetime.timedelta(days=3 if p.d.weekday() == 4 else 1)
    bars.append(st.Bar(d, o, hi, lo, c, vol))
    return bars


def extend(bars, closes, vol=1000000):
    prev, d = bars[-1].c, bars[-1].d
    for c in closes:
        d += datetime.timedelta(days=3 if d.weekday() == 4 else 1)
        bars.append(st.Bar(d, prev, max(prev, c) * 1.003, min(prev, c) * 0.997, c, vol))
        prev = c
    return bars


def to_yahoo(bars, name="Test Co"):
    ts = [int(datetime.datetime(b.d.year, b.d.month, b.d.day, 13, 30, tzinfo=UTC).timestamp()) for b in bars]
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": "USD", "longName": name, "gmtoffset": -14400}, "timestamp": ts,
        "indicators": {"quote": [{"open": [b.o for b in bars], "high": [b.h for b in bars],
                                  "low": [b.l for b in bars], "close": [b.c for b in bars],
                                  "volume": [b.v for b in bars]}],
                       "adjclose": [{"adjclose": [b.c for b in bars]}]}}], "error": None}})


def flat_bench(bars, level=100.0):
    return [(b.d, level) for b in bars]


def uptrend_then_vcp():
    closes = path(50, [(250, 100)]) + path(100, [(10, 80), (10, 98), (6, 88.2), (6, 97), (4, 93.1), (4, 96)])
    vols = [1000000] * 250 + [1500000] * 20 + [900000] * 12 + [400000] * 8
    return make(closes, vols)


def gap_and_pullback():
    bars = make(path(50, [(300, 80)]))
    gap_day(bars, gap=6, day=8)                                   # catalyst gap on 4x volume
    extend(bars, path(bars[-1].c, [(8, 95)]), vol=1300000)         # run
    extend(bars, path(95, [(7, 88)]), vol=600000)                 # quiet pullback
    return bars


class Parse(unittest.TestCase):
    def test_open_high_low_follow_the_adjusted_close(self):
        doc = {"chart": {"result": [{"meta": {"currency": "USD", "gmtoffset": 0},
                                     "timestamp": [1700000000, 1700086400, 1700172800],
                                     "indicators": {"quote": [{"open": [10, None, 11], "high": [11, 12, 12],
                                                               "low": [9, 10, 10], "close": [10, 11, 12],
                                                               "volume": [100, 200, 300]}],
                                                    "adjclose": [{"adjclose": [5, 5.5, 6]}]}}], "error": None}}
        bars, meta = st.parse_ohlcv(json.dumps(doc), "X")
        self.assertEqual(len(bars), 2)  # the bar without an open is dropped
        self.assertAlmostEqual(bars[0].o, 5.0)
        self.assertAlmostEqual(bars[0].h, 5.5)
        self.assertAlmostEqual(bars[1].l, 5.0)
        self.assertEqual(bars[1].v, 300)

    def test_errors(self):
        with self.assertRaises(st.T.DataError):
            st.parse_ohlcv("nope", "X")
        with self.assertRaises(st.T.DataError):
            st.parse_ohlcv(json.dumps({"chart": {"result": None, "error": {"description": "No data"}}}), "X")


class Math(unittest.TestCase):
    def test_zigzag_finds_the_turns(self):
        bars = make(path(100, [(10, 120), (10, 100), (10, 115)]))
        piv = st.zigzag(bars, 5)
        self.assertEqual([p[2] for p in piv], ["L", "H", "L", "H"])
        self.assertAlmostEqual(piv[1][1], 120 * 1.003, places=2)
        self.assertFalse(piv[-1][3])  # the running high is not confirmed

    def test_ema_atr_clv(self):
        e = st.ema_series([1.0] * 5 + [2.0] * 50, 10)
        self.assertIsNone(e[8])
        self.assertAlmostEqual(e[-1], 2.0, places=3)
        self.assertIsNone(st.atr(make([1.0] * 5)))
        b = st.Bar(None, 10, 12, 8, 11, 0)
        self.assertAlmostEqual(st.clv(b), 0.75)


class Stage(unittest.TestCase):
    def test_steady_uptrend_is_stage_2(self):
        bars = make(path(50, [(300, 100)]))
        r = st.trend_template(bars, flat_bench(bars))
        self.assertEqual(r["stage"], "stage 2")
        self.assertEqual(r["passed"], 8)
        self.assertGreater(r["rs_vs_bench"], 5)

    def test_downtrend_is_stage_4(self):
        bars = make(path(100, [(300, 50)]))
        r = st.trend_template(bars, flat_bench(bars))
        self.assertEqual(r["stage"], "stage 4 (falling 200-day)")
        self.assertIn("price above the 50-day", r["failed"])

    def test_without_benchmark_seven_of_seven_is_enough(self):
        r = st.trend_template(make(path(50, [(300, 100)])))
        self.assertEqual(r["stage"], "stage 2")
        self.assertIn("relative strength vs SPY at least +5 points", r["unknown"])


class Vcp(unittest.TestCase):
    def test_three_tighter_waves_near_the_pivot(self):
        bars = uptrend_then_vcp()
        r = st.vcp(bars, atr_val=st.atr(bars))
        self.assertTrue(r["valid"], r.get("why"))
        self.assertEqual(len(r["depths"]), 3)
        self.assertGreater(r["depths"][0], 18)
        self.assertLess(r["depths"][2], 6)
        self.assertEqual(r["state"], "near pivot")
        self.assertLess(r["dryup"], 0.7)
        self.assertLess(r["stop"], r["pivot"])

    def test_breakout_on_volume(self):
        bars = uptrend_then_vcp()
        r0 = st.vcp(bars, atr_val=st.atr(bars))
        extend(bars, [r0["pivot"] * 1.02], vol=3000000)
        r = st.vcp(bars, atr_val=st.atr(bars))
        self.assertEqual(r["state"], "breakout")
        self.assertGreater(r["breakout_volume"], 1.4)

    def test_wider_waves_are_no_vcp(self):
        closes = path(50, [(250, 100)]) + path(100, [(8, 92), (8, 99), (10, 80), (10, 95)])
        r = st.vcp(make(closes))
        self.assertFalse(r.get("valid"))
        self.assertIn("not getting tighter", r["why"])

    def test_fresh_high_has_no_base(self):
        r = st.vcp(make(path(50, [(300, 100)])))
        self.assertEqual(r["state"], "none")


class Gaps(unittest.TestCase):
    def test_episodic_pivot_and_its_catalyst(self):
        bars = make(path(50, [(300, 80)]))
        gap_day(bars)
        extend(bars, [87, 88])
        d = bars[-3].d
        filings = [(d - datetime.timedelta(days=1), "8-K", "2.02,9.01"),
                   (d - datetime.timedelta(days=30), "8-K", "5.02")]
        g = st.gaps(bars, sec_filings=filings)
        self.assertEqual(len(g), 1)
        self.assertTrue(g[0]["ep"])
        self.assertAlmostEqual(g[0]["gap_pct"], 6.0, places=1)
        self.assertAlmostEqual(g[0]["volume_x"], 4.0, places=1)
        self.assertEqual(g[0]["held"], "holding")
        self.assertTrue(g[0]["catalyst"]["earnings"])
        self.assertEqual(g[0]["catalyst"]["what"], "earnings")

    def test_small_or_quiet_gaps_do_not_count(self):
        bars = make(path(50, [(300, 80)]))
        gap_day(bars, gap=2.0, day=3.0)
        gap_day(bars, gap=5.0, day=6.0, vol=1200000)
        self.assertEqual(st.gaps(bars), [])

    def test_weak_close_is_a_gap_but_no_ep(self):
        bars = make(path(50, [(300, 80)]))
        gap_day(bars, clv=0.3, day=6.5)
        g = st.gaps(bars)
        self.assertFalse(g[0]["ep"])

    def test_catalyst_window(self):
        d = datetime.date(2026, 8, 27)
        self.assertIsNone(st.catalyst_for(d, [(d - datetime.timedelta(days=6), "8-K", "2.02")]))
        c = st.catalyst_for(d, [(d, "8-K", "8.01"), (d - datetime.timedelta(days=1), "8-K", "2.02,9.01")])
        self.assertTrue(c["earnings"])  # earnings win over a later other event
        c = st.catalyst_for(d, [(d, "6-K", "")])
        self.assertEqual(c["what"], "foreign issuer report")


class MultiEdge(unittest.TestCase):
    def test_quiet_pullback_to_the_20_ema_is_a_setup(self):
        bars = gap_and_pullback()
        g = st.gaps(bars)[-1]
        ema = st.ema_series([b.c for b in bars], 20)[-1]
        last = bars[-1]
        bars[-1] = st.Bar(last.d, last.o, last.h, ema * 1.002, last.c, last.v)  # touch the EMA
        r = st.multi_edge(bars, g)
        self.assertEqual(r["state"], "setup", r.get("why"))
        self.assertLess(r["pullback_volume_x"], 1.0)
        p = r["plan"]
        self.assertLess(p["stop"], p["entry"])
        self.assertAlmostEqual(p["target_2r"] - p["entry"], 2 * (p["entry"] - p["stop"]))
        self.assertIn("catalyst not checked", r["note"])

    def test_close_above_the_prior_high_triggers(self):
        bars = gap_and_pullback()
        ema = st.ema_series([b.c for b in bars], 20)[-1]
        prev = bars[-1]
        extend(bars, [prev.h * 1.01], vol=900000)
        last = bars[-1]
        bars[-1] = st.Bar(last.d, last.o, last.h, min(last.l, ema * 1.002), last.c, last.v)
        r = st.multi_edge(bars, st.gaps(bars)[-1])
        self.assertEqual(r["state"], "triggered", r.get("why"))

    def test_running_failed_expired(self):
        bars = make(path(50, [(300, 80)]))
        gap_day(bars)
        extend(bars, path(bars[-1].c, [(5, 95)]))
        self.assertEqual(st.multi_edge(bars, st.gaps(bars)[-1])["state"], "running")
        g = st.gaps(bars)[-1]
        extend(bars, [g["low"] * 0.97])
        self.assertEqual(st.multi_edge(bars, g)["state"], "failed")
        bars = make(path(50, [(300, 80)]))
        gap_day(bars)
        extend(bars, path(bars[-1].c, [(45, 100)]))
        self.assertEqual(st.multi_edge(bars, st.gaps(bars, window=60)[-1])["state"], "expired")
        self.assertEqual(st.multi_edge(bars, None)["state"], "none")

    def test_heavy_pullback_is_loose(self):
        bars = make(path(50, [(300, 80)]))
        gap_day(bars)
        extend(bars, path(bars[-1].c, [(8, 95)]), vol=1300000)
        extend(bars, path(95, [(7, 88)]), vol=2500000)
        ema = st.ema_series([b.c for b in bars], 20)[-1]
        last = bars[-1]
        bars[-1] = st.Bar(last.d, last.o, last.h, ema * 1.002, last.c, last.v)
        r = st.multi_edge(bars, st.gaps(bars)[-1])
        self.assertEqual(r["state"], "loose")
        self.assertIn("pullback volume", r["why"])


class Pead(unittest.TestCase):
    def build(self):
        bars = make(path(50, [(300, 80)]), first=datetime.date(2024, 1, 1))
        while bars[-1].d.weekday() != 4:  # end on a Friday
            extend(bars, [bars[-1].c])
        gap_day(bars)                                      # Monday gap
        extend(bars, path(bars[-1].c, [(4, 90)]))          # green rest of the gap week
        extend(bars, path(90, [(5, 94)]))                  # green week
        wk = []
        prev = bars[-1].c
        d = bars[-1].d
        for c in (93, 92, 91, 90.5, 90):                   # red week: open 94, close 90
            d += datetime.timedelta(days=3 if d.weekday() == 4 else 1)
            wk.append(st.Bar(d, prev, prev * 1.003, c * 0.997, c, 900000))
            prev = c
        bars.extend(wk)
        return bars

    def test_red_week_then_signal_then_breakout(self):
        bars = self.build()
        g = st.gaps(bars)[-1]
        r = st.pead(bars, g)
        self.assertEqual(r["state"], "signal ready")
        self.assertAlmostEqual(r["entry"], 94 * 1.003, places=2)
        extend(bars, [92, 94, 95, 96, 97])                 # next week closes above the red high
        r = st.pead(bars, g)
        self.assertEqual(r["state"], "breakout")

    def test_monitoring_and_expired(self):
        bars = make(path(50, [(300, 80)]))
        while bars[-1].d.weekday() != 4:
            extend(bars, [bars[-1].c])
        gap_day(bars)
        extend(bars, path(bars[-1].c, [(9, 95)]))
        self.assertEqual(st.pead(bars, st.gaps(bars)[-1])["state"], "monitoring")
        extend(bars, path(95, [(30, 110)]))
        self.assertEqual(st.pead(bars, st.gaps(bars)[-1])["state"], "expired")


class BurstAndVolume(unittest.TestCase):
    def test_four_percent_burst(self):
        bars = make(path(50, [(100, 60)]) + [60, 59.5, 60.1, 59.8])
        extend(bars, [63.0], vol=2000000)
        b = st.bursts(bars)
        self.assertEqual(len(b), 1)
        self.assertGreater(b[0]["change_pct"], 4)

    def test_no_burst_after_three_up_days(self):
        bars = make(path(50, [(100, 60)]) + [60.5, 61, 61.5])
        extend(bars, [64.5], vol=2000000)
        self.assertEqual(st.bursts(bars), [])

    def test_volume_counts(self):
        bars = make([10 + (i % 2) for i in range(60)])
        v = st.volume(bars)
        self.assertAlmostEqual(v["relative"], 1.0)
        self.assertAlmostEqual(v["up_down_50"], 1.0)
        self.assertEqual(v["distribution_25"], 0)


class Cli(unittest.TestCase):
    def test_offline_run_with_sec_catalyst(self):
        bars = gap_and_pullback()
        bench = make([100.0] * len(bars))
        gap_date = st.gaps(bars)[-1]["date"]
        with tempfile.TemporaryDirectory() as tmp:
            for t, b in (("TEST", bars), ("SPY", bench)):
                with open(os.path.join(tmp, "%s-1d.json" % t), "w") as fh:
                    fh.write(to_yahoo(b))
            with open(os.path.join(tmp, "company_tickers.json"), "w") as fh:
                json.dump({"0": {"cik_str": 1234, "ticker": "TEST", "title": "Test Co"}}, fh)
            with open(os.path.join(tmp, "submissions-CIK0000001234.json"), "w") as fh:
                json.dump({"filings": {"recent": {"form": ["8-K", "10-Q"], "filingDate": [gap_date, gap_date],
                                                  "items": ["2.02,9.01", ""]}}}, fh)
            out = os.path.join(tmp, "trader", "setups.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = st.main(["TEST", "--offline", tmp, "--out", out])
            self.assertEqual(code, 0)
            text = buf.getvalue()
            self.assertIn("8-K %s earnings" % gap_date, text)
            self.assertIn("multi-edge", text)
            self.assertIn("STAGE 2", text)
            with open(out) as fh:
                doc = json.load(fh)
            r = doc["results"][0]
            self.assertEqual(r["catalyst_source"], "SEC EDGAR 8-K/6-K")
            self.assertTrue(r["gaps"][-1]["catalyst"]["earnings"])

    def test_missing_ticker_fails_and_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            for t in ("AAA", "BBB"):
                with open(os.path.join(tmp, "%s-1d.json" % t), "w") as fh:
                    fh.write(to_yahoo(make(path(50, [(300, 100)]))))
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                code = st.main(["AAA", "BBB", "ZZZ", "--offline", tmp, "--benchmark", "", "--no-sec"])
            self.assertEqual(code, 0)
            self.assertIn("active setups", buf.getvalue())
            self.assertIn("ZZZ: no offline file", err.getvalue())
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(st.main(["ZZZ", "--offline", tmp, "--benchmark", "", "--no-sec"]), 1)


if __name__ == "__main__":
    unittest.main()
