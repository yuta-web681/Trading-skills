---
name: trader-broker
description: >-
  Order Executor. Places APPROVED orders through your brokerage connector, one
  at a time, and never without your explicit yes. Shows each order as a plain
  ticket plus the exact JSON for Alpaca's place_stock_order, records your yes
  word for word, then Claude's own Allow once / Deny card asks again. Covers
  setting up Alpaca's official MCP server in Claude Desktop (paper trading by
  default, keys in env vars, never in chat), the Interactive Brokers connector
  (orders go to your IBKR account for your approval), Scalable Capital's
  official MCP server (German broker, ISINs and euros, read-only access level
  recommended; scalable.py syncs holdings and cash into trader/portfolio.json),
  and setting order tools to "Needs approval". Use when the user says "place the orders", "buy it",
  "execute", "send it to my broker", "connect Alpaca", "connect Interactive
  Brokers", "set up paper trading", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches the market only after three
separate gates, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **The user clicked Allow once** on Claude's own permission card, which
   appears because the order tool is set to "Needs approval".

Two yeses from the user, one PASS from the rules. No yes, no order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ID
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol AAPL --side buy --qty 3.6628 --price 341.27
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, and keeps the log in `trader/state/broker.json`.

## Setup A: Alpaca (official MCP server, Claude Desktop)

Alpaca's own server is github.com/alpacahq/alpaca-mcp-server (MIT). It runs on
the user's computer inside Claude Desktop. It is not in Claude's connector
directory. It trades on a **paper** account unless told otherwise.

1. The user makes an Alpaca account and creates **paper trading** API keys in
   the Alpaca dashboard. Paper keys are separate from live keys.
2. The user installs `uv` (it provides `uvx`), from docs.astral.sh/uv.
3. In Claude Desktop: Settings > Developer > Edit Config. That opens
   `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`,
   Windows: `%APPDATA%\Claude\`). The user adds this block (also in
   `claude_desktop_config.example.json` here) and types their own keys into the file:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "paste your paper key here, in this file only",
        "ALPACA_SECRET_KEY": "paste your paper secret here, in this file only",
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,stock-data"
      }
    }
  }
}
```

   The `env` block hands the keys to the server as environment variables.
   **Keys never go in the chat.** Never ask for them, never read this file
   back into the conversation, and if the user pastes a key anyway, tell them
   to delete that message and make new keys in the Alpaca dashboard.
   `ALPACA_PAPER_TRADE` is already true by default; writing it makes it
   visible. `ALPACA_TOOLSETS` is optional and hides the tools they do not need.
4. Restart Claude Desktop.
5. **Set the tool permissions.** Customize > Connectors (Settings > Connectors
   in older versions), open alpaca, and for each tool pick Always allow, Needs
   approval or Blocked:
   - `place_stock_order`: **Needs approval**. Never Always allow.
   - every other tool that places, changes, cancels or closes anything
     (`cancel_order_by_id`, `close_position`, `update_account_config`): Needs approval.
   - `place_option_order`, `place_crypto_order`, `close_all_positions`,
     `cancel_all_orders`, `exercise_options_position`: **Blocked** unless the
     user has a reason and says so.
   - read-only tools (`get_account_info`, `get_all_positions`, `get_stock_snapshot`,
     `get_stock_latest_quote`): Always allow is fine.
6. Check it: ask Claude for the Alpaca account info (read only) and confirm
   in the Alpaca dashboard that it is the paper account.

In Claude Code instead of Claude Desktop, keep the order tool on ask in
`.claude/settings.json`: `"permissions": {"ask": ["mcp__alpaca__place_stock_order"]}`,
and never put an order tool in `allow`.

## Setup B: Interactive Brokers (connector in Claude's directory)

Interactive Brokers publishes a verified connector: claude.ai/directory/interactive-brokers
(connector URL `https://api.ibkr.com/v1/api/mcp`). Add it from Customize >
Connectors > Browse connectors and sign in to IBKR there, not in the chat.
Its listing says Claude can draft trade instructions that are sent to the
user's IBKR account for their review and approval, and that Claude never
submits orders directly to the market. So with IBKR the final yes happens in
IBKR as well. Set `"broker": "ibkr"` in `trader/config.json`, and size with
`--whole-shares` if IBKR wants share counts. Set its tools that draft orders
to Needs approval too.

## Setup C: Scalable Capital (official MCP server, German broker)

Scalable Capital runs an official MCP server at `https://mcp.scalable.capital/mcp`
(OAuth sign-in with 2FA in the browser, no keys). It is a German broker, so it
withholds Abgeltungsteuer and Soli itself and honours the Freistellungsauftrag.
Scalable charges nothing extra for the MCP access; normal broker fees apply.
There is **no paper account**: every order is real money.

1. In the Scalable web app: Profile > Security > Agentic Investing. Pick the
   access level. **Read-only** is the recommended start: Claude sees holdings,
   cash, transactions, quotes and savings plans and can preview orders, but
   cannot change anything. "Limited" adds watchlists, price alerts and portfolio
   groups. Only "Full access" allows orders and savings plans. The level counts
   for every AI assistant at once.
2. In Claude (web): Customize > Connectors > Add custom connector, URL
   `https://mcp.scalable.capital/mcp`, then sign in to Scalable in the window it
   opens, never in the chat. The connector then also shows up in Claude Desktop.
   Claude Code: `claude mcp add --transport http scalable https://mcp.scalable.capital/mcp`.
   Access is time limited; when a tool answers that the sign-in expired, the
   user reconnects in the connector settings.
