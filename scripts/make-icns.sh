#!/usr/bin/env bash
# Generate build/KiteBar.icns from assets/appicon-512.png (sips + iconutil).
set -euo pipefail
cd "$(dirname "$0")/.."

SRC=assets/appicon-512.png
SET=build/KiteBar.iconset
mkdir -p "$SET"

for sz in 16 32 128 256 512; do
  sips -z "$sz" "$sz" "$SRC" --out "$SET/icon_${sz}x${sz}.png" >/dev/null
done
for sz in 16 32 128 256; do
  dbl=$((sz * 2))
  sips -z "$dbl" "$dbl" "$SRC" --out "$SET/icon_${sz}x${sz}@2x.png" >/dev/null
done

iconutil -c icns "$SET" -o build/KiteBar.icns
rm -rf "$SET"
echo "Wrote build/KiteBar.icns"
