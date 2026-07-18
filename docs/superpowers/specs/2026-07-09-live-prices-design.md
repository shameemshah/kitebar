# Live-feel prices via fast holdings polling

**Date:** 2026-07-09
**Status:** Approved

## Problem

The menu bar app polls `kite.holdings()` every 30 s, so prices lag the
Zerodha app (which streams WebSocket ticks). The user's free Kite Connect
"Personal" plan blocks LTP/quote/WebSocket endpoints, so the holdings and
positions endpoints are the only permitted price source.

## Approach (chosen over Yahoo-quotes overlay and a hybrid)

Poll faster and update the open menu in place. Stays 100% on official,
plan-permitted endpoints.

## Design

1. **Poll every 5 s during market hours** (was 30 s). Off-hours behaviour
   unchanged: one fetch after close, on wake, or when data is stale.
   0.4 req/s across holdings+positions is far below Kite rate limits.
2. **In-place menu updates.** `_rebuild_menu()` (clear + re-add) glitches
   an open dropdown, so at 5 s cadence:
   - While building rows, keep references to each row's LTP label, P&L
     label, day pill, and the summary card labels.
   - Track menu open/closed with an `NSMenu` delegate
     (`menuWillOpen:`/`menuDidClose:`).
   - When data arrives while the menu is open: update label strings,
     colors, and pills in place, keep row order stable, and update the
     "Updated hh:mm:ss" status row. Full rebuild (re-sort, pill column
     re-layout) is deferred to menu close.
   - When the menu is closed: rebuild as before.
3. **Wake detection** switches from `POLL_SECONDS * 4` to a fixed 120 s
   gap, since the tick interval is now 5 s.

## Error handling

Unchanged: failures keep last good data, stale `⚠` marker after 3
consecutive failures, token-expiry path untouched.

## Testing

Run during market hours with the menu open: LTP/P&L/timestamp must change
every ~5 s without the menu closing or flickering. Off-hours: no polling
churn.

## Addendum (same day): Kite-exact row layout

Mid-implementation the user asked for rows identical to the Kite app's
holdings screen. Each holding/position renders as three lines:

    Qty. 595  •  Avg. 301.67                        +34.85%
    BEL                                          +62,548.35
    Invested 1,79,497.65                LTP 406.80 (-0.21%)

- Overall P&L % (top right) and overall P&L amount (middle right) are
  green/red; day-change % sits in parens after the LTP.
- Numbers use Indian grouping without the ₹ symbol, 2 decimals.
- Holdings sort alphabetically (Kite's order); hairline separators
  between rows; the day-change pills are removed.
- Positions mirror the same layout (M2M "today" top right, product tag
  bottom left).

## Known limitation

Zerodha serves holdings prices from a server-side cache that is not
tick-by-tick; updates arrive every 5 s but may trail Kite's streamed
prices slightly. This is the freshest possible on the Personal plan.
