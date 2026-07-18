"""Number/text formatting helpers."""

def fmt_inr(value, decimals=0, explicit_sign=False, rupee=True):
    """Indian digit grouping: 1234567.8 -> ₹12,34,568 (or bare with rupee=False)."""
    negative = value < 0
    text = f"{abs(value):.{decimals}f}"
    int_part, _, frac = text.partition(".")
    if len(int_part) > 3:
        head, last3 = int_part[:-3], int_part[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        int_part = ",".join(groups + [last3])
    sign = "-" if negative else ("+" if explicit_sign else "")
    symbol = "₹" if rupee else ""
    return f"{sign}{symbol}{int_part}" + (f".{frac}" if frac else "")
