# Trading Skills

Sammlung von Claude-Skills für Investieren und Trading. Beide Pakete stammen von
**Jake Schincariol** und stehen unter der MIT-Lizenz (siehe `LICENSE` im jeweiligen Ordner).

| Ordner | Quelle | Inhalt |
| --- | --- | --- |
| `investing/` | [Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill) (Commit `unknown`) | 11 Skills fürs langfristige Investieren |
| `day-trading/` | [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (Commit `3d0f4ef`) | 11 Skills fürs Day Trading |

Beide Pakete benutzen teilweise dieselben Skill-Namen (z. B. `trader-risk`), die Inhalte
unterscheiden sich aber. Installiere deshalb pro Umgebung nur eines der beiden Pakete
oder nutze die Plugin-Variante, bei der die Namen getrennt sind.

## investing/ (trader-skill)

- **trader-copycat:** Portfolio bekannter Investoren aus 13F-Meldungen nachbauen
- **trader-analyst:** Quartalszahlen aus SEC-Daten
- **trader-screener:** Aktien nach eigenen Regeln filtern
- **trader-budget:** Positionsgrößen mit Cash-Reserve und Obergrenze
- **trader-rebalance:** Zurück auf Zielgewichte
- **trader-risk:** Jede Order gegen Limits prüfen (PASS/BLOCK)
- **trader-broker:** Order-Tickets für Alpaca/IBKR, nur nach ausdrücklichem Ja
- **trader-news**, **trader-alerts**, **trader-tax**, **trader-pelosi**

## day-trading/ (day-trader-skill)

- **trader-scanner:** Charts von rund 5.900 US-Aktien nach Setups durchsuchen
- **trader-entry** / **trader-exit:** Ein- und Ausstieg planen
- **trader-timemachine:** Strategien über viele historische Sessions durchspielen
- **trader-risk**, **trader-budget**, **trader-broker**, **trader-news**, **trader-alerts**, **trader-analyst**, **trader-pelosi**

## Installation

**Claude Code als Plugin** (die Namen werden getrennt, z. B. `/trader-skill:trader-copycat`):

```
/plugin marketplace add yuta-web681/Trading-skills
/plugin install trader-skill@trading-skills
/plugin install day-trader-skill@trading-skills
```

**Manuell:** Die `trader-*`-Ordner eines Pakets nach `~/.claude/skills/` kopieren.

**Voraussetzungen:** Python 3.8+, keine pip-Pakete. Die SEC verlangt Name und E-Mail:
`"sec_user_agent": "Name mail@example.com"` in `trader/config.json` oder die Umgebungsvariable `SEC_USER_AGENT`.

## Wichtig

- Ausgelegt auf **US-Aktien und ETFs** und die Broker **Alpaca** und **Interactive Brokers**.
  CFD- und Forex-Broker wie XM oder IC Trading (MT4/MT5, cTrader) werden nicht unterstützt.
- Paper Trading ist voreingestellt. Optionen, Margin, Leerverkäufe und Hebel sind aus.
- `trader-tax` rechnet nach US-Steuerrecht und passt nicht für Deutschland.
- Keine Anlageberatung. Die meisten Day Trader verlieren Geld.
