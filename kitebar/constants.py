"""Paths, identifiers, timings, and tunables."""

import os
from datetime import time as dtime
from zoneinfo import ZoneInfo

APP_NAME = "KiteBar"
BUNDLE_ID = "com.shameemshah.kitebar"
KEYRING_SERVICE = "kitebar"                  # Keychain service name
IST = ZoneInfo("Asia/Kolkata")

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8000
CALLBACK_PATH = "/callback"
LOGIN_WAIT_SECONDS = 300                     # how long the local server waits

POLL_SECONDS = 5                             # market-hours refresh cadence
WAKE_GAP_SECONDS = 120                       # tick gap that means "slept"
MF_REFRESH_SECONDS = 1800                    # MF NAVs move once a day
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
TOKEN_EXPIRY_HOUR = 6                        # tokens die ~6 AM IST daily

def _resources_dir():
    """py2app sets RESOURCEPATH to KiteBar.app/Contents/Resources."""
    rp = os.environ.get("RESOURCEPATH")
    if rp:
        return os.path.join(rp, "assets")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _bundle_path():
    """Path to KiteBar.app when running frozen (py2app), else None."""
    rp = os.environ.get("RESOURCEPATH")
    if not rp:
        return None
    return os.path.dirname(os.path.dirname(rp))


ASSETS_DIR = _resources_dir()
MENUBAR_ICON = os.path.join(ASSETS_DIR, "menubar.png")
APP_ICON = os.path.join(ASSETS_DIR, "appicon-256.png")

APP_SUPPORT = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
TOKEN_FILE = os.path.join(APP_SUPPORT, "access_token.json")
SETTINGS_FILE = os.path.join(APP_SUPPORT, "settings.json")

AUTO_LOGIN_COOLDOWN = 600     # never auto-open the browser more than 1/10 min

LAUNCH_AGENT_LABEL = BUNDLE_ID
LAUNCH_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist"
)

# Pre-rename (ZerodhaBar) names — read once at startup for migration.
OLD_KEYRING_SERVICE = "zerodha-menubar"
OLD_APP_SUPPORT = os.path.expanduser("~/Library/Application Support/ZerodhaBar")
OLD_LAUNCH_AGENT_LABEL = "com.zerodha.menubar"
OLD_LAUNCH_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{OLD_LAUNCH_AGENT_LABEL}.plist"
)

FAILURES_BEFORE_WARNING = 3

PRIVATE_MASK = "••••••"           # replaces rupee amounts in private mode
