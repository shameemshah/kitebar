"""Portfolio math on raw Kite holdings/positions dicts."""

def eff_qty(holding):
    """Total shares held: settled demat quantity plus unsettled T1 shares.

    Kite's `quantity` excludes shares bought in the last trading session
    (still in T1); ignoring them understates invested/current/P&L.
    """
    return (holding.get("quantity") or 0) + (holding.get("t1_quantity") or 0)


def position_state(p):
    """Kite-style position badge state.

    CNC buys settle into holdings tomorrow ("HOLDING"); CNC sells of stock
    already held are realized exits ("SOLD HOLDING" — Kite dims these);
    qty 0 is a closed intraday round-trip; anything else is a plain open
    position.
    """
    qty = p.get("quantity") or 0
    if qty == 0:
        return "closed"
    if str(p.get("product", "")) == "CNC":
        return "holding" if qty > 0 else "sold"
    return "open"
