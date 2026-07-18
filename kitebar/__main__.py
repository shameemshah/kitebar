"""Entry point: `python -m kitebar` (also used by the app bundle)."""

import sys

import keyring

from .constants import KEYRING_SERVICE


def set_credentials_cli():
    """Terminal fallback for entering credentials: --set-credentials."""
    api_key = input("Kite API Key (visible so you can check it): ").strip()
    api_secret = input("Kite API Secret (visible so you can check it): ").strip()
    if not api_key or not api_secret:
        print("Both values are required; nothing saved.")
        sys.exit(1)
    # Kite keys/secrets have fixed lengths; a mismatch means a bad paste and
    # guarantees "Invalid checksum" at login.
    if len(api_key) != 16:
        print(f"WARNING: API keys are 16 chars; you entered {len(api_key)}.")
    if len(api_secret) != 32:
        print(f"WARNING: API secrets are 32 chars; you entered "
              f"{len(api_secret)}. Check for extra/missing characters.")
    keyring.set_password(KEYRING_SERVICE, "api_key", api_key)
    keyring.set_password(KEYRING_SERVICE, "api_secret", api_secret)
    print("Saved to the macOS Keychain (service: %s)." % KEYRING_SERVICE)



def main():
    if "--set-credentials" in sys.argv:
        set_credentials_cli()
    else:
        from .migration import migrate_from_zerodhabar
        from .ui.app import KiteBarApp
        migrate_from_zerodhabar()
        KiteBarApp().run()


if __name__ == "__main__":
    main()
