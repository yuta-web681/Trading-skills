#!/usr/bin/env python3
"""Swing setups for trader-technicals: Stage 2, VCP, Episodic Pivot, Multi-Edge pullback, PEAD,
Momentum Burst and volume. Standard library only.

    python3 setups.py NVDA ANET                         # all setups, text
    python3 setups.py NVDA --json                       # the same as JSON
    python3 setups.py NVDA ANET --out trader/setups.json
    python3 setups.py NVDA --offline tests/fixtures/trader-technicals --no-sec

What it checks per ticker on daily open/high/low/close/volume (split- and dividend-adjusted):
  stage 2       Minervini's trend template: price above the 50-, 150- and 200-day averages,
                50 > 150 > 200, the 200-day rising for a month, at least 30 % above the
                52-week low, within 25 % of the 52-week high, and a relative strength vs.
                SPY weighted 40/20/20/20 over 3/6/9/12 months (an estimate, not a
                percentile rank across all stocks)
  vcp           Minervini's volatility contraction: a base that starts at its highest high
                and pulls back in ever smaller waves (each at least a quarter tighter), the
                pivot (high of the last wave), the stop (its low), the volume dry-up
  ep            Stockbee's Episodic Pivot: a gap of 4 % or more on 3x the 50-day volume,
                closing in the upper half of the day; with a SEC user agent also the 8-K or
                6-K filed around that day (2.02 = earnings) as the catalyst
  multi-edge    J Law's catalyst breakout -> pullback to the 20-day EMA on falling volume,
                gap still holding: the entry above the day's high, the stop under the
                pullback low, the risk in % and a 2R target
  pead          Post-earnings drift on weekly candles: after a gap of 3 % or more, the first
                red week, then a weekly close above its high (entry) with its low as the stop
  burst         Stockbee's 4 % Momentum Burst in the last five days: +4 % on rising volume,
                close near the high, not after three up days in a row
  volume        relative volume, the 10/50-day dry-up, up/down volume over 50 days,
                distribution and accumulation days over 25 days

Data: Yahoo Finance's unofficial chart JSON (the same as technicals.py), three years of daily
bars plus SPY. --offline DIR reads DIR/<TICKER>-1d.json and, for catalysts,
DIR/company_tickers.json and DIR/submissions-CIK##########.json. SEC data needs a user agent
with your name and email: SEC_USER_AGENT, "sec_user_agent" in trader/config.json, or
--user-agent; without one the catalyst is printed as unknown.

None of this predicts the future. A setup describes a chart that, in the past, often came
before a move; most setups fail, which is why each one carries a stop.
"""

import argparse
import bisect
import datetime
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import technicals as T  # noqa: E402  (same folder: Yahoo access, SMA, RSI)

YEARS = 3                # 2 years for the trend template and RS, plus a margin
EP_GAP, EP_VOL = 4.0, 3.0          # Stockbee: gap >= 4 %, volume >= 3x the 50-day average
GAP_MIN, GAP_VOL = 3.0, 2.0        # a weaker catalyst gap still counts for PEAD / Multi-Edge
EP_WINDOW = 60           # trading days searched for gaps
ME_MAX_DAYS = 40         # a Multi-Edge pullback must come within this many days of the gap
PEAD_WEEKS = 5           # PEAD watch window after the gap week
TOUCH = 1.0              # % above the 20-EMA that still counts as "touched"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK%s.json"
PLACEHOLDER = "you@example.com"
ITEMS = {"2.02": "earnings", "1.01": "material agreement", "2.01": "acquisition or sale",
         "5.02": "management change", "7.01": "Reg FD (often guidance)", "8.01": "other event",
         "1.03": "bankruptcy", "3.01": "delisting notice"}


class Bar(object):
    __slots__ = ("d", "o", "h", "l", "c", "v")

    def __init__(self, d, o, h, l, c, v):
        self.d, self.o, self.h, self.l, self.c, self.v = d, o, h, l, c, v

    def __repr__(self):
        return "Bar(%s %.2f %.2f %.2f %.2f %d)" % (self.d, self.o, self.h, self.l, self.c, self.v)


# ---------------------------------------------------------------- data

