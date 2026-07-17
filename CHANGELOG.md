# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.0.1] - 2026-07-17

First release as a packaged macOS app. (Entries below are from the earlier
run-from-source script era, which had its own 1.x numbering.)

### Changed
- Renamed ZerodhaBar → **KiteBar**; existing Keychain credentials, token and
  settings migrate automatically on first launch (Keychain service
  `kitebar`, `~/Library/Application Support/KiteBar`, bundle id
  `com.shameemshah.kitebar`).
- Restructured the single-file script into the `kitebar/` package
  (constants, formatting, market, portfolio, auth, migration, launch_agent,
  ui) with `python -m kitebar` as the entry point.
- Launch-at-login points at the app bundle when running from KiteBar.app.

### Added
- Native `KiteBar.app` (py2app, Apple Silicon only) — no Python needed.
- Distribution: dmg on GitHub Releases + Homebrew cask
  (`brew install --cask shameemshah/tap/kitebar`).
- Tag-triggered release workflow (build on an M-series runner, publish the
  release, bump the cask in `shameemshah/homebrew-tap`).

## [1.5.0] - 2026-07-09

### Added
- "Show" filter submenu (All / Equity / Mutual funds, persisted): limits
  the dropdown to the chosen side of the portfolio. The summary card
  follows the filter — combined equity+MF totals on All, one side only
  otherwise.

## [1.4.0] - 2026-07-09

### Added
- Mutual funds: a MUTUAL FUNDS section shows the Coin portfolio via
  `kite.mf_holdings()` (works on the free Personal plan) — units, avg
  NAV, invested, latest NAV, and P&L per fund (computed as
  `(nav - avg) × units`; the API's own `pnl` field is 0), plus the
  section-total P&L in the header. NAVs update once daily, so the
  endpoint is polled at most every 30 minutes.

## [1.3.0] - 2026-07-09

### Added
- "Auto-login on expiry" menu toggle (on by default, persisted in
  `settings.json`): when the daily token dies, the app opens the Kite
  login page itself; an existing kite.zerodha.com browser session
  completes the redirect with zero typing. Auto-login never re-fires
  after a failed attempt and is rate-limited to once per 10 minutes.

### Changed
- Summary card redesigned to match the Kite app: "Invested" and
  "Current" labels over their amounts, a hairline, then a P&L row with
  the amount and a rounded percentage pill (green/red). The ₹-symbol
  and "today" line are gone from the card (day P&L stays in the menu
  bar title).
- HOLDINGS and POSITIONS section headers are now clearly distinct: a
  full-width tinted band with the item count on the left and that
  section's total P&L on the right. The HOLDINGS header shows even when
  there are no positions.

## [1.2.0] - 2026-07-09

### Added
- Live-feel refresh: polling drops from 30 s to 5 s during market hours,
  and an open dropdown now updates in place (labels tick live via an
  `NSMenu` delegate tracking open/close) instead of freezing until the
  next rebuild. Re-sorting waits for the menu to close.

### Changed
- Holding and position rows redesigned to match the Kite app exactly:
  three lines — `Qty. • Avg.` with overall P&L % on top, symbol with
  overall P&L amount in the middle, `Invested` with `LTP (day %)` at the
  bottom — separated by hairlines, sorted alphabetically. The day-change
  pills are gone.
- Wake-from-sleep detection now uses a fixed 120 s tick gap (was tied to
  the poll interval).

## [1.1.0] - 2026-07-08

### Added
- Positions support: open and closed positions (`kite.positions()`, also a
  free-plan portfolio endpoint) render in their own dropdown section with
  product tag (MIS/NRML/CNC), signed quantity, LTP, a mark-to-market pill,
  and per-position P&L. Open positions sort first, by P&L.
- The menu bar title and summary card's "today" figure now include
  positions' M2M on top of holdings' day change — matching the Zerodha
  app's Day's P&L.

### Changed
- A positions fetch failure degrades gracefully (last known positions are
  kept); it never sinks the holdings refresh.

## [1.0.0] - 2026-07-08

### Added
- Menu bar title with total day P&L, colored green/red, Indian ₹ grouping.
- Native dropdown: portfolio summary card (current value, day move,
  invested, total P&L %) and two-line holding rows with day-change pills,
  built as custom `NSView` menu items that adapt to light/dark mode.
- Browser-based Kite login with a local `127.0.0.1:8000/callback` catcher;
  daily access token cached and reused until its ~6 AM IST expiry.
- Credentials stored in the macOS Keychain, with a first-run GUI prompt and
  a `--set-credentials` terminal fallback that validates key/secret lengths.
- Polling every 30 s during NSE market hours (IST-aware), a single fetch
  outside hours and on wake from sleep, quiet retries with a stale-data
  `⚠` indicator.
- "Launch at login" toggle via a user LaunchAgent.

### Fixed (during initial development)
- Holdings math now includes unsettled T1 shares (`quantity +
  t1_quantity`) — totals match the Zerodha app exactly.
- Credential dialogs get keyboard focus (app re-activates before showing
  them).
- Notification failures (missing `CFBundleIdentifier`) no longer crash the
  app; they fall back to a status row.
