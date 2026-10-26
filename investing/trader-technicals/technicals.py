#!/usr/bin/env python3
"""Long-term chart check and seasonality for trader-technicals. Standard library only.

    python3 technicals.py MA V MSFT GOOGL                 # trend, RSI, levels, seasonality
    python3 technicals.py MA --years 20 --json            # longer seasonality, JSON on stdout
    python3 technicals.py MA V --out trader/technicals.json
    python3 technicals.py MA --offline tests/fixtures/trader-technicals

What it computes per ticker (dividend- and split-adjusted closes):
  trend         price vs. the 50- and 200-day averages, the 200-day slope over
                the last month: uptrend, downtrend or mixed
  momentum      Wilder's RSI(14) on daily and on weekly closes
  levels        52-week high and low, the drawdown from the high, the nearest
                swing low below and swing high above the price (weekly closes,
                last two years, plus the low and high of the last four weeks),
                the 200-day average as a level
  performance   1m / 3m / 6m / 1y returns, 3y / 5y / 10y CAGR, the biggest
                drawdown in the data, 1y return vs. the benchmark (SPY)
  seasonality   per calendar month over the last N complete years: average and
                median return, share of up months, and a t-value; |t| < 2 is
                marked as noise because a dozen samples prove very little;
                with a benchmark also the average excess over it in that
                month (a strong November is often just the whole market)

Data: Yahoo Finance's unofficial chart JSON (free, delayed), daily bars for
11 years and monthly bars (31 years) for the seasonality, query2 first, query1 as the
fallback. --offline DIR reads DIR/<TICKER>-1d.json and DIR/<TICKER>-1mo.json.

None of this predicts the future. A chart describes what the price did; a
seasonal average describes what it did in past calendar months.
"""

import argparse
import datetime
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; trader-skill/1.0; +https://github.com/Jakeschincariol/trader-skill)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
PAUSE = 0.5  # seconds between requests: be polite to free endpoints
BENCHMARK = "SPY"
DAILY_YEARS = 11     # ten full years for the 10y CAGR, plus a margin
MONTHLY_YEARS = 31   # room for --years up to 30
MIN_GAP = 2.0       # a support or resistance closer than this many % to the price is not a level
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class DataError(Exception):
    pass


# ---------------------------------------------------------------- data

def yahoo_symbol(ticker):
    return ticker.upper().replace(".", "-")  # BRK.B -> BRK-B


def chart_path(ticker, interval, now):
    """Explicit period1/period2: with range=max Yahoo thins monthly bars to quarters."""
    years = DAILY_YEARS if interval == "1d" else MONTHLY_YEARS
    start = now - datetime.timedelta(days=int(365.25 * years))
    return "/v8/finance/chart/%s?period1=%d&period2=%d&interval=%s&events=div%%2Csplit" % (
        yahoo_symbol(ticker), start.timestamp(), now.timestamp(), interval)


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_get(path):
    last = "no answer"
    for host in YAHOO_HOSTS:
        try:
            return http_get(host + path)
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            if e.code == 429 or e.code >= 500:
                continue
            try:
                body = e.read().decode("utf-8", "replace")
            finally:
                e.close()
            if body.strip().startswith("{"):
                return body  # Yahoo's JSON error, parsed by the caller
            raise DataError("Yahoo answered %s for %s" % (last, path.split("?")[0]))
        except (urllib.error.URLError, OSError) as e:
            last = str(getattr(e, "reason", e))
    raise DataError("Yahoo did not answer (%s) for %s" % (last, path.split("?")[0]))


def parse_chart(text, ticker):
    """Yahoo chart JSON -> [(date, adjusted close)], oldest first, nulls dropped."""
    try:
        data = json.loads(text)
    except ValueError:
        raise DataError("%s: Yahoo sent something that is not JSON" % ticker)
    chart = data.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        err = (chart.get("error") or {}).get("description") or "no data"
        raise DataError("%s: %s" % (ticker, err))
    res = chart["result"][0]
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    adj = ((ind.get("adjclose") or [{}])[0]).get("adjclose")
    close = ((ind.get("quote") or [{}])[0]).get("close")
    series = adj or close or []
    off = (res.get("meta") or {}).get("gmtoffset") or 0
    out = {}
    for t, c in zip(ts, series):
        if c is None:
            continue
        d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).date()
        out[d] = float(c)  # one bar per date: a late duplicate (the live tick) wins
    if not out:
        raise DataError("%s: no prices in Yahoo's answer" % ticker)
    meta = res.get("meta") or {}
    return sorted(out.items()), {"currency": meta.get("currency"), "name": meta.get("longName") or meta.get("shortName")}


