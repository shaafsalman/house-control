#!/usr/bin/env bash
# Runs after `midea pair`: waits for both units, restarts the bridge, links the AC that is on at 26 C
# to "Shaaf's Room" and the other to "Room 2", then relaunches House Control.
set -u
M="$HOME/.local/bin/midea"
CFG="$HOME/Library/Application Support/HouseControl/midea.json"
echo "Waiting for pairing (both units in $CFG)..."
until [ -f "$CFG" ] && [ "$(python3 -c "import json;print(len(json.load(open('$CFG'))))")" -ge 2 ]; do sleep 3; done
launchctl kickstart -k "gui/$(id -u)/com.housecontrol.midea-bridge"; sleep 4
"$M" devices
python3 - <<'P'
import json, subprocess, os
m = os.path.expanduser("~/.local/bin/midea")
units = [l.split()[0] for l in subprocess.check_output([m, "devices"], text=True).splitlines() if l.strip()]
info = {}
for u in units:
    st = json.loads(subprocess.check_output([m, "state", u], text=True))
    ac = st.get("ac", {})
    info[u] = ac
    print(u, "on" if ac.get("on") else "off", "target", ac.get("target"), "room", ac.get("roomTemp"))
pick = next((u for u, a in info.items() if a.get("on") and a.get("target") == 26), None) or next((u for u, a in info.items() if a.get("on")), units[0])
other = next(u for u in units if u != pick)
for ac, u in (("shaaf.ac", pick), ("room2.ac", other)):
    subprocess.check_call([m, "link", ac, u])
P
pkill -x HouseControl; sleep 1; open "$(cd "$(dirname "$0")/../.." && pwd)/build/HouseControl.app"
echo "Done: Shaaf's Room is linked to the unit that is on at 26 C."
