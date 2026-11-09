#!/usr/bin/env python3
"""Scalable Capital bridge for the trader-* pipeline. Standard library only.

Scalable's official MCP server (https://mcp.scalable.capital/mcp) works with
ISINs and euros; the rest of this pack works with tickers. This tool never
talks to Scalable and never places anything. Claude calls the read-only MCP
tools, saves each raw answer to a file, and this tool turns them into the
files every other skill reads:

  isin      ISIN from a US CUSIP (13F data has CUSIPs), with the check digit.
  map       build trader/isin_map.json (ticker -> ISIN) from a copycat
            targets file, keeping entries you added by hand (ETFs, DE stocks).
  sync      raw get_portfolio_holdings + get_portfolio_cash_breakdown (and
            optional get_security_quote answers) -> trader/portfolio.json and
            trader/prices.json, in EUR, tickers mapped back through the map.
  tickets   trader/orders.json -> one Scalable order form per order: ISIN,
            buy amount in EUR or shares to sell, order type, venue. Claude uses
            it for preview_buy_order / preview_sell_order, or you type it
            into the Scalable app yourself.

    python3 scalable.py isin --cusip 037833100
    python3 scalable.py map --targets trader/targets.json
    python3 scalable.py sync --holdings trader/scalable/holdings.json \\
        --cash trader/scalable/cash.json --quote trader/scalable/quote-KO.json
    python3 scalable.py tickets

Scalable does not publish the JSON shape of its tool answers, so `sync`
searches the answer for objects that carry an ISIN and a quantity. It stops
with an error that names what it found instead of guessing when the shape is
not recognised.
"""

import argparse
import datetime
import json
import math
import os
import re
import sys

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
QTY_KEYS = ("quantity", "shares", "numberofshares", "sharecount", "units", "position", "size",
            "nominal", "pieces")
PRICE_KEYS = ("price", "lastprice", "currentprice", "quoteprice", "last", "mid", "midprice",
              "marketprice", "closeprice")
VALUE_KEYS = ("marketvalue", "currentvalue", "value", "valuation", "totalvalue", "positionvalue")
COST_KEYS = ("averagebuyprice", "averageprice", "avgbuyprice", "avgprice", "buyin", "buyinprice",
             "averagecost", "costbasisprice")
COST_TOTAL_KEYS = ("purchasevalue", "investedamount", "costbasis", "buyinvalue", "totalcost")
NAME_KEYS = ("name", "securityname", "instrumentname", "title", "displayname")
CASH_KEYS = ("cash_balance", "cashbalance", "availablecash", "cash", "settledcash", "balance")


class ScalableError(Exception):
    pass


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise ScalableError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise ScalableError("%s is not valid JSON: %s" % (path, e))


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def unwrap(doc):
    """An MCP tools/call result wraps the payload as content[].text (a JSON
    string) or structuredContent. Accept either, or the bare payload."""
    if isinstance(doc, dict):
        if isinstance(doc.get("structuredContent"), (dict, list)):
            return doc["structuredContent"]
        if isinstance(doc.get("result"), dict) and ("content" in doc["result"] or "structuredContent" in doc["result"]):
            return unwrap(doc["result"])
        content = doc.get("content")
        if isinstance(content, list) and content and all(isinstance(c, dict) for c in content):
            texts = [c.get("text") for c in content if c.get("type", "text") == "text" and c.get("text")]
            if texts:
                try:
                    return json.loads(texts[0])
                except (TypeError, json.JSONDecodeError):
                    raise ScalableError("the tool answer's text is not JSON; save the raw answer as it came")
    return doc


# ---------------------------------------------------------------- ISIN

def _isin_digits(body):
    return "".join(str(int(ch, 36)) for ch in body)


def isin_check_digit(body):
    """Check digit for the first 11 ISIN characters (ISO 6166, Luhn on the digit string)."""
    digits = _isin_digits(body.upper())
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - total % 10) % 10)


