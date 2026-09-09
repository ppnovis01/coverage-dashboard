# Coverage Dashboard

A one-screen Streamlit dashboard for a small equity + commodity coverage list.
Prices come from Yahoo Finance. Everything you might want to change lives in **one file:
`universe.yaml`**. You never need to touch the Python code.

## 1. Run it on your computer

Requirements: Python 3.11 or newer.

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

A browser tab opens at http://localhost:8501. Leave the terminal window open while you use it.

The first load downloads two years of history (a few seconds). After that, prices refresh
every 60 seconds automatically; history is refreshed only every 6 hours.

## 2. Check your symbols

Whenever you add or change a name, run:

```bash
python check_universe.py
```

It prints every symbol with its resolved Yahoo name, currency, last price and OK/FAIL.
Fix any FAIL row in `universe.yaml` before starting the dashboard (usually it is the
exchange suffix: `.AX` for ASX, `.TO` for TSX, nothing for NYSE/NASDAQ).

## 3. Editing `universe.yaml`

### Add a company
Copy one line in the `companies:` list and change the values:

```yaml
  - {name: My New Miner, yahoo: ABC.AX, exchange: ASX, ccy: AUD, commodity: Copper, stage: Developer}
```

* `yahoo` – the ticker exactly as it appears on finance.yahoo.com
* `exchange` – ASX, TSX, NYSE or NASDAQ (drives the open/closed badge)
* `ccy` – the currency the stock trades in (AUD, CAD, USD…). If you add a new currency,
  also add its FX pair under `fx:` (see below).
* `commodity` – the group heading. A new name creates a new section automatically.
  Sections appear in the order in which they first appear in the file.
* `stage` – `Producer` or `Developer`. Producers are listed first inside each group.

### Remove a company
Delete its line. Restart the app (`Ctrl+C` in the terminal, then `streamlit run app.py` again).

### Add a commodity
Add a line under `commodities:`:

```yaml
  - {name: Nickel (LME), yahoo: NI=F, unit: USD/t, kind: futures}
```

`kind` is `futures`, `proxy` (an ETF or trust that tracks the commodity) or `manual`.

If a name contains a comma, wrap it in double quotes, e.g. `name: "Uranium (Sprott, proxy)"`,
otherwise YAML thinks the comma starts a new field.

### Update the manual NdPr price
NdPr oxide has no Yahoo quote, so you type it in by hand:

```yaml
  - {name: NdPr oxide (manual, SMM), yahoo: null, unit: USD/kg, kind: manual, price: 62.5, as_of: 2026-09-09}
```

The card shows the price greyed out with the `as_of` date. Manual rows never call Yahoo.

### Add a currency
Under `fx:` add the Yahoo FX symbol. Two naming styles exist and both are handled:

```yaml
fx:
  AUD: AUDUSD=X     # quote is USD per 1 AUD
  BRL: BRL=X        # quote is BRL per 1 USD (the app inverts it)
```

### Change the refresh interval or other settings

```yaml
settings:
  refresh_seconds: 60        # how often live prices update (keep >= 60 to be kind to Yahoo)
  history_years: 2           # how much history to download for returns/sparklines
  base_currency: USD         # default currency shown at startup: LOCAL, USD or BRL
  return_type: total         # total (dividends reinvested) or price
  timezone: America/Sao_Paulo
```

Settings changes need a restart of the app. Currency and return type can also be switched
live in the sidebar.

## 4. What the numbers mean

* **Price** – latest Yahoo price in the stock's own currency, or converted to USD/BRL when
  selected in the sidebar. Commodities are always in their own unit.
* **Intraday %** – change versus the previous close.
* **1W / 1M / 3M / 1Y** – change versus the price 7 days / 1 / 3 months / 1 year earlier
  (calendar based).
* **MTD / YTD** – change versus the last close of the previous month / year.
* **Total vs Price** – Total return assumes dividends are reinvested (Yahoo "Adj Close");
  Price return ignores dividends. Only dividend payers differ.
* When a currency other than LOCAL is selected, returns include the currency move.
* **Summary** – simple equal-weighted averages of the company rows in each group/stage.

Some thinly traded futures (for example UX=F) have very little history on Yahoo, so their
returns show `n/a` even though the price is fine.

## 5. Deploy to Streamlit Community Cloud (free)

1. Put this folder in a GitHub repository (all files, including `.streamlit/config.toml`).
2. Go to https://share.streamlit.io, sign in with GitHub, click **New app**.
3. Choose the repository, branch `main`, main file `app.py`, and click **Deploy**.
4. To change the universe later, edit `universe.yaml` on GitHub; the app redeploys itself.

Note: Yahoo Finance sometimes rate-limits cloud servers. If the app shows many `n/a`
values after a deploy, wait a few minutes and press **Refresh now** in the sidebar.

## 6. Files

| File | Role |
|------|------|
| `universe.yaml` | **The only file you edit.** Companies, commodities, FX pairs, settings. |
| `app.py` | Screen layout (Streamlit). |
| `data.py` | Downloads from Yahoo Finance, with caching. |
| `metrics.py` | Return calculations and currency conversion. |
| `check_universe.py` | Symbol checker (`python check_universe.py`). |
| `.streamlit/config.toml` | Dark theme and layout. |
| `requirements.txt` | Python packages. |