def parse_ohlcv(text, ticker):
    """Yahoo chart JSON -> [Bar], oldest first. Open, high and low are scaled by
    adjclose / close so that a dividend or split does not show up as a gap."""
    try:
        data = json.loads(text)
    except ValueError:
        raise T.DataError("%s: Yahoo sent something that is not JSON" % ticker)
    chart = data.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        err = (chart.get("error") or {}).get("description") or "no data"
        raise T.DataError("%s: %s" % (ticker, err))
    res = chart["result"][0]
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    q = (ind.get("quote") or [{}])[0]
    adj = ((ind.get("adjclose") or [{}])[0]).get("adjclose") or q.get("close") or []
    off = (res.get("meta") or {}).get("gmtoffset") or 0
    out = {}
    cols = zip(ts, q.get("open") or [], q.get("high") or [], q.get("low") or [],
               q.get("close") or [], q.get("volume") or [], adj)
    for t, o, h, l, c, v, a in cols:
        if None in (o, h, l, c, a) or not c:
            continue
        k = a / c
        d = datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).date()
        out[d] = Bar(d, o * k, max(h, o, c) * k, min(l, o, c) * k, a, int(v or 0))
    if not out:
        raise T.DataError("%s: no prices in Yahoo's answer" % ticker)
    meta = res.get("meta") or {}
    return [out[d] for d in sorted(out)], {"currency": meta.get("currency"),
                                          "name": meta.get("longName") or meta.get("shortName")}


def load(ticker, offline=None):
    if offline:
        path = os.path.join(offline, "%s-1d.json" % T.yahoo_symbol(ticker))
        if not os.path.exists(path):
            raise T.DataError("%s: no offline file %s" % (ticker, path))
        with open(path, encoding="utf-8") as fh:
            return parse_ohlcv(fh.read(), ticker)
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=int(365.25 * YEARS))
    path = "/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d&events=div%%2Csplit" % (
        T.yahoo_symbol(ticker), start.timestamp(), now.timestamp())
    text = T.yahoo_get(path)
    time.sleep(T.PAUSE)
    return parse_ohlcv(text, ticker)


