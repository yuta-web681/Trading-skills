---
name: trader-technicals
description: >-
  Chart Check. A long-term investor's look at the chart and the calendar of
  a stock: trend (price vs. the 50- and 200-day averages and the slope of the
  200-day), daily and weekly RSI, 52-week range and drawdown from the high,
  the nearest support and resistance from swing points, 1m to 10y returns,
  the biggest drawdown, strength vs. SPY, and month-by-month seasonality over
  15 years with a t-value that marks what is noise. Plus swing setups on
  daily OHLCV: Minervini's stage 2 trend template and VCP, Stockbee's
  Episodic Pivot with the SEC 8-K catalyst, J Law's Multi-Edge pullback to
  the 20-day EMA after a catalyst gap, PEAD red-candle breakouts, 4 %
  Momentum Bursts and volume (dry-up, distribution days), each with entry,
  stop and risk. Free Yahoo and SEC data, adjusted for splits and dividends,
  standard library Python. Use when the user says "check the chart",
  "technical analysis", "is it in an uptrend", "moving averages", "RSI",
  "support and resistance", "seasonality", "best month to buy", "stage 2",
  "VCP", "episodic pivot", "Multi-Edge", "pullback to the 20-day", "PEAD",
  "momentum burst", "Setup", "Saisonalitaet" or "charttechnisch pruefen".
argument-hint: "TICKER [TICKER ...] [--years 15] [--out trader/technicals.json] | setups TICKER ..."
---

# trader-technicals

Fundamentals say what a company is worth; the chart says what the market is
paying for it right now and how it got there. For a long-term investor the
chart is a timing and risk tool, not a forecast: it shows whether a stock is
in an intact uptrend or a broken one, how stretched it is, how deep its past
falls were, and where buyers stepped in before.

Tools in this folder (standard library Python, network to Yahoo and SEC only):

