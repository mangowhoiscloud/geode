#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="${1:-"$ROOT/.geode/ComputerUseHelper/GEODE Computer Use Helper.app"}"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
BIN="$MACOS/geode-computer-helper"

mkdir -p "$MACOS"

cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleDisplayName</key>
  <string>GEODE Computer Use Helper</string>
  <key>CFBundleExecutable</key>
  <string>geode-computer-helper</string>
  <key>CFBundleIdentifier</key>
  <string>ai.geode.computer-use-helper</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>GEODE Computer Use Helper</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSBackgroundOnly</key>
  <true/>
  <key>NSAppleEventsUsageDescription</key>
  <string>GEODE uses app automation only when a computer-use task requires it.</string>
  <key>NSAppleScriptEnabled</key>
  <false/>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

swiftc \
  "$ROOT/scripts/macos/geode_computer_helper.swift" \
  -o "$BIN" \
  -framework AppKit \
  -framework ApplicationServices \
  -framework CoreGraphics

codesign --force --sign - "$APP_DIR" >/dev/null 2>&1 || true
echo "$BIN"
