"""One-time silent migration from the old ZerodhaBar names."""

import os
import shutil
import subprocess

import keyring

from .constants import (
    APP_SUPPORT,
    KEYRING_SERVICE,
    OLD_APP_SUPPORT,
    OLD_KEYRING_SERVICE,
    OLD_LAUNCH_AGENT_LABEL,
    OLD_LAUNCH_AGENT_PLIST,
    TOKEN_FILE,
)

def migrate_from_zerodhabar():
    """One-time silent migration from the old ZerodhaBar names.

    Each stage is independent and idempotent; failures never block startup —
    the app just behaves like a fresh install.
    """
    try:  # Keychain: copy forward, never delete the old entries
        for key in ("api_key", "api_secret"):
            if not keyring.get_password(KEYRING_SERVICE, key):
                old = keyring.get_password(OLD_KEYRING_SERVICE, key)
                if old:
                    keyring.set_password(KEYRING_SERVICE, key, old)
    except Exception:  # noqa: BLE001
        pass
    try:  # token + settings files
        if not os.path.isdir(APP_SUPPORT) and os.path.isdir(OLD_APP_SUPPORT):
            os.makedirs(APP_SUPPORT, exist_ok=True)
            for name in ("access_token.json", "settings.json"):
                src = os.path.join(OLD_APP_SUPPORT, name)
                dst = os.path.join(APP_SUPPORT, name)
                if os.path.exists(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
            if os.path.exists(TOKEN_FILE):
                os.chmod(TOKEN_FILE, 0o600)
    except Exception:  # noqa: BLE001
        pass
    try:  # old LaunchAgent: remove so two copies never autostart
        if os.path.exists(OLD_LAUNCH_AGENT_PLIST):
            subprocess.run(
                ["launchctl", "bootout",
                 f"gui/{os.getuid()}/{OLD_LAUNCH_AGENT_LABEL}"],
                capture_output=True, check=False)
            os.remove(OLD_LAUNCH_AGENT_PLIST)
    except Exception:  # noqa: BLE001
        pass
