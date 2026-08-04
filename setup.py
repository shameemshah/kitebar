"""py2app build config: python3 setup.py py2app  ->  dist/KiteBar.app"""
import re

from setuptools import setup

with open("kitebar/__init__.py") as fh:
    VERSION = re.search(r'^__version__ = "([^"]+)"', fh.read(), re.M).group(1)

OPTIONS = {
    "iconfile": "build/KiteBar.icns",
    "resources": ["assets"],
    # cffi/_cffi_backend (cryptography) and charset_normalizer (requests)
    # are runtime imports py2app's scanner misses. certifi must ship as a
    # real directory: zipped, its cacert.pem gets extracted to $TMPDIR,
    # which macOS purges after ~3 days and every HTTPS call then fails.
    "packages": [
        "kitebar",
        "rumps",
        "kiteconnect",
        "keyring",
        "cffi",
        "charset_normalizer",
        "certifi",
    ],
    "includes": ["_cffi_backend"],
    "plist": {
        "CFBundleName": "KiteBar",
        "CFBundleDisplayName": "KiteBar",
        "CFBundleIdentifier": "com.shameemshah.kitebar",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,
        "LSMinimumSystemVersion": "11.0",
        "LSArchitecturePriority": ["arm64"],
        "NSHumanReadableCopyright": "MIT License — not affiliated with Zerodha",
    },
}

setup(
    name="KiteBar",
    version=VERSION,
    app=["main.py"],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
