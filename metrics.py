"""
metrics.py - pure return math. No Yahoo calls, no Streamlit.

Given the price history and the latest quotes from data.py, this module produces one row
per symbol with: last price, previous close, intraday %, 1W, 1M, 3M, MTD, YTD, 1Y and a
30-day sparkline series.

Conventions
  * Returns are plain fractions (0.05 = +5 %). The UI multiplies by 100 for display.
  * Multi-period returns are calendar based:  return = last / price_on_or_before(anchor) - 1
      1W  -> 7 calendar days ago         MTD -> last close of the previous month
      1M  -> 1 month ago                 YTD -> last close of the previous year
      3M  -> 3 months ago                1Y  -> 1 year ago
  * When base_currency != LOCAL, the whole price series is converted with the FX series
    BEFORE returns are computed, so every return includes the currency effect.
  * Commodities are never converted - they stay in their own unit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RETURN_COLS = ["intraday", "1W", "1M", "3M", "MTD", "YTD", "1Y"]


# --------------------------------------------------------------------------- #
# FX helpers
# --------------------------------------------------------------------------- #
def fx_to_usd(fx_cfg: dict, ccy: str, series_by_symbol: pd.DataFrame) -> pd.Series | None:
    """
    Return a daily series that converts 1 unit of `ccy` into USD.

    Yahoo has two naming styles and universe.yaml lists both:
      AUDUSD=X  -> quote is AUD/USD (USD per 1 AUD)      -> use as is
      BRL=X     -> quote is USD/BRL (BRL per 1 USD)      -> invert it
    We detect the style from the symbol name, so adding e.g. `CLP: CLP=X` just works.
    Returns None if the currency has no FX entry (or is USD itself -> caller treats as 1).
    """
    ccy = ccy.upper()
    if ccy == "USD":
        return None
    sym = fx_cfg.get(ccy)
    if not sym or sym not in series_by_symbol.columns:
        return None
    ser = pd.to_numeric(series_by_symbol[sym], errors="coerce").ffill()
    if sym.upper().startswith(ccy) and sym.upper().endswith("USD=X"):
        return ser                      # already USD per 1 unit of ccy
    return 1.0 / ser                    # quoted as ccy per 1 USD -> invert


def convert_series(prices: pd.Series, ccy: str, base: str, fx_cfg: dict, fx_hist: pd.DataFrame) -> pd.Series:
    """Convert a local-currency price series into `base` (USD, BRL, ...). LOCAL = no change."""
    base = base.upper()
    if base == "LOCAL" or ccy.upper() == base:
        return prices
    # local -> USD
    to_usd = fx_to_usd(fx_cfg, ccy, fx_hist)
    usd = prices if to_usd is None else prices * to_usd.reindex(prices.index).ffill()
    # USD -> base
    base_to_usd = fx_to_usd(fx_cfg, base, fx_hist)
    if base_to_usd is None:            # base is USD (or unknown, in which case we stay in USD)
        return usd
    return usd / base_to_usd.reindex(prices.index).ffill()


def latest_rate(ccy: str, base: str, fx_cfg: dict, fx_hist: pd.DataFrame) -> float:
    """Most recent conversion factor: 1 unit of `ccy` = `rate` units of `base`."""
    one = pd.Series([1.0], index=[fx_hist.index[-1]] if len(fx_hist) else [pd.Timestamp.today().normalize()])
    converted = convert_series(one, ccy, base, fx_cfg, fx_hist)
    val = converted.iloc[-1] if len(converted) else np.nan
    return float(val) if not pd.isna(val) else np.nan


# --------------------------------------------------------------------------- #
# Return math
# --------------------------------------------------------------------------- #
def _price_on_or_before(series: pd.Series, when: pd.Timestamp) -> float:
    """Last available price at or before `when` (handles weekends/holidays)."""
    val = series.asof(when)
    return float(val) if val is not None and not pd.isna(val) else np.nan


def period_returns(series: pd.Series) -> dict[str, float]:
    """Calendar-based returns for one already-converted price series (index = dates)."""
    series = series.dropna()
    out = {k: np.nan for k in RETURN_COLS if k != "intraday"}
    if series.empty:
        return out
    last_date = series.index[-1]
    last = float(series.iloc[-1])

    anchors = {
        "1W": last_date - pd.Timedelta(days=7),
        "1M": last_date - pd.DateOffset(months=1),
        "3M": last_date - pd.DateOffset(months=3),
        "1Y": last_date - pd.DateOffset(years=1),
        # "last close of the previous month/year" = the last price strictly before day 1
        "MTD": last_date.replace(day=1) - pd.Timedelta(days=1),
        "YTD": pd.Timestamp(year=last_date.year - 1, month=12, day=31),
    }
    first_date = series.index[0]
    for key, anchor in anchors.items():
        if anchor < first_date:         # not enough history for this period
            continue
        base = _price_on_or_before(series, anchor)
        out[key] = last / base - 1 if base and not np.isnan(base) else np.nan
    return out


def splice_live_price(hist: pd.Series, last: float, last_date) -> pd.Series:
    """
    Put the live quote at the end of the history series.

    History is cached for hours, quotes for a minute, so the last history point may be
    stale. Overwriting/adding the latest date makes every return use the fresh price.
    """
    hist = hist.dropna().copy()
    if last is None or np.isnan(last) or pd.isna(last_date):
        return hist
    hist.loc[pd.Timestamp(last_date).normalize()] = float(last)
    return hist.sort_index()


def sparkline(series: pd.Series, days: int = 30) -> list[float]:
    """Last `days` calendar days of the series as a plain list (for LineChartColumn)."""
    series = series.dropna()
    if series.empty:
        return []
    cutoff = series.index[-1] - pd.Timedelta(days=days)
    return [round(float(v), 4) for v in series[series.index > cutoff]]


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def compute_table(cfg: dict, close: pd.DataFrame, adj: pd.DataFrame, quotes: pd.DataFrame,
                  base_currency: str, return_type: str) -> pd.DataFrame:
    """
    Build one row per company and per (non-manual) commodity.

    Columns: name, ticker, exchange, ccy, commodity, stage, kind, unit, is_company,
             last, prev_close, intraday, 1W, 1M, 3M, MTD, YTD, 1Y, spark, display_ccy
    """
    hist_src = adj if return_type == "total" else close
    fx_cfg = cfg.get("fx", {})
    rows = []

    def build_row(meta: dict, symbol: str, ccy: str, convert: bool) -> dict:
        q = quotes.loc[symbol] if symbol in quotes.index else None
        last = float(q["last"]) if q is not None else np.nan
        prev = float(q["prev_close"]) if q is not None else np.nan
        last_date = q["last_date"] if q is not None else pd.NaT

        raw_hist = hist_src[symbol] if symbol in hist_src.columns else pd.Series(dtype="float64")
        series = splice_live_price(raw_hist, last, last_date)

        display_ccy = ccy
        if convert and base_currency.upper() != "LOCAL":
            # convert the series (returns include FX) and the two quote prices
            series = convert_series(series, ccy, base_currency, fx_cfg, close)
            rate = latest_rate(ccy, base_currency, fx_cfg, close)
            last, prev = last * rate, prev * rate
            display_ccy = base_currency.upper()

        rets = period_returns(series)
        intraday = last / prev - 1 if prev and not np.isnan(prev) and not np.isnan(last) else np.nan
        return {
            **meta,
            "ticker": symbol,
            "display_ccy": display_ccy,
            "last": last,
            "prev_close": prev,
            "intraday": intraday,
            **rets,
            "spark": sparkline(series),
        }

    for c in cfg["companies"]:
        meta = {"name": c["name"], "exchange": c.get("exchange", ""), "ccy": c["ccy"],
                "commodity": c.get("commodity", "Other"), "stage": c["stage"], "kind": "company",
                "unit": c["ccy"], "is_company": True}
        rows.append(build_row(meta, c["yahoo"], c["ccy"], convert=True))

    for c in cfg["commodities"]:
        meta = {"name": c["name"], "exchange": "", "ccy": "", "commodity": "", "stage": "",
                "kind": c.get("kind", "futures"), "unit": c.get("unit", ""), "is_company": False}
        if c.get("kind") == "manual" or not c.get("yahoo"):
            price = c.get("price")
            rows.append({**meta, "ticker": "manual", "display_ccy": "",
                         "last": float(price) if price is not None else np.nan,
                         "prev_close": np.nan, "as_of": c.get("as_of"),
                         **{k: np.nan for k in RETURN_COLS}, "spark": []})
        else:
            rows.append(build_row(meta, c["yahoo"], "", convert=False))

    df = pd.DataFrame(rows)
    if "as_of" not in df.columns:
        df["as_of"] = None
    return df


# --------------------------------------------------------------------------- #
# Aggregations for the summary section
# --------------------------------------------------------------------------- #
def _rebase(spark: list[float]) -> list[float]:
    """Scale a sparkline so it starts at 100 - lets us average lines of different price levels."""
    if not spark or spark[0] == 0:
        return []
    return [v / spark[0] * 100 for v in spark]


def _mean_spark(sparks: list[list[float]]) -> list[float]:
    rebased = [_rebase(s) for s in sparks if s]
    if not rebased:
        return []
    n = min(len(s) for s in rebased)            # align on the shortest series (from the end)
    arr = np.array([s[-n:] for s in rebased])
    return [round(float(v), 2) for v in arr.mean(axis=0)]


def summary_table(table: pd.DataFrame, group_order: list[str], stage_order: list[str]) -> pd.DataFrame:
    """
    Equal-weighted average returns by commodity group and by stage (companies only).
    Rows: one per group (in universe.yaml order), then one per stage, then "All companies".
    """
    comp = table[table["is_company"]].copy()
    blocks = []

    def agg(label: str, sub: pd.DataFrame) -> dict:
        row = {"group": label, "n": int(len(sub))}
        for col in RETURN_COLS:
            row[col] = float(sub[col].mean()) if sub[col].notna().any() else np.nan
        row["spark"] = _mean_spark(sub["spark"].tolist())
        return row

    for g in group_order:
        sub = comp[comp["commodity"] == g]
        if len(sub):
            blocks.append(agg(g, sub))
    for s in stage_order:
        sub = comp[comp["stage"] == s]
        if len(sub):
            blocks.append(agg(f"All {s}s", sub))
    blocks.append(agg("All companies", comp))
    return pd.DataFrame(blocks)
