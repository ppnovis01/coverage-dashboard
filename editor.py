"""
editor.py - saving universe.yaml from inside the dashboard (the "Edit" view).

Two places a change can go:
  1. The local file universe.yaml (always).
  2. GitHub, via the Contents API (only when a token is configured). This is what makes
     edits stick on Streamlit Community Cloud, whose file system is wiped on every restart.

The GitHub token lives in Streamlit secrets (never in the code):
    .streamlit/secrets.toml locally, or App settings -> Secrets on Streamlit Cloud
        [github]
        token = "github_pat_..."
        repo  = "ppnovis01/coverage-dashboard"
        branch = "main"
"""

from __future__ import annotations

import base64
import warnings
from pathlib import Path

import requests
import streamlit as st
import yaml

UNIVERSE_PATH = Path(__file__).with_name("universe.yaml")

# Order of the keys inside a company / commodity line, so the file stays readable.
COMPANY_KEYS = ["name", "yahoo", "exchange", "ccy", "commodity", "stage"]
COMMODITY_KEYS = ["name", "yahoo", "unit", "kind", "price", "as_of"]

# Comments written next to each setting so the file stays self-explanatory.
SETTING_NOTES = {
    "refresh_seconds": "how often live prices update",
    "history_years": "years of history to download",
    "base_currency": "options: LOCAL, USD, BRL",
    "return_type": "options: total (dividend-adjusted), price",
    "columns": "company-table columns, in order (Edit view)",
}


# --------------------------------------------------------------------------- #
# YAML writing (keeps the same one-line-per-name layout as the original file)
# --------------------------------------------------------------------------- #
def _flow(row: dict, keys: list[str]) -> str:
    """One company/commodity as a single-line YAML mapping, e.g. {name: X, yahoo: Y, ...}."""
    ordered = {k: row.get(k) for k in keys if k in row}
    return yaml.safe_dump(ordered, default_flow_style=True, sort_keys=False, allow_unicode=True,
                          width=10_000).strip()


def _scalar(v) -> str:
    """A single value (or short list) as YAML text, e.g. 60, LOCAL, [stage, price]."""
    text = yaml.safe_dump({"k": v}, default_flow_style=True, sort_keys=False, width=10_000).strip()
    return text[len("{k: "):-1]                 # strip the surrounding "{k: " and "}"


def to_yaml_text(cfg: dict) -> str:
    """Render the whole config as universe.yaml text."""
    s = cfg["settings"]
    lines = ["settings:"]
    for k, v in s.items():
        note = SETTING_NOTES.get(k, "")
        lines.append(f"  {k}: {_scalar(v)}" + (f"{' ' * max(1, 28 - len(k) - len(_scalar(v)))}# {note}" if note else ""))
    lines += ["", "fx:                           # used to convert local prices to base_currency"]
    for ccy, sym in cfg.get("fx", {}).items():
        lines.append(f"  {ccy}: {sym}")
    lines += ["", "companies:"]
    for c in cfg.get("companies", []):
        lines.append(f"  - {_flow(c, COMPANY_KEYS)}")
    lines += ["", "commodities:"]
    for c in cfg.get("commodities", []):
        lines.append(f"  - {_flow(c, COMMODITY_KEYS)}")
    return "\n".join(lines) + "\n"


def save_local(cfg: dict) -> str:
    """Write universe.yaml on disk and return the text that was written."""
    text = to_yaml_text(cfg)
    yaml.safe_load(text)                       # make sure what we wrote parses back
    UNIVERSE_PATH.write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
def github_settings() -> dict | None:
    """Token/repo/branch from Streamlit secrets, or None when not configured."""
    try:
        gh = st.secrets["github"]
        if not gh.get("token"):
            return None
        return {"token": gh["token"], "repo": gh.get("repo", "ppnovis01/coverage-dashboard"),
                "branch": gh.get("branch", "main")}
    except Exception:
        return None


def push_to_github(text: str, message: str) -> tuple[bool, str]:
    """
    Commit universe.yaml to GitHub. Returns (ok, human message).
    Uses the Contents API: read the current file's sha, then PUT the new content.
    """
    gh = github_settings()
    if gh is None:
        return False, "No GitHub token configured - saved locally only."
    url = f"https://api.github.com/repos/{gh['repo']}/contents/universe.yaml"
    headers = {"Authorization": f"Bearer {gh['token']}", "Accept": "application/vnd.github+json"}
    try:
        cur = requests.get(url, headers=headers, params={"ref": gh["branch"]}, timeout=20)
        sha = cur.json().get("sha") if cur.status_code == 200 else None
        body = {"message": message, "branch": gh["branch"],
                "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        r = requests.put(url, headers=headers, json=body, timeout=20)
        if r.status_code in (200, 201):
            return True, f"Saved to GitHub ({gh['repo']}, branch {gh['branch']}). The public app updates in about a minute."
        return False, f"GitHub refused the save ({r.status_code}): {r.json().get('message', r.text)[:200]}"
    except Exception as exc:
        return False, f"Could not reach GitHub: {exc}"


# --------------------------------------------------------------------------- #
# Symbol check used by the "Add" form
# --------------------------------------------------------------------------- #
def check_symbol(symbol: str) -> tuple[bool, str]:
    """Ask Yahoo for one symbol. Returns (ok, 'currency / last price' or an error)."""
    import yfinance as yf
    warnings.filterwarnings("ignore")
    try:
        fi = yf.Ticker(symbol).fast_info
        px, ccy = fi.get("lastPrice"), fi.get("currency")
        if px is None:
            return False, "Yahoo has no price for this symbol"
        return True, f"{ccy} {px:,.2f}"
    except Exception:
        return False, "Yahoo does not recognise this symbol"
