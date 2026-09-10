"""
app.py - the Streamlit user interface.  Run with:  streamlit run app.py

Everything shown here comes from universe.yaml (what to show) + data.py (Yahoo downloads)
+ metrics.py (return math). This file only arranges things on screen.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

import data
import metrics

# --------------------------------------------------------------------------- #
# Page setup
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Coverage Dashboard", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")   # open it with the arrow at the top-left

# Tighten vertical spacing so the whole universe fits on a 1080p screen.
st.markdown(
    """
    <style>
      .block-container { padding-top: 0.8rem; padding-bottom: 0.3rem; }
      h1 { padding-bottom: 0 !important; font-size: 1.8rem !important; }
      h2, h3 { margin-top: 0.2rem !important; margin-bottom: 0.25rem !important; padding: 0.2rem 0 !important;
               font-size: 1.15rem !important; }
      div[data-testid="stVerticalBlock"] { gap: 0.45rem; }
      div[data-testid="stMarkdownContainer"] p { margin-bottom: 0; }
      div[data-testid="stMetric"] { padding: 0.1rem 0.4rem; }
      div[data-testid="stMetricLabel"] p { font-size: 0.78rem; }
      div[data-testid="stMetricValue"] { font-size: 1.25rem; }
      .badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.75rem;
               margin-right:6px; font-weight:600; }
      .open   { background:#1f6f43; color:#e6ffe6; }
      .closed { background:#5a2d2d; color:#ffe6e6; }
      .grp { font-weight:700; font-size:0.85rem; color:#cfcfcf; margin:0.15rem 0 0.05rem 0; }
      .up { color:#3ddc84; } .dn { color:#ff5c5c; } .na { color:#8a8a8a; }
      .manual { color:#8a8a8a; }
      .footer { color:#8a8a8a; font-size:0.78rem; margin-top:0.8rem; }
      .hint { display:block; color:#f0c674; font-size:0.78rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

CFG = data.load_universe()
SETTINGS = CFG["settings"]
TZ = ZoneInfo(SETTINGS["timezone"])
REFRESH = int(SETTINGS["refresh_seconds"])

# Main area must be at least this wide (CSS px) for every table column to show without
# a horizontal scrollbar; the fit-to-screen script never zooms in beyond this.
MIN_MAIN_WIDTH_BASE = 1700 + 86      # +86 for the market cap column
ROW_PX = 26          # table row height in pixels (compact so 12+ names fit on one screen)
HEADER_PX = 35       # the header row is always this tall regardless of row_height
CCY_SYMBOL = {"AUD": "A$", "CAD": "C$", "USD": "US$", "BRL": "R$", "GBP": "£", "EUR": "€"}
RET_LABELS = {"intraday": "Intraday %", "1W": "1W", "1M": "1M", "3M": "3M",
              "MTD": "MTD", "YTD": "YTD", "1Y": "1Y"}

# Local trading hours (regular session) per exchange. Holidays are not modelled.
MARKET_HOURS = {
    "ASX":    ("Australia/Sydney",  dt.time(10, 0), dt.time(16, 0)),
    "TSX":    ("America/Toronto",   dt.time(9, 30), dt.time(16, 0)),
    "NYSE":   ("America/New_York",  dt.time(9, 30), dt.time(16, 0)),
    "NASDAQ": ("America/New_York",  dt.time(9, 30), dt.time(16, 0)),
}


# --------------------------------------------------------------------------- #
# Sidebar controls
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Settings")
    ccy_options = ["LOCAL", "USD", "BRL"]
    default_ccy = SETTINGS["base_currency"] if SETTINGS["base_currency"] in ccy_options else "LOCAL"
    base_currency = st.radio("Currency", ccy_options, index=ccy_options.index(default_ccy), horizontal=True)

    rt_options = ["Total", "Price"]
    default_rt = "Total" if SETTINGS["return_type"] == "total" else "Price"
    return_label = st.radio("Return type", rt_options, index=rt_options.index(default_rt), horizontal=True,
                            help="Total = dividends reinvested (Adj Close). Price = plain close.")
    return_type = return_label.lower()

    show_ids = st.toggle("Show Ticker & Exchange columns", value=False)
    auto_refresh = st.toggle(f"Auto-refresh every {REFRESH}s", value=True)
    fit_screen = st.toggle("Fit to one screen", value=True,
                           help="Scales the main area so everything fits your window height without scrolling.")
    if st.button("Refresh now", use_container_width=True):
        data.fetch_quotes.clear()          # only the quote cache - history stays
        st.rerun()
    warn_box = st.container()              # filled after data loads

if auto_refresh:
    # Re-runs the script every REFRESH seconds. Only fetch_quotes expires that often;
    # fetch_history is cached for 6 h and is NOT re-downloaded by these reruns.
    st_autorefresh(interval=REFRESH * 1000, key="autorefresh")


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
symbols = tuple(data.all_symbols(CFG))
close, adj, hist_warnings = data.fetch_history(symbols, int(SETTINGS["history_years"]))
quotes, quote_warnings, fetched_at = data.fetch_quotes(symbols)
company_symbols = tuple(c["yahoo"] for c in CFG["companies"] if c.get("yahoo"))
shares = data.fetch_shares(company_symbols)

table = metrics.compute_table(CFG, close, adj, quotes, base_currency, return_type, shares)

# Symbols that have neither a quote nor history are the "failed" ones.
failed = sorted({w.split(":")[0] for w in hist_warnings + quote_warnings if ":" in w and not w.startswith("History")})
with warn_box:
    if failed or hist_warnings or quote_warnings:
        st.warning("Symbols with no data (shown as n/a):\n\n" + "\n".join(f"- `{s}`" for s in failed)
                   if failed else "Data warnings")
        with st.expander("Details"):
            for w in hist_warnings + quote_warnings:
                st.caption(w)
    else:
        st.success("All symbols loaded")


# --------------------------------------------------------------------------- #
# Header: title, refresh info, market badges
# --------------------------------------------------------------------------- #
def market_badges() -> str:
    """One green/red pill per exchange in the universe, based on local regular hours."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    exchanges = []
    for c in CFG["companies"]:
        ex = c.get("exchange", "")
        if ex and ex not in exchanges:
            exchanges.append(ex)
    html = []
    for ex in exchanges:
        if ex not in MARKET_HOURS:
            continue
        tzname, open_t, close_t = MARKET_HOURS[ex]
        local = now_utc.astimezone(ZoneInfo(tzname))
        is_open = local.weekday() < 5 and open_t <= local.time() <= close_t
        html.append(f'<span class="badge {"open" if is_open else "closed"}">{ex} {"open" if is_open else "closed"}</span>')
    return "".join(html)


last_refresh_local = fetched_at.astimezone(TZ)
seconds_since = (dt.datetime.now(dt.timezone.utc) - fetched_at).total_seconds()
seconds_left = max(0, int(REFRESH - seconds_since))

h1, h2 = st.columns([3, 2])
with h1:
    st.title("Coverage Dashboard")
with h2:
    st.markdown(
        f"<div style='text-align:right; padding-top:1.2rem'>"
        f"<b>Last refresh:</b> {last_refresh_local:%Y-%m-%d %H:%M:%S} ({SETTINGS['timezone']}) &nbsp;·&nbsp; "
        f"<b>Next in:</b> <span id='cd'>{seconds_left}</span>s<br/>{market_badges()}"
        + (f"<span class='badge closed'>no data: {', '.join(failed)}</span>" if failed else "")
        + "<span id='fit-hint' class='hint'></span></div>",
        unsafe_allow_html=True,
    )
    if auto_refresh:
        # Tiny countdown that ticks in the browser between reruns (purely cosmetic).
        components.html(
            f"""<script>
            let s = {seconds_left};
            const el = window.parent.document.getElementById('cd');
            setInterval(() => {{ s = Math.max(0, s - 1); if (el) el.textContent = s; }}, 1000);
            </script>""",
            height=0,
        )


# --------------------------------------------------------------------------- #
# Helpers for formatting tables
# --------------------------------------------------------------------------- #
def fmt_price(value: float, ccy: str) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    sym = CCY_SYMBOL.get(ccy, ccy + " ")
    decimals = 2 if value >= 1 else 3
    return f"{sym}{value:,.{decimals}f}"


def fmt_time(last_time, last_date) -> str:
    """Time of the last price in the user's timezone: HH:MM today, else dd/mm HH:MM."""
    if last_time is not None and not pd.isna(last_time):
        t = pd.Timestamp(last_time).tz_convert(TZ)
        return f"{t:%H:%M}" if t.date() == dt.datetime.now(TZ).date() else f"{t:%d/%m %H:%M}"
    if last_date is not None and not pd.isna(last_date):
        return f"{pd.Timestamp(last_date):%d/%m}"          # daily data only: show the date
    return "n/a"


def fmt_mcap(value: float) -> str:
    """Market cap as US$1.23B / US$456M."""
    if value is None or np.isnan(value):
        return "n/a"
    if value >= 1e9:
        return f"US${value / 1e9:,.2f}B"
    return f"US${value / 1e6:,.0f}M"


def fmt_pct(value: float) -> str:
    return "n/a" if value is None or np.isnan(value) else f"{value:+.2%}"


def color_returns(val: str):
    """Green for '+', red for '-' (cells are pre-formatted strings; blank = no data)."""
    if not val:
        return ""
    return "color: #3ddc84" if val.startswith("+") else ("color: #ff5c5c" if val.startswith("-") else "")


def return_column_config(width: int = 64, fmt: str = "%+.2f%%", spark_width: int = 75) -> dict:
    """Column settings for the seven return columns + sparkline. Widths are pixels."""
    # Returns are pre-formatted text (see show_table), so plain text columns are used here.
    cfg = {k: st.column_config.TextColumn(v, width=width) for k, v in RET_LABELS.items()}
    cfg["spark"] = st.column_config.LineChartColumn("30d", width=spark_width)
    return cfg


def table_width(config: dict, columns: list[str]) -> int:
    """Sum of the configured pixel column widths, plus a little slack for borders."""
    total = 0
    for c in columns:
        w = (config.get(c) or {}).get("width")      # column_config objects are plain dicts
        total += int(w) if isinstance(w, (int, float)) else 90
    return total + 12


def show_table(df: pd.DataFrame, columns: list[str], config: dict, key: str) -> None:
    """Render a compact st.dataframe with coloured return cells."""
    view = df[columns].copy()
    ret_cols = [k for k in RET_LABELS if k in view.columns]
    for k in ret_cols:                       # fractions -> "+1.23%" text, blank when missing
        view[k] = ["" if pd.isna(v) else f"{v * 100:+.2f}%" for v in view[k]]
    styler = view.style.map(color_returns, subset=ret_cols)
    height = ROW_PX * len(view) + HEADER_PX + 3   # exact fit, no inner scrollbar
    # A fixed pixel width (not "stretch") keeps the grid correctly sized when the
    # fit-to-screen script scales the page.
    st.dataframe(styler, column_config=config, hide_index=True, width=table_width(config, columns),
                 height=height, row_height=ROW_PX, key=key)


# --------------------------------------------------------------------------- #
# Section 1 - Commodities
# --------------------------------------------------------------------------- #
st.subheader("Commodities")
comm = table[~table["is_company"]].reset_index(drop=True)


def fmt_comm_price(r) -> str:
    return "n/a" if np.isnan(r["last"]) else f"{r['last']:,.2f}"


def fmt_comm_time(r) -> str:
    if r["kind"] == "manual":
        as_of = r.get("as_of")
        as_of = "no date" if as_of is None or (isinstance(as_of, float) and np.isnan(as_of)) else as_of
        return f"as of {as_of}"
    return fmt_time(r["last_time"], r["last_date"])


if len(comm):
    comm["price_str"] = [fmt_comm_price(r) for _, r in comm.iterrows()]
    comm["time_str"] = [fmt_comm_time(r) for _, r in comm.iterrows()]
    comm["kind_str"] = comm["kind"].str.capitalize()
    COMM_COLS = ["name", "kind_str", "unit", "price_str", "time_str"] + list(RET_LABELS) + ["spark"]
    comm_config = {
        "name": st.column_config.TextColumn("Commodity", width=230),
        "kind_str": st.column_config.TextColumn("Kind", width=64,
                                                help="Futures = front-month contract; Proxy = listed fund/trust; "
                                                     "Manual = typed into universe.yaml"),
        "unit": st.column_config.TextColumn("Unit", width=72),
        "price_str": st.column_config.TextColumn("Price", width=86),
        "time_str": st.column_config.TextColumn("Time", width=92),
        **return_column_config(width=64, spark_width=70),
    }
    show_table(comm, COMM_COLS, comm_config, key="tbl_commodities")

# --------------------------------------------------------------------------- #
# Section 2 - Portfolio, one block per commodity group
# --------------------------------------------------------------------------- #
# Portfolio on the left (wide), summary on the right so everything fits on one screen.
left, right = st.columns([3, 2], gap="medium")
with left:
    st.subheader("Portfolio")
companies = table[table["is_company"]].copy()

group_order: list[str] = []                  # order of first appearance in universe.yaml
for c in CFG["companies"]:
    g = c.get("commodity", "Other")
    if g not in group_order:
        group_order.append(g)
STAGE_ORDER = ["Producer", "Developer"]      # anything else goes after these

companies["price_str"] = [fmt_price(v, c) for v, c in zip(companies["last"], companies["display_ccy"])]
companies["time_str"] = [fmt_time(t, d) for t, d in zip(companies["last_time"], companies["last_date"])]
companies["mcap_str"] = [fmt_mcap(v) for v in companies["mcap_usd"]]
companies["stage_rank"] = companies["stage"].map(lambda s: STAGE_ORDER.index(s) if s in STAGE_ORDER else 99)
companies["file_order"] = range(len(companies))

# Ticker and Exchange are hidden unless the sidebar switch is on.
MIN_MAIN_WIDTH = MIN_MAIN_WIDTH_BASE + 72 - (0 if show_ids else 64 + 72)
id_cols = ["ticker", "exchange"] if show_ids else []
TABLE_COLS = ["name"] + id_cols + ["stage", "price_str", "mcap_str", "time_str"] + list(RET_LABELS) + ["spark"]
company_config = {
    "name": st.column_config.TextColumn("Name", width=165),
    "ticker": st.column_config.TextColumn("Ticker", width=64),
    "exchange": st.column_config.TextColumn("Exchange", width=72),
    "stage": st.column_config.TextColumn("Stage", width=78),
    "price_str": st.column_config.TextColumn(f"Price ({'local' if base_currency == 'LOCAL' else base_currency})",
                                             width=95),
    "mcap_str": st.column_config.TextColumn("Mkt cap", width=86,
                                            help="Market cap in US dollars: shares outstanding x live price x FX."),
    "time_str": st.column_config.TextColumn("Time", width=72,
                                            help=f"Time of the last price ({SETTINGS['timezone']}). "
                                                 "ASX/TSX prices are delayed 15-20 min."),
    **return_column_config(width=64, spark_width=70),
}

with left:
    for g in group_order:
        block = companies[companies["commodity"] == g].sort_values(["stage_rank", "file_order"])
        if block.empty:
            continue
        # The group name is shown as the header of the first column instead of a separate
        # title line - it keeps the whole universe on one screen.
        cfg_g = {**company_config, "name": st.column_config.TextColumn(g, width=165)}
        show_table(block, TABLE_COLS, cfg_g, key=f"tbl_{g}")

# --------------------------------------------------------------------------- #
# Section 3 - Summary by group and by stage
# --------------------------------------------------------------------------- #
with right:
    st.subheader("Summary (equal-weighted averages)")
    summary = metrics.summary_table(table, group_order, STAGE_ORDER)
    summary["group"] = summary["group"] + " (" + summary["n"].astype(str) + ")"   # e.g. "Copper (2)"
    summary_config = {
        "group": st.column_config.TextColumn("Group (# names)", width=135),
        **return_column_config(width=62, spark_width=60),
    }
    show_table(summary, ["group"] + list(RET_LABELS) + ["spark"], summary_config, key="tbl_summary")

# --------------------------------------------------------------------------- #
# Footer
# --------------------------------------------------------------------------- #
st.markdown(
    "<div class='footer'>Source: Yahoo Finance. ASX/TSX quotes delayed 15–20 min; NYSE/NASDAQ near real-time. "
    "Futures are front-month continuous contracts.</div>",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Fit to one screen: scale the main area so its full height matches the window
# --------------------------------------------------------------------------- #
# Uses a CSS transform (not `zoom`): a transform scales only what you see, so Streamlit's
# own size measurements for the tables stay correct.
if fit_screen:
    components.html(
        f"""<script>
        const doc = window.parent.document;
        const MIN_WIDTH = {MIN_MAIN_WIDTH};
        function fit() {{
            const main = doc.querySelector('.block-container');
            if (!main) return;
            // 1. reset and measure the natural size
            main.style.transform = ''; main.style.width = ''; main.style.marginBottom = '';
            main.style.maxWidth = 'none'; main.style.marginLeft = '0'; main.style.marginRight = '0';
            main.style.alignSelf = 'flex-start';
            const rect = main.getBoundingClientRect();
            const availH = window.parent.innerHeight - rect.top - 6;
            const zW = rect.width / MIN_WIDTH;                     // keep tables wide enough for all columns
            let z = Math.min(availH / main.scrollHeight, zW);
            const hint = doc.getElementById('fit-hint');
            if (z < 0.98) {{
                // Shrinking with CSS breaks Streamlit's table sizing, so ask for browser zoom instead
                // (Ctrl and minus). Browser zoom is remembered per site, so this is a one-time step.
                const pct = Math.max(50, Math.round(z * 100 / 5) * 5);
                if (hint) hint.textContent = 'Tip: set browser zoom to about ' + pct + '% (Ctrl and −) to fit everything on one screen';
                return;
            }}
            if (hint) hint.textContent = '';
            z = Math.min(1.3, z);
            // lay out at the compensated width, re-measure height, refine once
            main.style.width = (rect.width / z).toFixed(0) + 'px';
            z = Math.min(1.3, Math.max(1, Math.min(availH / main.scrollHeight, zW)));
            main.style.width = (rect.width / z).toFixed(0) + 'px';
            const natural = main.scrollHeight;
            // scale visually and give back the layout space the scaling takes
            main.style.transformOrigin = 'top left';
            main.style.transform = 'scale(' + z.toFixed(3) + ')';
            main.style.marginBottom = (natural * (z - 1)).toFixed(0) + 'px';
        }}
        setTimeout(fit, 250); setTimeout(fit, 1200); setTimeout(fit, 3000);
        let t = null;
        window.parent.addEventListener('resize', () => {{ clearTimeout(t); t = setTimeout(fit, 150); }});
        </script>""",
        height=0,
    )