```bash
python3 "${CLAUDE_SKILL_DIR}/technicals.py" --help   # long-term chart check and seasonality
python3 "${CLAUDE_SKILL_DIR}/setups.py" --help       # swing setups: stage 2, VCP, EP, Multi-Edge, PEAD
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

## Setups (setups.py)

`setups.py` reads daily open, high, low, close and volume (three years, the
same Yahoo source, open/high/low scaled to the adjusted close) and looks for
the setups that swing traders such as Mark Minervini, Pradeep Bonde
(Stockbee) and J Law teach. The rules are rebuilt from the MIT-licensed
[tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills)
(vcp-screener, stockbee-episodic-pivot-analyzer, pead-screener,
stockbee-momentum-burst-screener), without their paid FMP data.

```bash
python3 "${CLAUDE_SKILL_DIR}/setups.py" NVDA SHOP LLY --out trader/setups.json
```

With more than one ticker it prints a table first (stage, RS, active setups,
strongest first), then one block per ticker.

| Block | Rule | States |
|---|---|---|
| stage | Minervini's trend template, 8 checks: price above the 50/150/200-day, 50 > 150 > 200, 200-day rising for 22 days, at least 30 % above the 52-week low, within 25 % of the high, RS vs. SPY (3/6/9/12 months weighted 40/20/20/20) at least +5 points | STAGE 2 (all), ALMOST (6-7), NOT STAGE 2, STAGE 4 (under a falling 200-day) |
| vcp | The base starts at the highest high of 200 days. Swing waves (zigzag of 1.5 ATR, 2.5-8 %, coarser if the fine one is noise) must number two or more, the first 8-50 % deep, each at least 25 % shallower than the last, no swing high 15 % under the base high, base at least 3 weeks old. Pivot = high of the last wave, stop = its low, dry-up = 10-day / 50-day volume | BASE FORMING, NEAR PIVOT (within 5 %), BREAKOUT (close over the pivot on 1.4x volume), BREAKOUT ON LIGHT VOLUME, EXTENDED (> 5 % over), NO VCP with the reason |
| gap / EP | Last 60 days: gap of 3 %+ on 2x the 50-day volume. EP (Stockbee Day 1) = gap 4 %+, 3x volume, close in the upper half. With SEC data: the 8-K/6-K filed that day or up to 4 days before, item 2.02 = earnings. Also: did the gap hold, the move since, and a warning if the stock ran 50 %+ in the 3 months before | per gap: EP or gap, catalyst, holding / dipped / gap filled |
| multi-edge | J Law: after the latest catalyst gap (within 40 days) the stock runs, then pulls back to the 20-day EMA (low within 1 %) on lower volume than before the gap, the gap-day low holds, price above the 50-day. Entry above the day's high, stop under the pullback low, 2R target | RUNNING (wait), SETUP, TRIGGERED (close over the prior high), LOOSE (pullback volume high, deep, under the 50-day), BOUNCED, FAILED (under the gap low), EXPIRED |
| pead | Earnings gap (3 %+), then weekly candles for 5 weeks: the latest red week sets entry (its high) and stop (its low) | MONITORING, SIGNAL READY, BREAKOUT, FAILED, EXPIRED; warns when the red week is wider than 10 % |
| burst | Stockbee 4 % breakout in the last 5 days: +4 % close to close, volume above the prior day and 100k, close in the top 30 % of the range, not after three up days; "quiet before" when the 3 days before were narrower than the ATR | list of days |
| volume | today vs. the 50-day, 10/50 dry-up, up/down volume over 50 days, distribution (down 0.2 %+ on higher volume) and accumulation days over 25 days | numbers |

SEC catalysts need a user agent with name and email (`SEC_USER_AGENT`,
`sec_user_agent` in `trader/config.json`, or `--user-agent`); `--no-sec`
skips them. A gap without a filing may still have a catalyst (an analyst
call, a contract in the press): check `/trader-news` before trusting it.
Non-US companies file 6-Ks, which carry no item numbers.

How to use it as a long-term investor: the setups are a timing aid for a
stock that `/trader-copycat`, `/trader-analyst` and `/trader-screener`
already picked. A SETUP or NEAR PIVOT says "a lower-risk entry with a clear
stop is here now", RUNNING or EXTENDED says "do not chase, wait for the
pullback", STAGE 4 says "the trend is down, do not average down yet". Run
it after the US close: during the session the last bar is unfinished.

### Example: Shopify on 2026-10-23

```
SHOP  Shopify Inc.  USD 168.68 on 2026-10-23   ATR14 7.50 (4.4%)  RSI14 58
  stage      ALMOST STAGE 2: 6/8 trend template  (RS vs SPY +17.4 points, +79% over the 52w low, -7.4% from the high)
             missing: 150-day above the 200-day; 200-day rising for a month
  gap        gap 2026-09-22 gap +4.8% (day +7.1%) on 2.7x volume, close at 59% of the range, no 8-K/6-K around that day (check /trader-news); dipped under the gap-day low since, +14.2% since
  multi-edge SETUP: at the 20-EMA on 0.90x volume, gap holding
             entry above 170.47  stop 162.44 (-4.7%)  2R 186.54  | 20-EMA 164.84  pullback 9.7% on 0.90x volume
             no SEC filing at the gap: find the catalyst in the news before trusting it
```

A textbook-looking pullback to the 20-day EMA on lighter volume, but the gap
had no SEC filing, so the catalyst must be confirmed first, and the 200-day
is not rising yet.

## What it never does

- Never predicts a price or calls a buy or a sell. A trend, an RSI and a
  seasonal average describe the past; none of them reliably forecasts
  future returns, and seasonal averages over 15 data points are fragile.
- Never fills a gap in the data: a missing number prints as `-`.
- Never sends anything to `/trader-budget` or an order path by itself. An
  entry and stop from `setups.py` are a plan for the user to look at, not
  an order; most setups fail, which is why each one comes with its stop.

## Safety

Education and tooling, not financial advice. This skill only reads prices.
Nothing places an order except `/trader-broker`, after `/trader-risk` passes
and the user types an explicit yes for that order.
