#!/usr/bin/env python3
"""Local Midea air-conditioner bridge for House Control.

Talks to Midea ACs on the LAN with msmart-ng and serves them on 127.0.0.1 as small JSON, in the
panel's own vocabulary (on / mode / target / fan / swing / sleep / eco / roomTemp) plus the extras
the Midea app has (breeze, humidity, outdoor temperature, energy, display, turbo, ...).

  midea_bridge.py pair <ip> [<ip> ...]   one-time: fetch each unit's token/key (asks for YOUR Midea
                                         app login in the terminal; it is never stored)
  midea_bridge.py serve [--port 8765]    run the bridge

Config: ~/Library/Application Support/HouseControl/midea.json (tokens and keys, mode 0600).
"""
import argparse
import asyncio
import getpass
import json
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

CONFIG = Path.home() / "Library/Application Support/HouseControl/midea.json"
log = logging.getLogger("midea-bridge")

MODES = {"auto": "AUTO", "cool": "COOL", "dry": "DRY", "heat": "HEAT", "fan": "FAN_ONLY"}
FANS = {"auto": "AUTO", "low": "LOW", "medium": "MEDIUM", "high": "HIGH", "turbo": "MAX", "silent": "SILENT"}
SWINGS = {"off": "OFF", "vertical": "VERTICAL", "horizontal": "HORIZONTAL", "both": "BOTH"}


def load_config() -> list:
    if not CONFIG.exists():
        return []
    return json.loads(CONFIG.read_text())


def save_config(devices: list) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(devices, indent=2))
    CONFIG.chmod(0o600)


async def pair(hosts: list, account: str = "", password: str = "", cloud_name: str = "smarthome") -> None:
    """Finds each unit on the LAN, then fetches its V3 token/key from the Midea cloud account the
    phone app uses (SmartHome by default; NetHome Plus with --cloud nethome)."""
    from msmart.cloud import NetHomePlusCloud, SmartHomeCloud
    from msmart.discover import Discover
    from msmart.lan import Security

    account = account or os.environ.get("MIDEA_ACCOUNT") or input("Midea app account (email/phone): ").strip()
    password = password or os.environ.get("MIDEA_PASSWORD") or getpass.getpass("Midea app password (not stored): ")
    cloud_cls = SmartHomeCloud if cloud_name == "smarthome" else NetHomePlusCloud
    cloud = cloud_cls("US", account=account, password=password)
    await cloud.login()
    devices = {d["ip"]: d for d in load_config()}
    for host in hosts:
        found = await Discover.discover(target=host, auto_connect=False)
        dev = found[0] if found else None
        if dev is None:
            print(f"  {host}: no Midea device answered")
            continue
        token = key = None
        for endian in ("little", "big"):
            udpid = Security.udpid(dev.id.to_bytes(6, endian)).hex()
            try:
                token, key = await cloud.get_token(udpid, dev.id)
                await dev.authenticate(token, key)
                break
            except Exception as e:  # wrong endian or token: try the other one
                token = key = None
                err = e
        if not token:
            print(f"  {host}: could not get a token ({err})")
            continue
        devices[host] = {"id": str(dev.id), "ip": host, "port": dev.port, "name": dev.name or f"Midea {host}",
                         "token": token, "key": key}
        print(f"  {host}: paired {devices[host]['name']} (id {dev.id})")
    save_config(list(devices.values()))
    print(f"Saved to {CONFIG}")


