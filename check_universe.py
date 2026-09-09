"""
check_universe.py - validate every Yahoo symbol in universe.yaml.

Run it any time you add or change a name:

    python check_universe.py

It prints one line per symbol: symbol, resolved name, currency, last price, OK/FAIL.
Manual commodity rows (kind: manual) are listed but never sent to Yahoo.
"""

from __future__ import annotations

import sys
import warnings

import pandas as pd
import yfinance as yf

import data

warnings.filterwarnings("ignore")


def main() -> int:
    cfg = data.load_universe()

    # (symbol, what we call it in the yaml, section) for everything that should hit Yahoo
    entries: list[tuple[str, str, str]] = []
    entries += [(c["yahoo"], c["name"], "company") for c in cfg["companies"] if c.get("yahoo")]
    entries += [(c["yahoo"], c["name"], "commodity") for c in cfg["commodities"]
                if c.get("yahoo") and c.get("kind") != "manual"]
    entries += [(sym, f"FX {ccy}", "fx") for ccy, sym in cfg["fx"].items()]
    manual = [c for c in cfg["commodities"] if c.get("kind") == "manual" or not c.get("yahoo")]

    symbols = [e[0] for e in entries]
    print(f"Checking {len(symbols)} symbols on Yahoo Finance...\n")

    # One batched request for prices (same code path the dashboard uses).
    quotes, _, _ = data._quote_batch(tuple(symbols))

    # Resolved name + currency need the per-ticker metadata endpoint (one call each).
    rows = []
    failures = 0
    for sym, yaml_name, section in entries:
        last = quotes.loc[sym, "last"] if sym in quotes.index else float("nan")
        resolved, ccy = "", ""
        try:
            fi = yf.Ticker(sym).fast_info
            ccy = fi.get("currency") or ""
        except Exception:
            pass
        try:
            info = yf.Ticker(sym).info
            resolved = info.get("shortName") or info.get("longName") or ""
        except Exception:
            pass
        ok = not pd.isna(last)
        failures += 0 if ok else 1
        rows.append({"symbol": sym, "section": section, "yaml name": yaml_name,
                     "resolved name": resolved[:38], "ccy": ccy,
                     "last price": f"{last:,.4f}" if ok else "", "status": "OK" if ok else "FAIL"})

    for c in manual:
        rows.append({"symbol": "(manual)", "section": "commodity", "yaml name": c["name"],
                     "resolved name": "-", "ccy": c.get("unit", ""),
                     "last price": "" if c.get("price") is None else str(c["price"]),
                     "status": "MANUAL"})

    df = pd.DataFrame(rows)
    with pd.option_context("display.max_columns", None, "display.width", 200, "display.max_colwidth", 40):
        print(df.to_string(index=False))

    print(f"\n{len(symbols) - failures} OK, {failures} FAIL, {len(manual)} manual")
    if failures:
        print("Fix the FAIL rows in universe.yaml (check the Yahoo symbol, e.g. the .AX / .TO suffix).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
