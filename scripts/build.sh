#!/usr/bin/env bash
# Build dist/KiteBar.app and dist/KiteBar-<version>.dmg.
# Run inside a venv (or CI python) that can take pip installs.
# Set CODESIGN_IDENTITY to a Developer ID to really sign; default is ad-hoc.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import re; print(re.search(r'^__version__ = \"([^\"]+)\"', open('kitebar/__init__.py').read(), re.M).group(1))")
echo "Building KiteBar ${VERSION}"

rm -rf build dist
scripts/make-icns.sh

python3 -m pip install --quiet -r requirements.txt py2app setuptools
python3 setup.py py2app

APP=dist/KiteBar.app
codesign --force --deep --sign "${CODESIGN_IDENTITY:--}" "$APP"
codesign --verify --deep "$APP" && echo "Signature OK"

STAGING=$(mktemp -d)
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
DMG="dist/KiteBar-${VERSION}.dmg"
hdiutil create -volname "KiteBar" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
rm -rf "$STAGING"

echo "Built $DMG"