def valid_isin(isin):
    isin = str(isin or "").upper()
    return bool(ISIN_RE.match(isin)) and isin_check_digit(isin[:11]) == isin[11]


def isin_from_cusip(cusip, country="US"):
    cusip = str(cusip or "").strip().upper()
    if not re.match(r"^[A-Z0-9]{9}$", cusip):
        raise ScalableError("a CUSIP has 9 letters or digits, not %r" % cusip)
    body = country.upper() + cusip
    return body + isin_check_digit(body)


# ---------------------------------------------------------------- map

def load_map(path):
    doc = read_json(path, "ISIN map", required=False) or {}
    m = doc.get("isins", doc) if isinstance(doc, dict) else {}
    out = {}
    for t, i in m.items():
        if isinstance(i, str):
            out[str(t).upper()] = i.upper()
    return out


def build_map(targets_doc, existing=None):
    """ticker -> ISIN from a copycat targets file (first CUSIP of each row),
    without overwriting what is already in the map."""
    rows = targets_doc.get("weights", targets_doc) if isinstance(targets_doc, dict) else targets_doc
    m = dict(existing or {})
    added, missing = [], []
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("ticker"):
            continue
        t = str(r["ticker"]).upper()
        if t in m:
            continue
        if r.get("isin") and valid_isin(r["isin"]):
            m[t] = str(r["isin"]).upper()
            added.append(t)
        elif r.get("cusips") or r.get("cusip"):
            cusip = (r.get("cusips") or [r.get("cusip")])[0]
            m[t] = isin_from_cusip(cusip)
            added.append(t)
        elif valid_isin(t):
            m[t] = t
        else:
            missing.append(t)
    return m, added, missing


# ---------------------------------------------------------------- reading answers

