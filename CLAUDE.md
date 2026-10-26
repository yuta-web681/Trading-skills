# Arbeitsweise in diesem Repo

- Antworte auf Deutsch.
- Ziel des Nutzers: langfristiges Investieren in ETFs und Aktien (Deutschland, Steuerinländer).
- Bei Investoren-Portfolios (trader-copycat) immer **mehrere Portfolios vergleichen**, nie nur eines.
  Standard-Set: Berkshire Hathaway, Pershing Square, Baupost, Akre Capital, plus weitere passende
  langfristige Value/Quality-Investoren aus `investing/trader-copycat/filers.json`.
- Ranking der Aktien: Wie viele der Investoren halten die Aktie (Überschneidung), Gewicht im jeweiligen
  Portfolio, dann trader-analyst-Kennzahlen und trader-screener-Score.
- Immer Stand und Alter der 13F-Daten nennen (bis zu 45 Tage alt). Keine Anlageberatung.
- trader-tax rechnet nach US-Recht und passt nicht für Deutschland. Nur UCITS-ETFs (ISIN IE/LU), keine US-ETFs.
- Budget und ETF-Quote legt der Nutzer erst ganz am Schluss fest.
- SEC_USER_AGENT ist als Umgebungsvariable gesetzt; nichts Persönliches ins Repo committen.
