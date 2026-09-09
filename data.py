"""
data.py - everything that talks to Yahoo Finance (via the yfinance library).

Two kinds of downloads, each cached separately so they refresh on their own schedule:

  * HISTORY  - two years (configurable) of daily prices for every symbol, one batched
               request. Cached for 6 hours. Used for the multi-period returns and sparklines.
  * QUOTES   - the last few days of prices, one batched request. Cached for
               `refresh_seconds` (default 60 s). Used for the live price and previous close.

Nothing in here knows about the UI. If Yahoo breaks or a symbol is wrong, the functions
return NaN for that symbol plus a list of warnings - they never raise.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
import yfinance as yf

log = logging.getLogger("dashboard.data")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

UNIVERSE_PATH = Path(__file__).with_name("universe.yaml")


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_universe(path: Path = UNIVERSE_PATH) -> dict:
    """Read universe.yaml and fill in defaults so the rest of the app can rely on keys."""
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    settings = cfg.setdefault("settings", {})
    settings.setdefault("refresh_seconds", 60)
    settings.setdefault("history_years", 2)
    settings.setdefault("base_currency", "LOCAL")
    settings.setdefault("return_type", "total")
    settings.setdefault("timezone", "UTC")

    cfg.setdefault("fx", {})
    cfg.setdefault("companies", [])
    cfg.setdefault("commodities", [])

    # Normalise a few things so small typos in the YAML are less likely to bite.
    settings["base_currency"] = str(settings["base_currency"]).upper()
    settings["return_type"] = str(settings["return_type"]).lower()
    for c in cfg["companies"]:
        c["ccy"] = str(c.get("ccy", "USD")).upper()
        c["stage"] = str(c.get("stage", "")).strip()
    return cfg


def all_symbols(cfg: dict) -> list[str]:
    """Every Yahoo symbol we need: companies, non-manual commodities, and FX pairs."""
    syms: list[str] = []
    syms += [c["yahoo"] for c in cfg["companies"] if c.get("yahoo")]
    syms += [c["yahoo"] for c in cfg["commodities"] if c.get("yahoo") and c.get("kind") != "manual"]
    syms += list(cfg["fx"].values())
    seen: set[str] = set()            # keep order, drop duplicates
    return [s for s in syms if not (s in seen or seen.add(s))]


# Settings are read once at import so the cache TTL below can use refresh_seconds.
_SETTINGS = load_universe()["settings"]


# --------------------------------------------------------------------------- #
# History (slow-changing, cached 6 hours)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=6 * 3600, show_spinner="Downloading price history from Yahoo...")
def fetch_history(symbols: tuple[str, ...], years: int) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """
    One batched download of daily history for all symbols.

    Returns (close, adj_close, warnings):
      close      - DataFrame, one column per symbol, plain closing price (price return)
      adj_close  - same shape, dividend/split-adjusted close (total return)
      warnings   - human-readable messages for symbols that returned no data
    Symbols with no data are present as all-NaN columns so downstream code never KeyErrors.
    """
    # This print line is how you verify that history is NOT re-downloaded on every refresh.
    print(f"[data] HISTORY DOWNLOAD at {dt.datetime.now():%H:%M:%S} ({len(symbols)} symbols, {years}y)", flush=True)

    warnings: list[str] = []
    try:
        raw = yf.download(
            list(symbols),
            period=f"{years}y",
            auto_adjust=False,        # keep both Close and Adj Close
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception as exc:  # network down, Yahoo outage, etc.
        warnings.append(f"History download failed entirely: {exc}")
        empty = pd.DataFrame(columns=list(symbols), dtype="float64")
        return empty, empty.copy(), warnings

    close = _extract_field(raw, symbols, "Close")
    adj = _extract_field(raw, symbols, "Adj Close")
    for s in symbols:
        if close[s].dropna().empty:
            warnings.append(f"{s}: no history returned (wrong symbol or delisted?)")
    return close, adj, warnings


def _extract_field(raw: pd.DataFrame, symbols: tuple[str, ...], field: str) -> pd.DataFrame:
    """Pull one field (Close / Adj Close) for every symbol out of yfinance's MultiIndex frame."""
    out = {}
    for s in symbols:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                col = raw[(s, field)]
            else:  # single symbol -> flat columns
                col = raw[field]
            out[s] = pd.to_numeric(col, errors="coerce")
        except Exception:
            out[s] = pd.Series(dtype="float64")
    df = pd.DataFrame(out)
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx
    return df.sort_index()


# --------------------------------------------------------------------------- #
# Quotes (fast-changing, cached refresh_seconds)
# --------------------------------------------------------------------------- #
# TTL is a few seconds shorter than the auto-refresh interval. If they were equal, a rerun
# could arrive a few milliseconds before the cache expired and skip a whole cycle.
QUOTE_TTL = max(10, int(_SETTINGS["refresh_seconds"]) - 5)


@st.cache_data(ttl=QUOTE_TTL, show_spinner=False)
def fetch_quotes(symbols: tuple[str, ...]) -> tuple[pd.DataFrame, list[str], dt.datetime]:
    """
    One batched request for the latest price and previous close of every symbol.

    Returns (quotes, warnings, fetched_at) where quotes has columns:
      last        - most recent price (today's live price while the market is open)
      prev_close  - the close before that
      last_date   - the date of `last`
    Strategy: yf.download(period="5d") is one HTTP call for everything. Only symbols that
    come back empty fall back to Ticker.fast_info (one call each), so a healthy universe
    costs a single request per refresh.
    """
    return _quote_batch(symbols)


def _quote_batch(symbols: tuple[str, ...]) -> tuple[pd.DataFrame, list[str], dt.datetime]:
    """Uncached implementation, shared by the dashboard and check_universe.py."""
    fetched_at = dt.datetime.now(dt.timezone.utc)
    print(f"[data] quote batch at {fetched_at:%H:%M:%S} UTC", flush=True)
    warnings: list[str] = []
    nan = float("nan")
    rows: dict[str, dict] = {s: {"last": nan, "prev_close": nan, "last_date": pd.NaT} for s in symbols}

    try:
        raw = yf.download(list(symbols), period="5d", interval="1d", auto_adjust=False,
                          group_by="ticker", threads=True, progress=False)
        close = _extract_field(raw, symbols, "Close")
    except Exception as exc:
        warnings.append(f"Quote batch failed: {exc}")
        close = pd.DataFrame(columns=list(symbols), dtype="float64")

    failed: list[str] = []
    for s in symbols:
        ser = close[s].dropna() if s in close else pd.Series(dtype="float64")
        if len(ser) >= 2:
            rows[s] = {"last": float(ser.iloc[-1]), "prev_close": float(ser.iloc[-2]), "last_date": ser.index[-1]}
        elif len(ser) == 1:
            rows[s] = {"last": float(ser.iloc[-1]), "prev_close": nan, "last_date": ser.index[-1]}
        else:
            failed.append(s)

    # Fallback for the few (hopefully zero) symbols the batch could not price.
    for s in failed:
        try:
            fi = yf.Ticker(s).fast_info
            last, prev = fi["lastPrice"], fi["previousClose"]
            if last is None or pd.isna(last):
                raise ValueError("no lastPrice")
            rows[s] = {"last": float(last), "prev_close": float(prev) if prev is not None else nan,
                       "last_date": pd.Timestamp(dt.date.today())}
        except Exception:
            warnings.append(f"{s}: no quote available (symbol not found?)")

    quotes = pd.DataFrame.from_dict(rows, orient="index")
    return quotes, warnings, fetched_at
