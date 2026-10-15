#!/usr/bin/env bash
# Keeps House Control running: copies the built app to ~/Applications and installs a LaunchAgent that
# starts it at login and restarts it if it crashes (a normal Quit from its menu stays quit until next login).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/build/HouseControl.app"
DEST="$HOME/Applications/HouseControl.app"
PLIST="$HOME/Library/LaunchAgents/com.housecontrol.app.plist"
LABEL="com.housecontrol.app"
[ -d "$SRC" ] || { echo "Build first: SKIP_WIDGETS=1 $ROOT/scripts/build-app.sh"; exit 1; }
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
pkill -x HouseControl 2>/dev/null || true; sleep 1
mkdir -p "$HOME/Applications" "$HOME/Library/Logs"
rm -rf "$DEST"; cp -R "$SRC" "$DEST"
cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$DEST/Contents/MacOS/HouseControl</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/HouseControl.log</string>
</dict></plist>
P
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "House Control will now start at login and restart if it crashes."
echo "Update after a rebuild:  $ROOT/tools/install-autostart.sh"
echo "Stop for good:           launchctl bootout gui/\$(id -u)/$LABEL"