# Everything the Midea app offers beyond mode / temperature / fan / swing, as one table the panel renders.
# key: patch/state key; attr: msmart-ng property; need: capability flag; kind: toggle | select | number.
EXTRAS = [
    {"key": "breeze", "label": "Breeze Away", "desc": "Airflow that avoids blowing directly on you", "kind": "select",
     "options": ["off", "away", "mild", "breezeless"]},
    {"key": "ieco", "label": "ECOMaster", "desc": "Improves efficiency while maintaining your comfort", "attr": "ieco", "need": "supports_ieco", "kind": "toggle"},
    {"key": "eco", "label": "ECO", "desc": "Energy-saving mode", "attr": "eco", "need": "supports_eco", "kind": "toggle"},
    {"key": "ecoEye", "label": "ECO Smart Eye", "desc": "Energy saving when you are away for 30 minutes", "attr": "eco_mode", "need": "supports_eco_mode", "kind": "toggle"},
    {"key": "sleep", "label": "Smart Sleep", "desc": "Dynamically adjusts the temperature while sleeping", "attr": "sleep", "kind": "toggle"},
    {"key": "flash", "label": "Flash", "desc": "Reach the set-point faster in cooling or heating", "attr": "flash_cool", "need": "supports_flash_cool", "kind": "toggle"},
    {"key": "turbo", "label": "Boost", "desc": "The fastest way to reach the desired temperature", "attr": "turbo", "need": "supports_turbo", "kind": "toggle"},
    {"key": "rate", "label": "Generator Mode", "desc": "Decrease power to save energy", "kind": "select",
     "options": ["off", "L1", "L2", "L3", "L4", "L5"]},
    {"key": "beep", "label": "Beep", "desc": "The AC beeps when it receives a command", "kind": "toggle", "local": True},
    {"key": "display", "label": "LED", "desc": "Turn the AC's LED display on or off", "attr": "display_on", "need": "supports_display_control", "kind": "toggle"},
    {"key": "silent", "label": "Silent", "desc": "Reduce the unit noise to keep quiet", "attr": "out_silent", "need": "supports_out_silent", "kind": "toggle"},
    {"key": "selfClean", "label": "Active Clean", "desc": "Clean the inside of the unit and prevent bacteria", "attr": "self_clean_active",
     "need": "supports_self_clean", "kind": "toggle", "action": True},
    {"key": "freeze", "label": "Freeze Protection", "desc": "Keep at least 8 °C for frost protection", "attr": "freeze_protection", "need": "supports_freeze_protection", "kind": "toggle"},
    {"key": "targetHumidity", "label": "Custom Dry", "desc": "Run dry mode to a target humidity", "attr": "target_humidity",
     "need": "supports_target_humidity", "kind": "number", "min": 30, "max": 85},
]
RATES = {"off": "OFF", "L1": "LEVEL_1", "L2": "LEVEL_2", "L3": "LEVEL_3", "L4": "LEVEL_4", "L5": "LEVEL_5"}