def load(ticker, interval, offline=None):
    if offline:
        path = os.path.join(offline, "%s-%s.json" % (yahoo_symbol(ticker), interval))
        if not os.path.exists(path):
            raise DataError("%s: no offline file %s" % (ticker, path))
        with open(path, encoding="utf-8") as fh:
            return parse_chart(fh.read(), ticker)
    text = yahoo_get(chart_path(ticker, interval, datetime.datetime.now(datetime.timezone.utc)))
    time.sleep(PAUSE)
    return parse_chart(text, ticker)


# ---------------------------------------------------------------- math

def sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def rsi(closes, n=14):
    """Wilder's RSI (the same math as day-trading/trader-scanner)."""
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def weekly(bars):
    """[(date, close)] daily -> last close of each ISO week."""
    out = {}
    for d, c in bars:
        out[d.isocalendar()[:2]] = (d, c)
    return [out[k] for k in sorted(out)]


def pct(a, b):
    return (a / b - 1) * 100 if a is not None and b else None


def back(bars, days):
    """The close on or before `days` calendar days before the last bar."""
    target = bars[-1][0] - datetime.timedelta(days=days)
    if bars[0][0] > target:
        return None
    for d, c in reversed(bars):
        if d <= target:
            return c
    return None


def cagr(bars, years):
    start = back(bars, int(round(365.25 * years)))
    return ((bars[-1][1] / start) ** (1 / years) - 1) * 100 if start else None


def max_drawdown(closes):
    peak, worst = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1)
    return worst * 100


def swings(points, k=4):
    """Swing highs and lows: a close that is the highest (lowest) of the k
    closes on each side. points = [(date, close)]."""
    highs, lows = [], []
    for i in range(k, len(points) - k):
        win = [c for _, c in points[i - k:i + k + 1]]
        c = points[i][1]
        if c == max(win):
            highs.append(points[i])
        if c == min(win):
            lows.append(points[i])
    return highs, lows


def trend_label(price, s50, s200, s200_before):
    if None in (s50, s200, s200_before):
        return "unknown", "not enough history for the 200-day average"
    rising = s200 > s200_before
    if price > s50 > s200 and rising:
        return "uptrend", "price above the 50- and 200-day averages, 50 above 200, 200-day rising"
    if price < s50 < s200 and not rising:
        return "downtrend", "price below the 50- and 200-day averages, 50 below 200, 200-day falling"
    bits = ["price %s the 50-day" % ("above" if price > s50 else "below"),
            "%s the 200-day" % ("above" if price > s200 else "below"),
            "50-day %s the 200-day" % ("above" if s50 > s200 else "below"),
            "200-day %s" % ("rising" if rising else "falling")]
    return "mixed", ", ".join(bits)


def monthly_returns(mbars, today):
    """Monthly closes -> {(year, month): return %}, the running month left out."""
    by_month = {}
    for d, c in mbars:  # Yahoo adds a bar for the latest day: one close per month, the last wins
        if (d.year, d.month) != (today.year, today.month):
            by_month[(d.year, d.month)] = (d, c)
    closes = [by_month[k] for k in sorted(by_month)]
    out = {}
    for (d0, c0), (d1, c1) in zip(closes, closes[1:]):
        if c0 and (d1.year * 12 + d1.month) - (d0.year * 12 + d0.month) == 1:  # a gap is no return
            out[(d1.year, d1.month)] = (c1 / c0 - 1) * 100
    return out


