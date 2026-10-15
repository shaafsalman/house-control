#!/usr/bin/env bash
# Installs the Midea bridge: a private venv and a LaunchAgent that keeps it running on 127.0.0.1:8765.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Library/Application Support/HouseControl"
PLIST="$HOME/Library/LaunchAgents/com.housecontrol.midea-bridge.plist"
PY="$(ls /opt/homebrew/bin/python3.1[2-9] 2>/dev/null | tail -1 || true)"; PY="${PY:-python3}"
mkdir -p "$APP"
"$PY" -m venv "$APP/midea-venv"
"$APP/midea-venv/bin/pip" -q install -r "$HERE/requirements.txt"
cp "$HERE/midea_bridge.py" "$APP/midea_bridge.py"
cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.housecontrol.midea-bridge</string>
  <key>ProgramArguments</key><array>
    <string>$APP/midea-venv/bin/python</string><string>$APP/midea_bridge.py</string><string>serve</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$APP/midea-bridge.log</string>
</dict></plist>
P
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/midea" <<W
#!/bin/sh
exec "$APP/midea-venv/bin/python" "$APP/midea_bridge.py" "\$@"
W
chmod +x "$HOME/.local/bin/midea"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Bridge installed. Pair your units once with:"
echo "  \"$APP/midea-venv/bin/python\" \"$APP/midea_bridge.py\" pair <ip> [<ip> ...]"
echo "then: launchctl kickstart -k gui/\$(id -u)/com.housecontrol.midea-bridge"