class Unit:
    def __init__(self, cfg: dict):
        from msmart.device import AirConditioner as AC

        self.cfg = cfg
        self.ac = AC(ip=cfg["ip"], device_id=int(cfg["id"]), port=int(cfg.get("port", 6444)))
        self.ready = False
        self.lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.cfg.get("token"):
            await self.ac.authenticate(self.cfg["token"], self.cfg["key"])
        await self.ac.get_capabilities()
        self.ready = True

    async def state(self) -> dict:
        async with self.lock:
            if not self.ready:
                await self.connect()
            await self.ac.refresh()
            return self.snapshot()

    def extras(self) -> list:
        a = self.ac
        out = []
        for e in EXTRAS:
            if e["key"] == "breeze":
                opts = ["off"] + [k for k, ok in (("away", a.supports_breeze_away), ("mild", a.supports_breeze_mild),
                                                    ("breezeless", a.supports_breezeless)) if ok]
                if len(opts) > 1: out.append({**e, "options": opts})
            elif e["key"] == "rate":
                names = {r.name for r in getattr(a, "supported_rate_selects", [])}
                opts = [k for k, v in RATES.items() if k == "off" or v in names]
                if len(opts) > 1: out.append({**e, "options": opts})
            elif e.get("need") is None or getattr(a, e["need"], False):
                out.append(e)
        return out

    def value(self, key: str):
        a = self.ac
        if key == "breeze":
            return ("away" if getattr(a, "breeze_away", False) else "mild" if getattr(a, "breeze_mild", False)
                    else "breezeless" if getattr(a, "breezeless", False) else "off")
        if key == "beep":
            return bool(self.cfg.get("beep", True))
        if key == "rate":
            r = getattr(a.rate_select, "name", "OFF")
            return next((k for k, v in RATES.items() if v == r), "off")
        e = next(x for x in EXTRAS if x["key"] == key)
        v = getattr(a, e["attr"], None)
        return v if e["kind"] == "number" else bool(v)

    @staticmethod
    def angle(v) -> int:
        """SwingAngle.POS_n -> n; OFF/unknown -> 0."""
        name = getattr(v, "name", "OFF")
        return int(name[4:]) if name.startswith("POS_") else 0

    def snapshot(self) -> dict:
        a = self.ac

        def name(v, table):
            return next((k for k, t in table.items() if getattr(v, "name", None) == t), None)

        extras = self.extras()
        feats = {
            "modes": [k for k, v in MODES.items() if v in {m.name for m in a.supported_operation_modes}],
            "fans": [k for k, v in FANS.items() if v in {f.name for f in a.supported_fan_speeds} and k != "silent"],
            "swing": len(a.supported_swing_modes) > 1, "sleep": True, "eco": False,  # eco lives in extras
            "airflow": {"vertical": "VERTICAL" in {m.name for m in a.supported_swing_modes},
                        "horizontal": "HORIZONTAL" in {m.name for m in a.supported_swing_modes},
                        "verticalAngles": bool(a.supports_vertical_swing_angle),
                        "horizontalAngles": bool(a.supports_horizontal_swing_angle)},
            "extras": extras,
        }
        ac = {
            "on": bool(a.power_state), "mode": name(a.operational_mode, MODES) or "auto",
            "target": a.target_temperature, "roomTemp": a.indoor_temperature,
            "fan": name(a.fan_speed, FANS) or "auto",
            "swing": "off" if getattr(a.swing_mode, "name", "OFF") == "OFF" else "swing",
            "swingMode": name(a.swing_mode, SWINGS) or "off",
            "swingV": getattr(a.swing_mode, "name", "OFF") in ("VERTICAL", "BOTH"),
            "swingH": getattr(a.swing_mode, "name", "OFF") in ("HORIZONTAL", "BOTH"),
            "angleV": self.angle(a.vertical_swing_angle), "angleH": self.angle(a.horizontal_swing_angle),
            "outdoorTemp": a.outdoor_temperature, "humidity": a.indoor_humidity,
            "power": a.real_time_power_usage or a.current_energy_usage, "totalEnergy": a.total_energy_usage,
            "filterAlert": bool(a.filter_alert), "error": a.error_code,
        }
        for e in extras:
            ac[e["key"]] = self.value(e["key"])
        return {"id": self.cfg["id"], "name": self.cfg["name"], "online": bool(a.online),
                "range": [a.min_target_temperature, a.max_target_temperature], "ac": ac, "features": feats}

    async def control(self, patch: dict) -> dict:
        async with self.lock:
            if not self.ready:
                await self.connect()
            a = self.ac
            if "beep" in patch:
                self.cfg["beep"] = bool(patch["beep"])
                devices = [self.cfg if d["id"] == self.cfg["id"] else d for d in load_config()]
                save_config(devices)
            a.beep = bool(self.cfg.get("beep", True))
            if "on" in patch: a.power_state = bool(patch["on"])
            if "mode" in patch: a.operational_mode = type(a.operational_mode)[MODES[patch["mode"]]]
            if "target" in patch: a.target_temperature = float(patch["target"])
            if "fan" in patch: a.fan_speed = type(a.fan_speed)[FANS[patch["fan"]]]
            if "swingV" in patch or "swingH" in patch:
                v = bool(patch.get("swingV", getattr(a.swing_mode, "name", "OFF") in ("VERTICAL", "BOTH")))
                h = bool(patch.get("swingH", getattr(a.swing_mode, "name", "OFF") in ("HORIZONTAL", "BOTH")))
                a.swing_mode = type(a.swing_mode)["BOTH" if v and h else "VERTICAL" if v else "HORIZONTAL" if h else "OFF"]
            for key, attr in (("angleV", "vertical_swing_angle"), ("angleH", "horizontal_swing_angle")):
                if key in patch:
                    n = int(patch[key])
                    if n >= 1:  # the unit has no "off" position: it keeps the last one when swing stops
                        setattr(a, attr, type(getattr(a, attr))[f"POS_{min(n, 5)}"])
            if ("swing" in patch or "swingMode" in patch) and "swingV" not in patch and "swingH" not in patch:
                sw = patch.get("swingMode") or ("both" if patch["swing"] != "off" else "off")
                a.swing_mode = type(a.swing_mode)[SWINGS[sw]]
            if "breeze" in patch:
                for key, attr in (("away", "breeze_away"), ("mild", "breeze_mild"), ("breezeless", "breezeless")):
                    if hasattr(a, attr): setattr(a, attr, patch["breeze"] == key)
            if "rate" in patch: a.rate_select = type(a.rate_select)[RATES[patch["rate"]]]
            clean = False
            for e in EXTRAS:
                k = e["key"]
                if k in patch and "attr" in e and not e.get("local"):
                    if e.get("action"): clean = bool(patch[k])
                    else: setattr(a, e["attr"], int(patch[k]) if e["kind"] == "number" else bool(patch[k]))
            await a.apply()
            if clean: await a.start_self_clean()
            return self.snapshot()


