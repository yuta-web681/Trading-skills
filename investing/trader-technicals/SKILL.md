---
name: trader-technicals
description: >-
  Chart Check. A long-term investor's look at the chart and the calendar of
  a stock: trend (price vs. the 50- and 200-day averages and the slope of the
  200-day), daily and weekly RSI, 52-week range and drawdown from the high,
  the nearest support and resistance from swing points, 1m to 10y returns,
  the biggest drawdown, strength vs. SPY, and month-by-month seasonality over
  15 years with a t-value that marks what is noise. Free Yahoo data, adjusted
  for splits and dividends, standard library Python. Use when the user says
  "check the chart", "technical analysis", "is it in an uptrend", "moving
  averages", "RSI", "support and resistance", "seasonality", "best month to
  buy", "Saisonalitaet" or "charttechnisch pruefen".
argument-hint: "TICKER [TICKER ...] [--years 15] [--out trader/technicals.json]"
---

# trader-technicals

Fundamentals say what a company is worth; the chart says what the market is
paying for it right now and how it got there. For a long-term investor the
chart is a timing and risk tool, not a forecast: it shows whether a stock is
in an intact uptrend or a broken one, how stretched it is, how deep its past
falls were, and where buyers stepped in before.

Tool in this folder (standard library Python, network to Yahoo only):

```bash
python3 "${CLAUDE_SKILL_DIR}/technicals.py" --help
```

## What it reads and writes

- Prices: Yahoo Finance's unofficial chart JSON, adjusted closes. Daily bars
  for 11 years, monthly bars for 31 years, plus SPY as the benchmark. Free and
  delayed; one request per ticker and interval with a short pause.
- `--offline DIR` reads `DIR/<TICKER>-1d.json` and `DIR/<TICKER>-1mo.json`
  (the same JSON Yahoo sends) instead of the network.
- Writes `trader/technicals.json` with `--out`; `--json` prints the same.

## What each number means

| Block | Numbers | How to read it |
|---|---|---|
| trend | 50-day and 200-day average, 200-day slope over a month | UPTREND: price above both, 50 above 200, 200 rising. DOWNTREND: the mirror. MIXED: anything between, usually a correction or a turn. |
| momentum | RSI(14) on daily and weekly closes | Above 70 the stock ran hard (overbought zone), below 30 it fell hard (oversold zone). In a strong uptrend RSI can stay above 70 for months. |
| levels | 52-week high and low, drawdown from the high, swing support and resistance, 200-day average | Support is the nearest weekly swing low at least 2 % below the price, resistance the nearest swing high 2 % above. "none (near the high)" means no higher close in two years. |
| returns | 1m, 3m, 6m, 1y, CAGR 3y / 5y / 10y, max drawdown, 1y vs. SPY | The max drawdown is the pain you must sit through to earn the CAGR. |
| seasonality | per calendar month: average, median, share of up years, t-value, excess vs. SPY | t below 2 in absolute terms is printed as noise. A month that is only strong because the whole market is strong shows a small excess vs. SPY. A month with earnings (Netflix in January, Fair Isaac in November) mixes seasonality with earnings reactions. |

## Steps

1. Take the tickers from the user, from `trader/targets.json`
   (`/trader-copycat`) or from `trader/shortlist.json` (`/trader-screener`).
   Use `BRK.B`, it becomes `BRK-B` for Yahoo.
2. Run it:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/technicals.py" MA V MSFT GOOGL --out trader/technicals.json
   ```

   Exit code 1 means no ticker could be read: show the errors.
3. Report per stock: trend label, how stretched it is (RSI, distance to the
   200-day), the levels, the long-run CAGR next to the max drawdown, and the
   next one to three months of seasonality with the noise flag. Always give
   the price date.
4. For a long-term buyer translate it into plain timing notes, for example
   "uptrend but RSI 70: buying in tranches beats one lump", or "below a falling
   200-day: wait for the trend to turn or size smaller". Say clearly that
   the fundamentals (`/trader-analyst`, `/trader-screener`) decide WHAT to
   own; the chart only helps with WHEN and HOW MUCH at once.

## Example: Mastercard on 2026-10-23

```
MA  Mastercard Incorporated  USD 623.60 on 2026-10-23
  trend      UPTREND: price above the 50- and 200-day averages, 50 above 200, 200-day rising
             50d 580.98  200d 532.69  price +17.1% vs 200d  200d slope +0.49%/month
  momentum   RSI14 daily 70  weekly 69  (overbought zone)
  levels     52w 470.05 - 633.21 (-1.5% from the high)  support 551.42  resistance none (near the high)
  returns    1m +11.5%  3m +15.7%  6m +24.1%  1y +9.4%  |  CAGR 3y 18.3%  5y 12.4%  10y 20.5%  |  max DD -41%
             1y vs SPY: -5.0 points
  seasonal   15 complete years (2011-2025); next months:
             Nov  avg  +4.2%  median  +5.6%  up  73% of years  t +2.8  vs SPY +0.9
             Dec  avg  +1.9%  median  +0.6%  up  60% of years  t +1.5  vs SPY +1.6  (noise)
             Jan  avg  +2.1%  median  +5.6%  up  67% of years  t +1.1  vs SPY +0.8  (noise)
```

An intact uptrend at a new high and a stretched RSI. November was strong in
11 of 15 years, but most of that is the market's own November (+0.9 points
over SPY).

## What it never does

- Never predicts a price or calls a buy or a sell. A trend, an RSI and a
  seasonal average describe the past; none of them reliably forecasts
  future returns, and seasonal averages over 15 data points are fragile.
- Never fills a gap in the data: a missing number prints as `-`.
- Never sends anything to `/trader-budget` or an order path by itself.

## Safety

Education and tooling, not financial advice. This skill only reads prices.
Nothing places an order except `/trader-broker`, after `/trader-risk` passes
and the user types an explicit yes for that order.
