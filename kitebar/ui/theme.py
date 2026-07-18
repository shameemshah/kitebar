"""Colors shared by the menu views."""

RED_SOFTEN = 0.35   # 0 = full systemRed, 1 = white; higher = gentler red


def soft_red():
    """systemRed blended toward white — less aggressive than the default."""
    from AppKit import NSColor
    return NSColor.systemRedColor().blendedColorWithFraction_ofColor_(
        RED_SOFTEN, NSColor.whiteColor())