def seasonality(mret, years, last_year, bench=None):
    """Per calendar month over the complete years last_year-years+1 .. last_year.
    With the benchmark's monthly returns, also the average excess over it."""
    first = last_year - years + 1
    rows = []
    for m in range(1, 13):
        xs = [r for (y, mm), r in mret.items() if mm == m and first <= y <= last_year]
        row = {"month": MONTHS[m - 1], "n": len(xs)}
        if len(xs) >= 3:
            sd = statistics.stdev(xs)
            avg = statistics.mean(xs)
            t = avg / (sd / math.sqrt(len(xs))) if sd else 0.0
            row.update(avg=avg, median=statistics.median(xs),
                       up=100.0 * sum(1 for x in xs if x > 0) / len(xs), t=t,
                       signal=abs(t) >= 2)
            if bench:
                ex = [r - bench[(y, mm)] for (y, mm), r in mret.items()
                      if mm == m and first <= y <= last_year and (y, mm) in bench]
                if ex:
                    row["vs_bench"] = statistics.mean(ex)
        rows.append(row)
    return rows


def analyse(ticker, daily, monthly, bench=None, years=15, today=None, bench_name=BENCHMARK):
    bars = daily[0]
    closes = [c for _, c in bars]
    if len(closes) < 60:
        raise DataError("%s: only %d daily closes" % (ticker, len(closes)))
    last_date, price = bars[-1]
    today = today or last_date  # the calendar date: decides the running month and the next months
    s50, s200 = sma(closes, 50), sma(closes, 200)
    s200_before = sma(closes[:-21], 200) if len(closes) >= 221 else None
    label, why = trend_label(price, s50, s200, s200_before)

    yr = [c for d, c in bars if d > last_date - datetime.timedelta(days=365)]
    hi52, lo52 = max(yr), min(yr)
    wk = weekly(bars)
    recent = [(d, c) for d, c in wk if d > last_date - datetime.timedelta(days=730)]
    highs, lows = swings(recent)
    tail = recent[-4:]  # the last weeks cannot be confirmed swings yet: count their extremes too
    highs.append(max(tail, key=lambda x: x[1]))
    lows.append(min(tail, key=lambda x: x[1]))
    support = max((c for _, c in lows if c < price * (1 - MIN_GAP / 100)), default=None)
    resistance = min((c for _, c in highs if c > price * (1 + MIN_GAP / 100)), default=None)

    r1y = pct(price, back(bars, 365))
    rel = None  # bench = (daily, monthly) of the benchmark
    if bench:
        b = bench[0][0]
        rel = r1y - pct(b[-1][1], back(b, 365)) if r1y is not None and back(b, 365) else None

    mret = monthly_returns(monthly[0], today)
    complete_years = sorted({y for (y, m) in mret if sum(1 for (yy, _) in mret if yy == y) == 12})
    last_full = complete_years[-1] if complete_years else today.year - 1
    bret = monthly_returns(bench[1][0], today) if bench else None
    seas = seasonality(mret, years, last_full, bret)
    have = [y for y in complete_years if y > last_full - years]
    nxt = [(today.month + i - 1) % 12 for i in (1, 2, 3)]  # next three calendar months, 0-based

    return {
        "ticker": ticker.upper(), "name": daily[1].get("name"), "currency": daily[1].get("currency"),
        "date": last_date.isoformat(), "price": price,
        "trend": {"label": label, "why": why, "sma50": s50, "sma200": s200,
                  "vs_sma200_pct": pct(price, s200),
                  "sma200_slope_1m_pct": pct(s200, s200_before)},
        "momentum": {"rsi14_daily": rsi(closes), "rsi14_weekly": rsi([c for _, c in wk])},
        "levels": {"high_52w": hi52, "low_52w": lo52, "from_high_pct": pct(price, hi52),
                   "swing_support": support, "swing_resistance": resistance, "sma200": s200},
        "performance": {"1m": pct(price, back(bars, 30)), "3m": pct(price, back(bars, 91)),
                        "6m": pct(price, back(bars, 182)), "1y": r1y,
                        "cagr_3y": cagr(bars, 3), "cagr_5y": cagr(bars, 5), "cagr_10y": cagr(bars, 10),
                        "max_drawdown_pct": max_drawdown(closes),
                        "data_from": bars[0][0].isoformat(),
                        "vs_benchmark_1y": rel, "benchmark": bench_name.upper() if bench else None},
        "seasonality": {"years": len(have), "from": have[0] if have else None,
                        "to": have[-1] if have else None, "months": seas,
                        "next_months": [seas[i] for i in nxt]},
    }


# ---------------------------------------------------------------- output

def f(x, fmt="%.1f", none="-"):
    return none if x is None else fmt % x