def make_app() -> web.Application:
    units = {}
    for cfg in load_config():
        units[str(cfg["id"])] = Unit(cfg)

    async def devices(_):
        return web.json_response([{"id": i, "name": u.cfg["name"], "ip": u.cfg["ip"]} for i, u in units.items()])

    async def state(request):
        u = units.get(request.match_info["id"])
        if not u: raise web.HTTPNotFound()
        try:
            return web.json_response(await u.state())
        except Exception as e:  # unreachable unit: report offline instead of failing the poll
            log.warning("state %s: %s", u.cfg["ip"], e)
            u.ready = False
            return web.json_response({"id": u.cfg["id"], "name": u.cfg["name"], "online": False})

    async def control(request):
        u = units.get(request.match_info["id"])
        if not u: raise web.HTTPNotFound()
        try:
            return web.json_response(await u.control(await request.json()))
        except Exception as e:
            u.ready = False
            return web.json_response({"error": str(e)}, status=502)

    app = web.Application()
    app.add_routes([web.get("/devices", devices), web.get("/state/{id}", state), web.post("/control/{id}", control)])
    return app


PLAN = Path.home() / "Library/Application Support/HouseControl/plan.json"
BRIDGE = "http://127.0.0.1:8765"


def http(method: str, path: str, body=None):
    import urllib.request
    req = urllib.request.Request(BRIDGE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def parse_value(v: str):
    if v.lower() in ("true", "on", "yes"): return True
    if v.lower() in ("false", "no"): return False
    try: return float(v) if "." in v else int(v)
    except ValueError: return v


def resolve(ref: str) -> str:
    """A unit by id, ip, or part of its name."""
    for d in http("GET", "/devices"):
        if ref in (d["id"], d["ip"]) or ref.lower() in d["name"].lower(): return d["id"]
    sys.exit(f"no paired unit matches '{ref}' (see: midea devices)")


def cli(args) -> None:
    if args.cmd == "devices":
        for d in http("GET", "/devices"): print(f'{d["id"]}  {d["ip"]:<15}  {d["name"]}')
    elif args.cmd == "state":
        print(json.dumps(http("GET", f"/state/{resolve(args.unit)}"), indent=2))
    elif args.cmd == "set":
        patch = {}
        for kv in args.pairs:
            k, _, v = kv.partition("=")
            patch[k] = "off" if v == "off" and k in ("breeze", "rate") else (False if v == "off" else parse_value(v))
        print(json.dumps(http("POST", f"/control/{resolve(args.unit)}", patch)["ac"], indent=2))
    elif args.cmd in ("link", "unlink"):
        plan = json.loads(PLAN.read_text())
        ac = next((a for a in plan["acs"] if args.ac in (a["id"], a["name"])), None)
        if not ac: sys.exit("AC not in plan: " + ", ".join(a["id"] for a in plan["acs"]))
        if args.cmd == "link": ac["link"] = {"service": "midea", "id": resolve(args.unit)}
        else: ac.pop("link", None)
        PLAN.write_text(json.dumps(plan, indent=2))
        print(f'{ac["id"]}: {ac.get("link") or "unlinked"} (restart House Control to apply)')
    elif args.cmd == "plan":
        print(PLAN.read_text())


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("pair"); pp.add_argument("hosts", nargs="+")
    pp.add_argument("--account", default=""); pp.add_argument("--password", default="")
    pp.add_argument("--cloud", choices=["smarthome", "nethome"], default="smarthome", help="which Midea app your account is from")
    sp = sub.add_parser("serve"); sp.add_argument("--port", type=int, default=8765)
    sub.add_parser("devices"); sub.add_parser("plan")
    st = sub.add_parser("state"); st.add_argument("unit")
    se = sub.add_parser("set"); se.add_argument("unit"); se.add_argument("pairs", nargs="+", help="key=value, e.g. on=true target=26 mode=cool breeze=away rate=L2")
    lk = sub.add_parser("link"); lk.add_argument("ac", help="AC id in plan.json"); lk.add_argument("unit")
    ul = sub.add_parser("unlink"); ul.add_argument("ac")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.cmd == "pair":
        asyncio.run(pair(args.hosts, args.account, args.password, args.cloud))
    elif args.cmd != "serve":
        cli(args)
    else:
        web.run_app(make_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