3. Tool permissions (Customize > Connectors > Scalable):
   - `submit_buy_order`, `submit_sell_order`, `submit_savings_plan`,
     `cancel_order`, `remove_savings_plan`: **Needs approval**, or **Blocked**
     while the access level is Read-only. Never Always allow.
   - every other `create_`, `add_`, `remove_`, `upsert_` tool: Needs approval.
   - read tools (`get_portfolio_holdings`, `get_portfolio_cash_breakdown`,
     `get_portfolio_overview`, `list_portfolio_transactions`, `list_savings_plans`,
     `get_security_quote`, `search_securities`, `preview_buy_order`,
     `preview_sell_order`, `preview_savings_plan`): Always allow is fine.
4. In `trader/config.json`: `"broker": "scalable"`. Amounts in the config
   (`budget`, `max_order_usd`, `min_order_usd`) are then read as euros.

Scalable works with ISINs and euros; the pack works with tickers. `scalable.py`
bridges the two and never talks to Scalable itself:

```bash
python3 "${CLAUDE_SKILL_DIR}/scalable.py" map --targets trader/targets.json   # ticker -> ISIN (from 13F CUSIPs)
python3 "${CLAUDE_SKILL_DIR}/scalable.py" sync          # saved answers -> portfolio.json + prices.json (EUR)
python3 "${CLAUDE_SKILL_DIR}/scalable.py" tickets       # orders.json -> ISIN, EUR amount, shares to sell
```

**Sync (read only, any access level).** Call `get_portfolio_holdings` and
`get_portfolio_cash_breakdown`, save each raw answer unchanged to
`trader/scalable/holdings.json` and `trader/scalable/cash.json`. For target
stocks not yet held, call `get_security_quote` per ISIN and save it as
`trader/scalable/quote-<TICKER>.json`. Then run `scalable.py sync` with a
`--quote` for each. It writes `trader/portfolio.json` (cash is the cash balance,
never buying power, which can include credit) and `trader/prices.json` in EUR,
so trader-rebalance, trader-budget and trader-risk run on the real depot. ETFs
and German stocks have no CUSIP: add them to `trader/isin_map.json` by hand
(`{"isins": {"EUNL": "IE00B4L5Y983"}}`) or use the ISIN itself as the ticker in
the targets. If `sync` says it does not recognise the answer, show the user the
error, not the file contents, and stop.

**Orders.** Same three gates as above, adapted to Scalable's own two-step flow:
1. trader-risk PASS for that exact order today, 2. the user's explicit yes on
the ticket (`ticket.py approve`), 3. `scalable.py tickets` gives the ISIN and
EUR amount (buys by amount; sells in shares), Claude calls `preview_buy_order`
or `preview_sell_order` and shows the **whole** `userReview` with every
acknowledgement text, translated, nothing rounded. Then:
- Read-only level (recommended): the user places the order in the Scalable app
  with exactly those values. If Scalable returns a `brokerHandoff.url` because
  submitting is blocked, give the user that link.
- Full access: only after a second, separate yes to that review, call the
  matching `submit_` tool with the preview's `submission` unchanged and exactly
  the acknowledgement IDs the user accepted; Claude's Allow once card follows.
  A preview expires; a changed order needs a new preview and a new yes. After a
  timeout or unknown outcome, never retry: check the app.

Record the outcome with `ticket.py result` as usual, then re-sync instead of `ticket.py fill`.

## Steps, for each order

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/trader-risk`.
2. Show ONE ticket and ask: "Place this order? Reply yes or no." One order
   per question. Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not an explicit yes for this
   order (for example "sure", "yes to all", or a yes that names a different
   stock or amount). Ask again. Never turn a reply into a yes yourself.
4. Only after "Recorded your yes", call `place_stock_order` with exactly the
   JSON the ticket printed. Claude's card appears: Allow once or Deny.
5. Record what happened: `ticket.py result --index N --status placed
   --broker-id <id from the response>`, or `--status denied` if they pressed
   Deny, or `--status failed` with `--note` for an error. A failed order is
   not retried without a new check and a new yes.
6. When the fill is known (the tool's response, or later from
   `get_all_positions`), `ticket.py fill` adds it to `trader/portfolio.json`
   as a tax lot for trader-tax. Then the next ticket.

## Example: the reel

```
ORDER 1 of 5, PAPER account, Alpaca
  BUY $1,250 of AAPL, market order, good for today
  READY: trader-risk PASS, waiting for your yes
  Claude will call place_stock_order with exactly:
    {"symbol": "AAPL", "side": "buy", "notional": "1250",
     "type": "market", "time_in_force": "day"}
```

The user replies "yes". Claude records it, calls `place_stock_order`, and the
card reads "Claude wants to use Place stock order" with that JSON and two
buttons: Allow once, Deny. Allow once sends it to the paper account.

## What it never does

- Never places an order without all three gates, and never two orders on one yes.
- Never places orders from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats API keys or passwords.
- Never switches `ALPACA_PAPER_TRADE` or `"paper"` to live. The user does that themselves.
- Never raises the Scalable access level, and never submits a Scalable order without its own preview and a fresh yes.
- Never calls `close_all_positions`, `cancel_all_orders`, option or crypto order tools on its own.

## Safety

- Education and tooling, not financial advice. No order here is a recommendation, and nothing promises returns.
- Paper trading by default (`"paper": true`, `ALPACA_PAPER_TRADE` true). Going live is the user's own decision.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