def render(r):
    t, m, lv, p, s = r["trend"], r["momentum"], r["levels"], r["performance"], r["seasonality"]
    out = ["%s  %s  %s %.2f on %s" % (r["ticker"], r["name"] or "", r["currency"] or "", r["price"], r["date"]),
           "  trend      %s: %s" % (t["label"].upper(), t["why"]),
           "             50d %s  200d %s  price %s%% vs 200d  200d slope %s%%/month" % (
               f(t["sma50"], "%.2f"), f(t["sma200"], "%.2f"), f(t["vs_sma200_pct"], "%+.1f"),
               f(t["sma200_slope_1m_pct"], "%+.2f")),
           "  momentum   RSI14 daily %s  weekly %s%s" % (
               f(m["rsi14_daily"], "%.0f"), f(m["rsi14_weekly"], "%.0f"), rsi_note(m["rsi14_daily"])),
           "  levels     52w %s - %s (%s%% from the high)  support %s  resistance %s" % (
               f(lv["low_52w"], "%.2f"), f(lv["high_52w"], "%.2f"), f(lv["from_high_pct"], "%+.1f"),
               f(lv["swing_support"], "%.2f", "none (near the low)"),
               f(lv["swing_resistance"], "%.2f", "none (near the high)")),
           "  returns    1m %s  3m %s  6m %s  1y %s  |  CAGR 3y %s  5y %s  10y %s  |  max DD %s%%" % (
               f(p["1m"], "%+.1f%%"), f(p["3m"], "%+.1f%%"), f(p["6m"], "%+.1f%%"), f(p["1y"], "%+.1f%%"),
               f(p["cagr_3y"], "%.1f%%"), f(p["cagr_5y"], "%.1f%%"), f(p["cagr_10y"], "%.1f%%"),
               f(p["max_drawdown_pct"], "%.0f"))]
    if p["vs_benchmark_1y"] is not None:
        out.append("             1y vs %s: %s points" % (p["benchmark"], f(p["vs_benchmark_1y"], "%+.1f")))
    out.append("  seasonal   %s complete years (%s-%s); next months:" % (s["years"], s["from"], s["to"]))
    for row in s["next_months"]:
        if "avg" not in row:
            out.append("             %s  too few years" % row["month"])
            continue
        vs = "  vs %s %+.1f" % (p["benchmark"], row["vs_bench"]) if "vs_bench" in row else ""
        out.append("             %s  avg %+5.1f%%  median %+5.1f%%  up %3.0f%% of years  t %+.1f%s%s" % (
            row["month"], row["avg"], row["median"], row["up"], row["t"], vs,
            "" if row["signal"] else "  (noise)"))
    return "\n".join(out)


def rsi_note(v):
    if v is None:
        return ""
    if v >= 70:
        return "  (overbought zone)"
    if v <= 30:
        return "  (oversold zone)"
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--years", type=int, default=15, help="years of seasonality (default 15)")
    ap.add_argument("--benchmark", default=BENCHMARK, help="relative strength vs. this (default SPY, '' for none)")
    ap.add_argument("--offline", help="read <TICKER>-1d.json and <TICKER>-1mo.json from this folder")
    ap.add_argument("--out", help="write the results JSON here (trader/technicals.json)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    bench = None
    if a.benchmark:
        try:
            bench = (load(a.benchmark, "1d", a.offline), load(a.benchmark, "1mo", a.offline))
        except DataError as e:
            print("benchmark skipped: %s" % e, file=sys.stderr)
    results, errors = [], []
    # live: the calendar decides the running month (on Jan 1 December is complete);
    # offline: the files' last bar does
    today = None if a.offline else datetime.date.today()
    for t in a.tickers:
        try:
            results.append(analyse(t, load(t, "1d", a.offline), load(t, "1mo", a.offline), bench, a.years,
                                   today=today, bench_name=a.benchmark))
        except DataError as e:
            errors.append(str(e))
    doc = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "Yahoo Finance chart API (unofficial, delayed, adjusted closes)",
           "results": results, "errors": errors}
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("\n\n".join(render(r) for r in results))
        for e in errors:
            print("ERROR %s" % e, file=sys.stderr)
        print("\nCharts and seasonal averages describe the past. They do not predict returns.")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