def user_agent(cli=None, config="trader/config.json"):
    ua = (cli or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua and config and os.path.isfile(config):
        try:
            with open(config, encoding="utf-8") as fh:
                ua = str(json.load(fh).get("sec_user_agent") or "").strip()
        except (OSError, ValueError):
            ua = ""
    return ua if ua and "@" in ua and PLACEHOLDER not in ua else None


class Sec(object):
    """8-K / 6-K filings per ticker from SEC EDGAR, for the catalyst of a gap."""

    def __init__(self, ua=None, offline=None):
        self.ua, self.offline, self._ciks, self._last = ua, offline, None, 0.0

    def available(self):
        if self.offline:
            return os.path.isfile(os.path.join(self.offline, "company_tickers.json"))
        return bool(self.ua)

    def json(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise T.DataError("offline: no file %s" % path)
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        gap = time.time() - self._last
        if gap < 0.15:
            time.sleep(0.15 - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
        except urllib.error.HTTPError as e:
            raise T.DataError("SEC answered HTTP %d for %s" % (e.code, url))
        except (urllib.error.URLError, OSError) as e:
            raise T.DataError("could not reach SEC: %s" % getattr(e, "reason", e))
        return json.loads(raw.decode("utf-8"))

    def filings(self, ticker):
        """[(filing date, form, items)] of the 8-Ks and 6-Ks in the recent list."""
        if self._ciks is None:
            data = self.json(TICKERS_URL, "company_tickers.json")
            self._ciks = {v["ticker"].upper().replace("-", "."): str(v["cik_str"]).zfill(10)
                          for v in data.values()}
        cik = self._ciks.get(ticker.upper().replace("-", "."))
        if not cik:
            raise T.DataError("%s: not in SEC's ticker list (no US filer?)" % ticker)
        rec = (self.json(SUBMISSIONS_URL % cik, "submissions-CIK%s.json" % cik)
               .get("filings") or {}).get("recent") or {}
        out = []
        for form, fd, items in zip(rec.get("form", []), rec.get("filingDate", []),
                                   rec.get("items", [""] * len(rec.get("form", [])))):
            if form in ("8-K", "6-K"):
                out.append((datetime.date.fromisoformat(fd), form, items or ""))
        return out


def catalyst_for(day, filings):
    """The 8-K / 6-K filed on the gap day or up to four calendar days before it
    (earnings come out after the close or before the open). Earnings win."""
    hits = [(fd, form, items) for fd, form, items in filings
            if day - datetime.timedelta(days=4) <= fd <= day]
    if not hits:
        return None
    hits.sort(key=lambda h: ("2.02" not in h[2], (day - h[0]).days))
    fd, form, items = hits[0]
    codes = [i.strip() for i in items.split(",") if i.strip() and i.strip() != "9.01"]
    what = [ITEMS.get(c, "item " + c) for c in codes] or (["foreign issuer report"] if form == "6-K" else [])
    return {"form": form, "filed": fd.isoformat(), "items": codes,
            "earnings": "2.02" in codes, "what": ", ".join(what) or "unspecified"}


# ---------------------------------------------------------------- math

def avg(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def ema_series(values, n):
    out, k, e = [], 2.0 / (n + 1), None
    for i, v in enumerate(values):
        if i < n - 1:
            out.append(None)
            continue
        e = sum(values[:n]) / n if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def atr(bars, n=14):
    """Wilder's average true range on the last bars."""
    if len(bars) < n + 1:
        return None
    tr = [max(b.h - b.l, abs(b.h - p.c), abs(b.l - p.c)) for p, b in zip(bars, bars[1:])]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def clv(b):
    """Where the close sits in the day's range: 0 = at the low, 1 = at the high."""
    return (b.c - b.l) / (b.h - b.l) if b.h > b.l else 0.5


def pct(a, b):
    return (a / b - 1) * 100 if a is not None and b else None


def zigzag(bars, thr):
    """Swing points on highs and lows: a turn counts once price reverses by thr %.
    -> [(index, price, 'H' or 'L', confirmed)]; the last point is the running
    extreme and not yet confirmed."""
    if len(bars) < 2:
        return []
    f = thr / 100.0
    piv, trend, hi, lo, ext = [], None, 0, 0, 0
    for i in range(1, len(bars)):
        b = bars[i]
        if trend is None:
            if b.h > bars[hi].h:
                hi = i
            if b.l < bars[lo].l:
                lo = i
            if lo < hi and bars[hi].h >= bars[lo].l * (1 + f):
                piv.append((lo, bars[lo].l, "L", True))
                trend, ext = "up", hi
            elif hi < lo and bars[lo].l <= bars[hi].h * (1 - f):
                piv.append((hi, bars[hi].h, "H", True))
                trend, ext = "down", lo
        elif trend == "up":
            if b.h >= bars[ext].h:
                ext = i
            elif b.l <= bars[ext].h * (1 - f):
                piv.append((ext, bars[ext].h, "H", True))
                trend, ext = "down", i
        else:
            if b.l <= bars[ext].l:
                ext = i
            elif b.h >= bars[ext].l * (1 + f):
                piv.append((ext, bars[ext].l, "L", True))
                trend, ext = "up", i
    if trend == "up":
        piv.append((ext, bars[ext].h, "H", False))
    elif trend == "down":
        piv.append((ext, bars[ext].l, "L", False))
    return piv


# ---------------------------------------------------------------- setups

def close_on(series, day):
    """The close of [(date, close)] on `day` or the last session before it."""
    i = bisect.bisect_right([d for d, _ in series], day)
    return series[i - 1][1] if i else None


def trend_template(bars, bench=None):
    closes = [b.c for b in bars]
    price = closes[-1]
    s50, s150, s200 = T.sma(closes, 50), T.sma(closes, 150), T.sma(closes, 200)
    s200_before = T.sma(closes[:-22], 200) if len(closes) >= 222 else None
    yr = bars[-252:]
    hi52, lo52 = max(b.h for b in yr), min(b.l for b in yr)
    rs = None
    if bench:
        tot = 0.0
        b_now = close_on(bench, bars[-1].d)  # the benchmark as of the stock's last day
        for days, w in ((63, .4), (126, .2), (189, .2), (252, .2)):
            if len(closes) > days:
                b_then = close_on(bench, bars[-1 - days].d)
                if b_now is None or b_then is None:
                    continue
                rel = pct(closes[-1], closes[-1 - days]) - pct(b_now, b_then)
                rs = (rs or 0.0) + rel * w
                tot += w
        rs = rs / tot if rs is not None and tot else None

    def ok(cond, *need):
        return None if any(x is None for x in need) else bool(cond())

    checks = [
        ("price above the 150- and 200-day", ok(lambda: price > s150 and price > s200, s150, s200)),
        ("150-day above the 200-day", ok(lambda: s150 > s200, s150, s200)),
        ("200-day rising for a month", ok(lambda: s200 > s200_before, s200, s200_before)),
        ("50-day above the 150- and 200-day", ok(lambda: s50 > s150 and s50 > s200, s50, s150, s200)),
        ("price above the 50-day", ok(lambda: price > s50, s50)),
        ("at least 30% above the 52-week low", ok(lambda: price >= lo52 * 1.30, lo52)),
        ("within 25% of the 52-week high", ok(lambda: price >= hi52 * 0.75, hi52)),
        ("relative strength vs SPY at least +5 points", ok(lambda: rs >= 5, rs)),
    ]
    passed = sum(1 for _, v in checks if v)
    known = sum(1 for _, v in checks if v is not None)
    if known < 7:
        stage = "unknown"
    elif passed == len(checks) or (passed == 7 and checks[-1][1] is None):
        stage = "stage 2"
    elif price < s200 and s200_before is not None and s200 < s200_before:
        stage = "stage 4 (falling 200-day)"
    elif passed >= 6:
        stage = "almost stage 2"
    else:
        stage = "not stage 2"
    return {"stage": stage, "passed": passed, "of": len(checks),
            "failed": [name for name, v in checks if v is False],
            "unknown": [name for name, v in checks if v is None],
            "sma50": s50, "sma150": s150, "sma200": s200,
            "above_low_pct": pct(price, lo52), "from_high_pct": pct(price, hi52),
            "rs_vs_bench": rs}


def vcp(bars, lookback=200, atr_val=None):
    """The base as of today; if there is none because price already left it,
    the base as of up to ten days ago, judged against today's price."""
    out = vcp_base(bars, lookback, atr_val)
    if out.get("valid") or out["state"] not in ("none", "no vcp"):
        return out
    for j in range(1, 11):
        old = vcp_base(bars[:-j], lookback, atr_val)
        if old.get("valid") and bars[-1].c > old["pivot"]:
            return state_vs_pivot(bars, old)
    return out


def vcp_base(bars, lookback=200, atr_val=None):
    """The base at the finest swing size (1.5 ATR, 2.5-8 %) that shows a valid
    VCP; coarser sizes drop the small wiggles a long base is full of."""
    price = bars[-1].c
    atr_pct = (atr_val / price * 100) if atr_val else 2.0
    thr = min(8.0, max(2.5, 1.5 * atr_pct))
    first = None
    for k in (1.0, 1.5, 2.0, 3.0):
        res = base_at(bars, lookback, thr * k)
        if res.get("valid"):
            return res
        first = first or res
    return first


def base_at(bars, lookback, thr):
    """Find the base: start at the highest high of the window, then the waves
    (swing high -> swing low) after it. Valid when there are two or more waves,
    the first 8-50 % deep, each at least 25 % shallower than the one before, no
    swing high more than 15 % under the start, and price above the last low."""
    win = bars[-lookback:]
    price = bars[-1].c
    piv = zigzag(win, thr)
    highs = [p for p in piv if p[2] == "H"]
    if not highs:
        return {"state": "none", "why": "no swing high in the last %d days" % lookback}
    start = max(highs, key=lambda p: p[1])
    seq = [p for p in piv if p[0] >= start[0]]
    waves = []
    for a, b in zip(seq, seq[1:]):
        if a[2] == "H" and b[2] == "L":
            waves.append({"high": a[1], "low": b[1], "depth": (1 - b[1] / a[1]) * 100,
                          "from": win[a[0]].d.isoformat(), "to": win[b[0]].d.isoformat(),
                          "days": b[0] - a[0], "low_confirmed": b[3]})
    out = {"zigzag_pct": thr, "base_start": win[start[0]].d.isoformat(), "base_high": start[1],
           "base_days": len(win) - 1 - start[0], "waves": waves}
    if not waves:
        out.update(state="none", why="no pullback since the high on %s" % out["base_start"])
        return out
    depths = [w["depth"] for w in waves]
    tight = [b <= a * 0.75 for a, b in zip(depths, depths[1:])]
    last = waves[-1]
    problems = []
    if len(waves) < 2:
        problems.append("only one pullback so far")
    if not 8 <= depths[0] <= 50:
        problems.append("first pullback %.0f%% (needs 8-50%%)" % depths[0])
    if not all(tight):
        problems.append("pullbacks are not getting tighter")
    if min(w["high"] for w in waves) < start[1] * 0.85:
        problems.append("swing highs fall more than 15% under the base high")
    if price < last["low"]:
        problems.append("price under the last swing low")
    if out["base_days"] < 15:
        problems.append("base younger than 3 weeks")
    pivot = last["high"]  # the high of the last wave
    vols = [b.v for b in bars]
    v50 = avg(vols[-50:])
    dry = avg(vols[-10:]) / v50 if v50 else None
    out.update(depths=depths, pivot=pivot, stop=last["low"], dryup=dry,
               vs_pivot_pct=pct(price, pivot), risk_pct=(1 - last["low"] / pivot) * 100,
               valid=not problems, problems=problems)
    if problems:
        out["state"] = "no vcp"
        out["why"] = "; ".join(problems)
        return out
    return state_vs_pivot(bars, out)


def state_vs_pivot(bars, out):
    """Where today's close stands against a valid base's pivot."""
    pivot, vols = out["pivot"], [b.v for b in bars]
    out = dict(out, vs_pivot_pct=pct(bars[-1].c, pivot))
    crossed = [i for i in range(len(bars) - 10, len(bars)) if bars[i].c > pivot >= bars[i - 1].c]
    if crossed:
        i = crossed[-1]
        out["breakout_volume"] = bars[i].v / avg(vols[i - 50:i]) if i >= 50 else None
        out["breakout_date"] = bars[i].d.isoformat()
    if bars[-1].c > pivot * 1.05:
        out["state"] = "extended"
    elif bars[-1].c > pivot:
        vm = out.get("breakout_volume")
        out["state"] = ("above pivot" if vm is None else
                        "breakout" if vm >= 1.4 else "breakout on light volume")
    elif bars[-1].c >= pivot * 0.95:
        out["state"] = "near pivot"
    else:
        out["state"] = "base forming"
    return out


def gaps(bars, window=EP_WINDOW, sec_filings=None):
    """Gap days in the last `window` bars: gap >= 3 % on >= 2x the 50-day volume.
    'ep' marks Stockbee's stricter Day 1 (gap >= 4 %, >= 3x volume, upper half close)."""
    out = []
    for i in range(max(51, len(bars) - window), len(bars)):
        b, p = bars[i], bars[i - 1]
        v50 = avg(x.v for x in bars[i - 50:i])
        gap = pct(b.o, p.c)
        vm = b.v / v50 if v50 else None
        if gap is None or gap < GAP_MIN or vm is None or vm < GAP_VOL:
            continue
        prior = bars[i - 61].c if i >= 61 else bars[0].c
        after = bars[i + 1:]
        g = {"index": i, "date": b.d.isoformat(), "gap_pct": gap, "day_pct": pct(b.c, p.c),
             "volume_x": vm, "close_in_range": clv(b), "low": b.l, "high": b.h, "close": b.c,
             "prior_close": p.c, "run_before_pct": pct(p.c, prior),
             "days_ago": len(bars) - 1 - i, "since_pct": pct(bars[-1].c, b.c),
             "ep": gap >= EP_GAP and vm >= EP_VOL and clv(b) >= 0.5}
        if after and min(x.l for x in after) < b.l:
            g["held"] = "gap filled" if bars[-1].c < p.c else "dipped under the gap-day low since"
        else:
            g["held"] = "holding"
        if sec_filings is not None:
            g["catalyst"] = catalyst_for(b.d, sec_filings)
        out.append(g)
    return out


def multi_edge(bars, gap):
    """J Law's Multi-Edge after a catalyst gap: let it run, then buy the first
    quiet pullback to the 20-day EMA while the gap holds."""
    if gap is None:
        return {"state": "none", "why": "no catalyst gap in the last %d days" % EP_WINDOW}
    e = gap["index"]
    days = len(bars) - 1 - e
    closes = [b.c for b in bars]
    ema = ema_series(closes, 20)
    s50 = T.sma(closes, 50)
    last, prev = bars[-1], bars[-2]
    out = {"gap_date": gap["date"], "days_since_gap": days, "ema20": ema[-1], "sma50": s50,
           "to_ema_pct": pct(last.c, ema[-1])}
    if days > ME_MAX_DAYS:
        out.update(state="expired", why="gap %d trading days ago (window %d)" % (days, ME_MAX_DAYS))
        return out
    if last.c < gap["low"]:
        out.update(state="failed", why="closed under the gap-day low %.2f" % gap["low"])
        return out
    peak = max(range(e, len(bars)), key=lambda i: bars[i].h)
    pull = bars[peak + 1:]
    v_base = avg(b.v for b in bars[max(0, e - 50):e])
    out.update(post_gap_high=bars[peak].h, post_gap_high_date=bars[peak].d.isoformat())
    if not pull:
        out.update(state="running", why="new high today, no pullback yet")
        return out
    plow = min(b.l for b in pull)
    vr = avg(b.v for b in pull) / v_base if v_base else None
    touched = any(b.l <= ema[len(bars) - len(pull) + j] * (1 + TOUCH / 100)
                  for j, b in enumerate(pull) if ema[len(bars) - len(pull) + j] is not None)
    near_now = any(bars[i].l <= ema[i] * (1 + TOUCH / 100) for i in range(max(peak + 1, len(bars) - 3), len(bars)))
    out.update(pullback_pct=(1 - plow / bars[peak].h) * 100, pullback_low=plow,
               pullback_days=len(pull), pullback_volume_x=vr, touched_ema=touched)
    entry = last.h * 1.001
    stop = min(plow, last.l) * 0.995
    plan = {"entry": entry, "stop": stop, "risk_pct": (1 - stop / entry) * 100,
            "target_2r": entry + 2 * (entry - stop)}
    warn = []
    if vr is not None and vr > 1.0:
        warn.append("pullback volume %.1fx the pre-gap average (wanted: below 1x)" % vr)
    if s50 and last.c < s50:
        warn.append("under the 50-day")
    if last.c < ema[-1] * 0.98:
        warn.append("closed %.1f%% under the 20-EMA" % pct(last.c, ema[-1]))
    if plow < gap["low"]:
        warn.append("pullback dipped under the gap-day low")
    if out["pullback_pct"] > 15:
        warn.append("pullback %.0f%% deep (a quiet one is shallower)" % out["pullback_pct"])
    out["warnings"] = warn
    if "catalyst" in gap and gap["catalyst"] is None:
        out["note"] = "no SEC filing at the gap: find the catalyst in the news before trusting it"
    elif "catalyst" not in gap:
        out["note"] = "catalyst not checked (no SEC data): confirm it in the news"
    if not near_now:
        if touched:
            out.update(state="bounced", why="touched the 20-EMA earlier, now %+.1f%% above it" % out["to_ema_pct"])
        else:
            out.update(state="running",
                       why="%+.1f%% above the 20-EMA; wait for a quiet pullback to it" % out["to_ema_pct"])
        return out
    out["plan"] = plan
    if warn:
        out.update(state="loose", why="; ".join(warn))
    elif last.c > prev.h:
        out.update(state="triggered", why="closed above the prior day's high at the 20-EMA")
    else:
        out.update(state="setup", why="at the 20-EMA on %.2fx volume, gap holding" % (vr or 0))
    return out


def weekly_bars(bars):
    weeks = {}
    for b in bars:
        weeks.setdefault(b.d.isocalendar()[:2], []).append(b)
    out = []
    for k in sorted(weeks):
        w = weeks[k]
        out.append(Bar(w[0].d, w[0].o, max(x.h for x in w), min(x.l for x in w), w[-1].c, sum(x.v for x in w)))
    return out


def pead(bars, gap):
    """Weekly red-candle breakout after an earnings gap (PEAD)."""
    if gap is None:
        return {"state": "none", "why": "no gap of %.0f%%+ in the last %d days" % (GAP_MIN, EP_WINDOW)}
    gd = datetime.date.fromisoformat(gap["date"])
    wk = weekly_bars(bars)
    gi = max(i for i, w in enumerate(wk) if w.d <= gd)
    after = wk[gi + 1:]
    cat = gap.get("catalyst")
    out = {"gap_date": gap["date"], "weeks_since": len(after),
           "earnings": bool(cat and cat["earnings"]) if "catalyst" in gap else None,
           "running_week": bars[-1].d.weekday() < 4}
    if len(after) > PEAD_WEEKS:
        out.update(state="expired", why="gap %d weeks ago (window %d)" % (len(after), PEAD_WEEKS))
        return out
    if bars[-1].c < gap["low"]:
        out.update(state="failed", why="under the gap-day low %.2f" % gap["low"])
        return out
    done = after[:-1] if out["running_week"] else after
    reds = [i for i, w in enumerate(done) if w.c < w.o]
    if not reds:
        out.update(state="monitoring", why="no red weekly candle since the gap yet")
        return out
    r = done[reds[-1]]
    risk = r.h - r.l
    out.update(red_week=r.d.isoformat(), entry=r.h, stop=r.l, risk_pct=(1 - r.l / r.h) * 100,
               target_2r=r.h + 2 * risk)
    if out["risk_pct"] > 10:
        out["warning"] = "wide stop: the red week spans %.0f%%" % out["risk_pct"]
    later = done[reds[-1] + 1:]  # only finished weeks confirm a breakout
    broke = [w for w in later if w.c > r.h and w.c >= w.o]
    if broke:
        out.update(state="breakout", why="week of %s closed above the red week's high" % broke[0].d.isoformat())
    elif out["running_week"] and bars[-1].c > r.h:
        out.update(state="signal ready", why="the running week trades above the red week's high; "
                                             "a breakout needs the Friday close")
    else:
        out.update(state="signal ready", why="buy stop above the red week's high")
    return out


def bursts(bars, days=5):
    """Stockbee's 4 % breakout in the last `days` bars."""
    out = []
    for i in range(max(4, len(bars) - days), len(bars)):
        b, p = bars[i], bars[i - 1]
        chg = pct(b.c, p.c)
        if chg is None or chg < 4 or b.v <= p.v or b.v < 100000:
            continue
        up3 = all(bars[j].c > bars[j - 1].c for j in range(i - 3, i))
        if up3 or clv(b) < 0.7:
            continue
        ranges = [x.h - x.l for x in bars[i - 3:i]]
        a = atr(bars[:i])
        out.append({"date": b.d.isoformat(), "change_pct": chg, "volume_vs_prior": b.v / p.v if p.v else None,
                    "close_in_range": clv(b), "quiet_before": bool(a and avg(ranges) < a)})
    return out


def volume(bars):
    vols = [b.v for b in bars]
    v50 = avg(vols[-51:-1])
    up = sum(b.v for p, b in zip(bars[-51:], bars[-50:]) if b.c > p.c)
    dn = sum(b.v for p, b in zip(bars[-51:], bars[-50:]) if b.c < p.c)
    pairs = list(zip(bars[-26:], bars[-25:]))
    return {"relative": bars[-1].v / v50 if v50 else None,
            "dryup_10_50": avg(vols[-10:]) / avg(vols[-50:]) if avg(vols[-50:]) else None,
            "up_down_50": up / dn if dn else None,
            "distribution_25": sum(1 for p, b in pairs if pct(b.c, p.c) <= -0.2 and b.v > p.v),
            "accumulation_25": sum(1 for p, b in pairs if pct(b.c, p.c) >= 0.2 and b.v > p.v)}


def analyse(ticker, data, bench=None, sec_filings=None, sec_note=None):
    bars, meta = data
    if len(bars) < 60:
        raise T.DataError("%s: only %d daily bars" % (ticker, len(bars)))
    a = atr(bars)
    gl = gaps(bars, sec_filings=sec_filings)
    latest = gl[-1] if gl else None
    earn = [g for g in gl if g.get("catalyst") and g["catalyst"]["earnings"]]
    r = {"ticker": ticker.upper(), "name": meta.get("name"), "currency": meta.get("currency"),
         "date": bars[-1].d.isoformat(), "price": bars[-1].c,
         "atr14": a, "atr_pct": a / bars[-1].c * 100 if a else None,
         "rsi14": T.rsi([b.c for b in bars]),
         "stage": trend_template(bars, bench),
         "vcp": vcp(bars, atr_val=a),
         "gaps": gl, "catalyst_source": sec_note,
         "multi_edge": multi_edge(bars, latest),
         "pead": pead(bars, earn[-1] if earn else latest),  # PEAD wants the earnings gap
         "bursts": bursts(bars),
         "volume": volume(bars)}
    if r["vcp"].get("valid") and not r["stage"]["stage"].endswith("stage 2"):
        r["vcp"]["note"] = "careful: a VCP is a stage 2 pattern and this chart is %s" % r["stage"]["stage"]
    r["active"] = active(r)
    return r


def active(r):
    """The setups worth a look today, strongest first."""
    out = []
    if r["vcp"].get("valid") and r["vcp"]["state"] in ("breakout", "near pivot", "breakout on light volume"):
        out.append("vcp " + r["vcp"]["state"])
    if r["multi_edge"]["state"] in ("triggered", "setup"):
        out.append("multi-edge " + r["multi_edge"]["state"])
    if r["pead"]["state"] in ("breakout", "signal ready"):
        out.append("pead " + r["pead"]["state"])
    if r["gaps"] and r["gaps"][-1]["ep"] and r["gaps"][-1]["days_ago"] <= 1:
        out.append("ep day %d" % (r["gaps"][-1]["days_ago"] + 1))
    if r["bursts"]:
        out.append("burst %s" % r["bursts"][-1]["date"])
    return out


# ---------------------------------------------------------------- output

f = T.f


def gap_line(g):
    cat = g.get("catalyst", "?")
    if cat == "?":
        c = "catalyst unknown (no SEC data)"
    elif cat is None:
        c = "no 8-K/6-K around that day (check /trader-news)"
    else:
        c = "%s %s %s" % (cat["form"], cat["filed"], cat["what"] if cat["form"] == "8-K" or cat["items"]
                                  else "foreign issuer report (often earnings)")
    return "%s %s gap %+.1f%% (day %+.1f%%) on %.1fx volume, close at %d%% of the range, %s; %s, %+.1f%% since%s" % (
        "EP " if g["ep"] else "gap", g["date"], g["gap_pct"], g["day_pct"], g["volume_x"],
        round(g["close_in_range"] * 100), c, g["held"], g["since_pct"],
        "  (ran %+.0f%% in the 3 months before)" % g["run_before_pct"] if g["run_before_pct"] and g["run_before_pct"] > 50 else "")


def render(r):
    s, v, me, pe, vo = r["stage"], r["vcp"], r["multi_edge"], r["pead"], r["volume"]
    out = ["%s  %s  %s %.2f on %s   ATR14 %s (%s%%)  RSI14 %s" % (
        r["ticker"], r["name"] or "", r["currency"] or "", r["price"], r["date"],
        f(r["atr14"], "%.2f"), f(r["atr_pct"], "%.1f"), f(r["rsi14"], "%.0f"))]
    out.append("  stage      %s: %d/%d trend template  (RS vs SPY %s points, %s%% over the 52w low, %s%% from the high)%s" % (
        s["stage"].upper(), s["passed"], s["of"], f(s["rs_vs_bench"], "%+.1f"), f(s["above_low_pct"], "%+.0f"),
        f(s["from_high_pct"], "%+.1f"), ("\n             missing: " + "; ".join(s["failed"])) if s["failed"] else ""))
    if v.get("waves") and v.get("depths"):
        waves = " > ".join("%.0f%%" % d for d in v["depths"])
        line = "  vcp        %s: %d waves %s since %s, pivot %.2f (price %s%% vs pivot), stop %.2f, dry-up %s" % (
            v["state"].upper(), len(v["depths"]), waves, v["base_start"], v["pivot"],
            f(v["vs_pivot_pct"], "%+.1f"), v["stop"], f(v["dryup"], "%.2f"))
        if v.get("breakout_date"):
            line += "\n             crossed the pivot on %s on %sx the 50-day volume" % (
                v["breakout_date"], f(v["breakout_volume"], "%.1f"))
        for note in (v.get("why"), v.get("note")):
            if note:
                line += "\n             " + note
        out.append(line)
    else:
        out.append("  vcp        %s: %s" % (v["state"].upper(), v.get("why", "")))
    if r["gaps"]:
        for g in r["gaps"][-3:]:
            out.append("  gap        " + gap_line(g))
    else:
        out.append("  gap        none of %.0f%%+ on %.0fx volume in the last %d days" % (GAP_MIN, GAP_VOL, EP_WINDOW))
    line = "  multi-edge %s: %s" % (me["state"].upper(), me.get("why", ""))
    if me.get("plan"):
        p = me["plan"]
        line += "\n             entry above %.2f  stop %.2f (-%.1f%%)  2R %.2f  | 20-EMA %.2f  pullback %.1f%% on %sx volume" % (
            p["entry"], p["stop"], p["risk_pct"], p["target_2r"], me["ema20"], me["pullback_pct"],
            f(me["pullback_volume_x"], "%.2f"))
    if me.get("note") and me["state"] in ("setup", "triggered", "loose"):
        line += "\n             " + me["note"]
    out.append(line)
    line = "  pead       %s: %s" % (pe["state"].upper(), pe.get("why", ""))
    if pe.get("entry"):
        line += "  (red week %s: entry %.2f  stop %.2f  -%.1f%%  2R %.2f)" % (
            pe["red_week"], pe["entry"], pe["stop"], pe["risk_pct"], pe["target_2r"])
        if pe.get("warning"):
            line += "\n             " + pe["warning"]
        if pe.get("earnings") is False:
            line += "\n             note: no earnings 8-K at the gap, so this is not a classic PEAD"
    out.append(line)
    if r["bursts"]:
        out.append("  burst      " + "; ".join("%s %+.1f%% on %.1fx the prior day's volume%s" % (
            b["date"], b["change_pct"], b["volume_vs_prior"] or 0, ", quiet before" if b["quiet_before"] else "")
            for b in r["bursts"]))
    else:
        out.append("  burst      none in the last 5 days")
    out.append("  volume     today %sx  dry-up 10/50 %s  up/down 50d %s  distribution %d / accumulation %d of 25 days" % (
        f(vo["relative"], "%.1f"), f(vo["dryup_10_50"], "%.2f"), f(vo["up_down_50"], "%.2f"),
        vo["distribution_25"], vo["accumulation_25"]))
    return "\n".join(out)


def table(results):
    rows = ["%-7s %-16s %-6s %s" % ("ticker", "stage", "RS", "active setups")]
    for r in sorted(results, key=lambda r: (-len(r["active"]), -(r["stage"]["passed"]))):
        rows.append("%-7s %-16s %-6s %s" % (r["ticker"], r["stage"]["stage"][:16],
                                            f(r["stage"]["rs_vs_bench"], "%+.0f"),
                                            ", ".join(r["active"]) or "-"))
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--benchmark", default=T.BENCHMARK, help="relative strength vs. this (default SPY, '' for none)")
    ap.add_argument("--offline", help="read <TICKER>-1d.json (and SEC files) from this folder")
    ap.add_argument("--no-sec", action="store_true", help="skip the SEC catalyst lookup")
    ap.add_argument("--user-agent", help="SEC user agent: 'Your Name you@example.com'")
    ap.add_argument("--out", help="write the results JSON here (trader/setups.json)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    bench = None
    if a.benchmark:
        try:
            bench = [(b.d, b.c) for b in load(a.benchmark, a.offline)[0]]
        except T.DataError as e:
            print("benchmark skipped: %s" % e, file=sys.stderr)
    sec = None if a.no_sec else Sec(user_agent(a.user_agent), a.offline)
    sec_note = "skipped" if a.no_sec else None
    if sec is not None and not sec.available():
        sec, sec_note = None, "no SEC user agent (set SEC_USER_AGENT)"
    results, errors = [], []
    for t in a.tickers:
        try:
            data = load(t, a.offline)
        except T.DataError as e:
            errors.append(str(e))
            continue
        filings, note = None, sec_note
        if sec is not None:
            try:
                filings, note = sec.filings(t), "SEC EDGAR 8-K/6-K"
            except T.DataError as e:
                note = str(e)
        try:
            results.append(analyse(t, data, bench, filings, note))
        except T.DataError as e:
            errors.append(str(e))
    doc = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "Yahoo Finance chart API (unofficial, delayed, adjusted); catalysts from SEC EDGAR",
           "results": results, "errors": errors}
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        if len(results) > 1:
            print(table(results) + "\n")
        print("\n\n".join(render(r) for r in results))
        for e in errors:
            print("ERROR %s" % e, file=sys.stderr)
        print("\nSetups describe the chart, not the future. Most fail; every one comes with its stop.")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
