# Coverage Dashboard - notes for future sessions

Streamlit dashboard for a small mining/commodity coverage list, priced from Yahoo Finance.
The owner is not a developer: keep code commented, keep the README non-technical.

## File roles
- `universe.yaml`  - THE config. Companies, commodities, FX pairs, settings. All customisation
                     lives here; adding/removing names or groups must never need a code change.
- `data.py`        - all Yahoo (yfinance) calls. `fetch_history` (one batch, cached 6 h) and
                     `fetch_quotes` (two batched calls per refresh: 5d daily for price/prev close,
                     1d 1-minute for the last-trade timestamp shown in the Time column).
                     `fetch_shares` (one fast_info call per company, cached 6 h) feeds market cap. Failures -> NaN + warning
                     list, never exceptions. Prints "[data] HISTORY DOWNLOAD" when history is fetched.
- `metrics.py`     - pure pandas: FX conversion, calendar-based returns, sparklines, group/stage
                     equal-weighted averages. No Streamlit, no network.
- `app.py`         - UI only. Two views switched by a segmented control (`view`): Overview (tables) and
                     Graph (Plotly, multi-asset, rebased to 100). st.tabs is avoided on purpose: it resets
                     to the first tab on every auto-refresh rerun. Auto-refresh is paused on Graph. Sidebar (currency, return type, auto-refresh, refresh-now, failed
                     symbols), commodity cards, per-group tables, summary table, footer.
- `editor.py`      - Edit view persistence: writes universe.yaml (one-line-per-name layout) and pushes it
                     to GitHub via the Contents API when `st.secrets["github"]["token"]` exists. Needed because
                     Streamlit Cloud's disk is ephemeral. Secrets template: .streamlit/secrets.toml.example.
- Edit view (app.py) uses streamlit-sortables for drag-reorder (groups, companies across groups, columns)
  and st.data_editor for add/remove/correct rows. Draft lives in st.session_state["draft"] until Save.
  settings.columns (list) drives the visible company-table columns and their order.
- `check_universe.py` - CLI symbol validator (`python check_universe.py`).
- `.streamlit/config.toml` - dark theme; `layout="wide"` is set in app.py.

## Rules
- Do not hard-code tickers, group names or stages anywhere in Python.
- Commodities are never FX-converted; companies are converted before returns are computed.
- "Refresh now" must clear only `fetch_quotes` (not history).
- Yahoo rate limits are the main operational risk: keep one history download per 6 h and one
  quote batch per `refresh_seconds`; never loop one HTTP call per ticker in the app path.
- Layout: fit-to-screen only scales UP (CSS transform). Scaling down breaks Streamlit's table
  sizing (it clamps tables to the on-screen container width), so small screens get a browser-zoom hint.
- Known data gap: UX=F has ~1 row of history on Yahoo, so its returns are n/a by design.

## Environment
- Developed/tested on Python 3.13, pandas 3.0, yfinance 1.7, streamlit 1.63 (spec: Python 3.11+).
- `.claude/launch.json` starts the dev server for the in-app browser preview.