def num(v):
    """A number from 12.5, "12.5", "1.234,56", {"amount": "12.5", "currency": "EUR"}."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("amount", "value", "decimal", "units"):
            if k in v:
                return num(v[k])
        return None
    if isinstance(v, str):
        s = v.strip().replace(" ", "").replace(" ", "").replace("EUR", "").replace("€", "")
        if re.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$", s) or re.match(r"^-?\d+,\d+$", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _lower(d):
    return {re.sub(r"[^a-z_]", "", str(k).lower()): v for k, v in d.items()}


def _first(d, keys, strip_underscore=True):
    low = _lower(d)
    if strip_underscore:
        low = {k.replace("_", ""): v for k, v in low.items()}
    for k in keys:
        k2 = k.replace("_", "") if strip_underscore else k
        if k2 in low:
            n = num(low[k2])
            if n is not None:
                return n
    return None


def _isin_of(d):
    for k, v in d.items():
        if str(k).lower() == "isin" and isinstance(v, str) and ISIN_RE.match(v.upper()):
            return v.upper()
    for k in ("security", "instrument", "asset"):
        sub = d.get(k)
        if isinstance(sub, dict):
            i = _isin_of(sub)
            if i:
                return i
    return None


def _merged(d):
    """The row plus its nested security/instrument/valuation objects, flat."""
    flat = dict(d)
    for k, v in d.items():
        if isinstance(v, dict) and str(k).lower() in ("security", "instrument", "asset", "valuation",
                                                      "position", "quote", "performance", "price"):
            for k2, v2 in v.items():
                flat.setdefault(k2, v2)
    return flat


def walk(doc):
    if isinstance(doc, dict):
        yield doc
        for v in doc.values():
            for x in walk(v):
                yield x
    elif isinstance(doc, list):
        for v in doc:
            for x in walk(v):
                yield x


def parse_holdings(doc):
    """[{isin, name, shares, price, value, avg_cost}] from a get_portfolio_holdings answer."""
    doc = unwrap(doc)
    found = {}
    isin_rows = 0
    for d in walk(doc):
        isin = _isin_of(d)
        if not isin:
            continue
        isin_rows += 1
        flat = _merged(d)
        qty = _first(flat, QTY_KEYS)
        if qty is None or qty <= 0:
            continue
        value = _first(flat, VALUE_KEYS)
        price = _first(flat, PRICE_KEYS)
        if price is None and value is not None and qty:
            price = value / qty
        if value is None and price is not None:
            value = price * qty
        avg = _first(flat, COST_KEYS)
        total_cost = _first(flat, COST_TOTAL_KEYS)
        if avg is None and total_cost is not None and qty:
            avg = total_cost / qty
        name = None
        for k in NAME_KEYS:
            if isinstance(flat.get(k), str):
                name = flat[k]
                break
        row = found.setdefault(isin, {"isin": isin, "name": name, "shares": 0.0, "price": price,
                                      "value": 0.0, "avg_cost": avg})
        row["shares"] += qty
        row["value"] += value or 0.0
        if row["price"] is None:
            row["price"] = price
    if not found:
        if isin_rows:
            raise ScalableError("the holdings answer has %d ISIN entries but none with a quantity field I know "
                                "(%s); show Claude the raw file so the parser can learn the shape"
                                % (isin_rows, ", ".join(QTY_KEYS[:4])))
        empty = isinstance(doc, dict) and any(isinstance(v, list) and not v for v in doc.values())
        if empty:
            return []
        raise ScalableError("no holdings found in the answer (no object with an ISIN); is this the "
                            "get_portfolio_holdings answer?")
    return sorted(found.values(), key=lambda r: -(r["value"] or 0))


def parse_cash(doc):
    """Cash in EUR from get_portfolio_cash_breakdown. Never buying power or credit."""
    doc = unwrap(doc)
    for d in walk(doc):
        low = {re.sub(r"[^a-z_]", "", str(k).lower()): v for k, v in d.items()}
        for k in CASH_KEYS:
            for cand in (k, k.replace("_", "")):
                if cand in low:
                    n = num(low[cand])
                    if n is not None:
                        return n
    raise ScalableError("no cash balance in the cash answer (looked for %s); buying power is not used "
                        "because it can include credit" % ", ".join(CASH_KEYS[:3]))


def parse_quote(doc):
    """(isin, price) from a get_security_quote answer."""
    doc = unwrap(doc)
    for d in walk(doc):
        flat = _merged(d)
        isin = _isin_of(flat)
        price = _first(flat, PRICE_KEYS)
        if price is None:
            bid, ask = _first(flat, ("bid", "bidprice")), _first(flat, ("ask", "askprice"))
            if bid and ask:
                price = (bid + ask) / 2
        if isin and price:
            return isin, price
    raise ScalableError("no ISIN with a price in the quote answer")


# ---------------------------------------------------------------- sync

def sync(holdings_doc, cash_doc, quote_docs, isin_map, old_portfolio=None, today=None):
    today = today or datetime.date.today().isoformat()
    by_isin = {i: t for t, i in isin_map.items()}
    rows = parse_holdings(holdings_doc)
    cash = parse_cash(cash_doc)
    old = {str(p.get("ticker", "")).upper(): p for p in (old_portfolio or {}).get("positions", [])}
    positions, prices, unmapped = [], {}, []
    for r in rows:
        t = by_isin.get(r["isin"])
        if not t:
            t = r["isin"]
            unmapped.append(r["isin"])
        pos = {"ticker": t, "isin": r["isin"], "shares": round(r["shares"], 6)}
        if r.get("name"):
            pos["name"] = r["name"]
        prev = old.get(t)
        if prev and prev.get("lots") and abs(float(prev.get("shares", 0)) - pos["shares"]) < 1e-6:
            pos["lots"] = prev["lots"]
        elif r.get("avg_cost"):
            pos["lots"] = [{"id": "%s-scalable" % t, "date": today, "shares": pos["shares"],
                            "cost": round(r["avg_cost"] * pos["shares"], 2), "note": "average buy-in from Scalable"}]
        positions.append(pos)
        if r.get("price"):
            prices[t] = round(r["price"], 4)
    for qd in quote_docs:
        isin, price = parse_quote(qd)
        prices[by_isin.get(isin, isin)] = round(price, 4)
    stamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    portfolio = {"cash": round(cash, 2), "currency": "EUR", "source": "scalable", "as_of": stamp,
                 "positions": positions}
    price_doc = {"as_of": stamp, "source": "scalable", "currency": "EUR", "prices": prices}
    return portfolio, price_doc, unmapped


# ---------------------------------------------------------------- tickets

def _money(v):
    return "{:,.2f} EUR".format(float(v)).replace(",", "X").replace(".", ",").replace("X", ".")


def order_form(order, isin_map, prices, venue=None):
    sym = str(order.get("symbol", "")).upper()
    isin = isin_map.get(sym) or (sym if valid_isin(sym) else None)
    side = str(order.get("side", "")).lower()
    form = {"symbol": sym, "isin": isin, "side": side, "venue": venue or "default (Scalable picks)",
            "order_type": str(order.get("type", "market"))}
    problems = []
    if not isin:
        problems.append("no ISIN for %s: add it to trader/isin_map.json" % sym)
    elif not valid_isin(isin):
        problems.append("%s is not a valid ISIN (check digit)" % isin)
    if form["order_type"] not in ("market", "limit"):
        problems.append("Scalable tickets here cover market and limit orders only, not %s" % form["order_type"])
    if order.get("limit_price") is not None:
        form["limit_price_eur"] = float(order["limit_price"])
    if side == "buy":
        if order.get("notional") is not None:
            form["amount_eur"] = round(float(order["notional"]), 2)
        else:
            form["shares"] = float(order.get("qty"))
            if form["shares"] != math.floor(form["shares"]):
                problems.append("a share-based buy at Scalable takes whole shares; buy by amount instead")
    elif side == "sell":
        if order.get("qty") is not None:
            form["shares"] = float(order["qty"])
        else:
            p = prices.get(sym)
            if not p:
                problems.append("a sell at Scalable is share-based; no EUR price for %s to convert %s"
                                % (sym, order.get("notional")))
            else:
                form["shares"] = math.floor(float(order["notional"]) / p * 10000) / 10000.0
                form["shares_from_amount"] = "%s / %s" % (_money(order["notional"]), _money(p))
    else:
        problems.append("side must be buy or sell")
    form["preview_tool"] = "preview_%s_order" % side if side in ("buy", "sell") else None
    form["problems"] = problems
    return form


def render_form(i, n, form):
    what = (_money(form["amount_eur"]) + " of") if "amount_eur" in form else (
        "%s shares of" % ("{:g}".format(form.get("shares", 0))))
    how = ("limit %s" % _money(form["limit_price_eur"])) if "limit_price_eur" in form else "market order"
    lines = ["SCALABLE ORDER %d of %d" % (i, n),
             "  %s %s %s (ISIN %s), %s, venue %s" % (form["side"].upper(), what, form["symbol"],
                                                     form["isin"] or "?", how, form["venue"])]
    if form.get("shares_from_amount"):
        lines.append("  shares worked out from %s, rounded down" % form["shares_from_amount"])
    for p in form["problems"]:
        lines.append("  PROBLEM: " + p)
    if not form["problems"]:
        lines.append("  Claude: %s with this ISIN, quantity and order type; show the whole userReview;"
                     % form["preview_tool"])
        lines.append("  the order is only placed after your separate yes (or in the Scalable app).")
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

def cmd_isin(a):
    print(isin_from_cusip(a.cusip, a.country))
    return 0


def cmd_map(a):
    existing = load_map(a.isin_map)
    m, added, missing = build_map(read_json(a.targets, "targets file"), existing)
    write_json(a.isin_map, {"isins": dict(sorted(m.items()))})
    print("ISIN map %s: %d entries, %d new%s." % (a.isin_map, len(m), len(added),
                                                  (" (" + ", ".join(added) + ")") if added else ""))
    if missing:
        print("No CUSIP or ISIN for: %s. Add them by hand (ETFs: the IE/LU ISIN)." % ", ".join(missing))
        return 1
    return 0


def cmd_sync(a):
    isin_map = load_map(a.isin_map)
    quotes = [read_json(q, "quote answer") for q in (a.quote or [])]
    portfolio, prices, unmapped = sync(read_json(a.holdings, "holdings answer"),
                                       read_json(a.cash, "cash answer"), quotes, isin_map,
                                       read_json(a.portfolio, "portfolio", required=False), a.today)
    write_json(a.portfolio, portfolio)
    old_prices = read_json(a.prices, "prices", required=False) or {}
    if old_prices.get("currency") not in (None, "EUR") or (old_prices and old_prices.get("source") != "scalable"):
        print("note: replacing %s (it was from %s, not Scalable EUR prices)" % (a.prices, old_prices.get("source")))
    write_json(a.prices, prices)
    total = portfolio["cash"] + sum(p["shares"] * prices["prices"].get(p["ticker"], 0) for p in portfolio["positions"])
    print("Synced from Scalable: %d positions, cash %s, about %s in total (EUR)."
          % (len(portfolio["positions"]), _money(portfolio["cash"]), _money(total)))
    for p in portfolio["positions"]:
        print("  %-8s %-12s %12s shares  %s" % (p["ticker"], p["isin"], "{:g}".format(p["shares"]),
                                                p.get("name", "")))
    if unmapped:
        print("Not in the ISIN map, kept under their ISIN: %s. Add a ticker in %s if your targets use one."
              % (", ".join(unmapped), a.isin_map))
    return 0


def cmd_tickets(a):
    doc = read_json(a.orders, "orders file (run trader-budget or trader-rebalance first)")
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not orders:
        raise ScalableError("no orders in %s" % a.orders)
    isin_map = load_map(a.isin_map)
    pdoc = read_json(a.prices, "prices", required=False) or {}
    prices = pdoc.get("prices", pdoc) if isinstance(pdoc, dict) else {}
    forms = [order_form(o, isin_map, prices, a.venue) for o in orders]
    if a.json:
        print(json.dumps(forms, indent=2))
    else:
        print("\n\n".join(render_form(i, len(forms), f) for i, f in enumerate(forms, 1)))
        print("\nEach order needs its own trader-risk PASS and your own yes (ticket.py). "
              "Not financial advice.")
    return 1 if any(f["problems"] for f in forms) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scalable Capital bridge (ISINs, EUR). Never places orders.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("isin", help="ISIN from a CUSIP")
    p.add_argument("--cusip", required=True)
    p.add_argument("--country", default="US")
    p = sub.add_parser("map", help="ticker -> ISIN map from a targets file")
    p.add_argument("--targets", default="trader/targets.json")
    p.add_argument("--isin-map", default="trader/isin_map.json")
    p = sub.add_parser("sync", help="Scalable answers -> trader/portfolio.json and trader/prices.json")
    p.add_argument("--holdings", default="trader/scalable/holdings.json")
    p.add_argument("--cash", default="trader/scalable/cash.json")
    p.add_argument("--quote", action="append", help="a saved get_security_quote answer (repeatable)")
    p.add_argument("--isin-map", default="trader/isin_map.json")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--prices", default="trader/prices.json")
    p.add_argument("--today")
    p = sub.add_parser("tickets", help="orders -> Scalable order forms")
    p.add_argument("--orders", default="trader/orders.json")
    p.add_argument("--isin-map", default="trader/isin_map.json")
    p.add_argument("--prices", default="trader/prices.json")
    p.add_argument("--venue", choices=["gettex", "xetra", "eix"])
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"isin": cmd_isin, "map": cmd_map, "sync": cmd_sync, "tickets": cmd_tickets}[a.cmd](a)
    except ScalableError as e:
        print("scalable.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
