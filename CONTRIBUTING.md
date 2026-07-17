# Contributing

Thanks for your interest! This is a small project — keep changes focused
and it stays that way.

## Dev setup

```sh
git clone https://github.com/shameemshah/kitebar.git
cd kitebar
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string "com.shameemshah.kitebar"' .venv/bin/Info.plist
.venv/bin/python -m kitebar
```

You need a Zerodha account and a free Kite Connect app (redirect URL
`http://127.0.0.1:8000/callback`) to test the live flow — but most changes
can be tested headlessly without one, see below.

## Code layout

```
kitebar/
├── __init__.py       __version__ — the single version source for releases
├── __main__.py       python -m kitebar entry, --set-credentials CLI
├── constants.py      paths, identifiers, timings, tunables
├── formatting.py     ₹ formatting (Indian digit grouping)
├── market.py         IST clock, NSE market-hours helpers
├── portfolio.py      math on raw Kite holdings/positions dicts
├── auth.py           token expiry, login callback server, result page
├── migration.py      one-time ZerodhaBar → KiteBar data migration
├── launch_agent.py   launch-at-login LaunchAgent
└── ui/
    ├── app.py        KiteBarApp — the rumps status-bar application
    ├── cocoa.py      main-thread dispatch, activation, menu-state delegate
    └── theme.py      shared colors
main.py               py2app entry point (the .app runs this)
```

Put new code in the module whose one-line description covers it; if none
fits, propose a new module in the PR rather than growing `ui/app.py`.

## Headless testing

The modules import cleanly without starting the Cocoa run loop, so pure
logic and menu construction are testable from a script:

```sh
.venv/bin/python - <<'EOF'
from kitebar.formatting import fmt_inr
from kitebar.portfolio import eff_qty
from kitebar.ui.app import KiteBarApp

# pure helpers
assert fmt_inr(1234567.8) == "₹12,34,568"
assert eff_qty({"quantity": 100, "t1_quantity": 50}) == 150

# full render path with fake holdings — no API, no login needed
app = KiteBarApp()
app._apply_holdings([{
    "tradingsymbol": "TCS", "quantity": 10, "t1_quantity": 0,
    "average_price": 3500.0, "last_price": 3600.0, "close_price": 3550.0,
    "pnl": 1000.0, "day_change": 50.0, "day_change_percentage": 1.41,
}])
print(app.title)                    # ▲ +₹1,000 (+1.4%)
assert app.menu["TCS"]._menuitem.view() is not None
EOF
```

Please run this kind of check (plus a real launch if you touched auth or
polling) before opening a PR, and say in the PR what you verified. CI runs
a lint (`ruff check --select E9,F`) and an import smoke test on every PR;
both must pass before merge.

## Ground rules

- **Read-only, always.** No PR that places, modifies, or cancels orders
  will be merged, ever.
- **Personal-plan compatible.** Only the portfolio endpoints
  (`kite.holdings()`, `kite.positions()`, `kite.mf_holdings()`) —
  LTP/quote/OHLC/WebSocket endpoints are blocked on the free plan.
- **No new secrets on disk.** Credentials belong in the Keychain; the only
  cached artifact is the day's access token (mode 0600).
- **All changes via pull request.** `main` is protected — direct pushes are
  blocked and the `ci` check must pass.
- Follow the existing style: PEP 8-ish, comments explain *constraints*,
  AppKit calls wrapped in `try/except` with a plain-text fallback.

## Good first issues

- NSE holiday calendar (skip polling on exchange holidays)
- Configurable poll interval and menu width
- Localized number formats (the ₹ lakh/crore grouping is hardcoded)
- Intel/universal2 builds (currently Apple Silicon only)

## Reporting bugs

Open a GitHub issue with macOS version, install method, what you clicked,
and terminal output. Never include your API key, secret, request token, or
access token in an issue.
