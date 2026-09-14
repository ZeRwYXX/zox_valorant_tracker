from __future__ import annotations

import base64
import json
from pathlib import Path
import threading

from agents import resolve_agent
from riot_client import LocalAuth
from vconstants import map_name_from_path

PRESET_PATH = Path(__file__).resolve().parent / "data" / "instalock_preset.json"

def _self_session_state(presences: list, puuid: str) -> str | None:
    pass
    for p in presences or []:
        if p.get("puuid") != puuid:
            continue
        priv = p.get("private")
        if not priv or "{" in str(priv):
            return None
        try:
            data = json.loads(base64.b64decode(str(priv)).decode("utf-8"))
        except Exception:
            return None
        if "matchPresenceData" in data:
            return data["matchPresenceData"].get("sessionLoopState")
        return data.get("sessionLoopState")
    return None

def _side_from_match(match: dict, puuid: str) -> str | None:
    ally = (match or {}).get("AllyTeam") or {}
    team = ally.get("TeamID")
    return {"Red": "Attacker", "Blue": "Defender"}.get(team)

class InstalockWorker:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.state = {"running": False, "status": "idle", "message": "",
                      "agent": None, "mode": "lock", "side": None, "map": None,
                      "loop": True, "delay": 2, "region": None, "perMap": {}}
        self.preset = self._load_preset()

    @staticmethod
    def _load_preset() -> dict:
        try:
            data = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_preset(self, preset: dict) -> None:
        PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
        PRESET_PATH.write_text(json.dumps(preset, indent=2), encoding="utf-8")
        self.preset = preset

    def status(self) -> dict:
        return dict(self.state)

    @staticmethod
    def _normalize_per_map(per_map: dict | None) -> dict:
        pass
        out: dict[str, dict[str, str]] = {}
        for k, v in (per_map or {}).items():
            if not k or not v:
                continue
            if isinstance(v, dict):
                agent = str(v.get("agent") or "").strip()
                selected_mode = str(v.get("mode") or "lock").strip().lower()
            else:
                agent = str(v).strip()
                selected_mode = "lock"
            if agent:
                out[str(k).strip().lower()] = {
                    "agent": agent,
                    "mode": selected_mode if selected_mode in ("lock", "hover") else "lock",
                }
        return out

    def start(self, agent_id: str, mode: str = "lock", delay: float = 0.0,
              region: str | None = None, per_map: dict | None = None,
              loop: bool = True) -> dict:
        agent = resolve_agent(agent_id)
        if not agent:
            return {"ok": False, "message": f"Unknown agent '{agent_id}'."}
        saved = self.save_preset(agent_id, mode, delay, region, per_map, loop)
        if not saved["ok"]:
            return saved
        preset = saved["preset"]
        per_map_norm = preset["perMap"]

        for mapn, config in per_map_norm.items():
            if not resolve_agent(config["agent"]):
                return {"ok": False,
                        "message": f"Unknown agent '{config['agent']}' for map '{mapn}'."}
        preset = {
            "agent": agent["name"],
            "mode": mode if mode in ("lock", "hover") else "lock",
            "delay": max(0, float(delay or 0)),
            "region": region,
            "loop": bool(loop),
            "perMap": per_map_norm,
        }
        self._save_preset(preset)
        self.stop()
        with self._lock:
            self._stop.clear()
            self.state.update(running=True, status="waiting", agent=agent["name"],
                              mode=preset["mode"], side=None, map=None,
                              loop=preset["loop"], delay=preset["delay"],
                              region=region, perMap=per_map_norm,
                              message="Armed — waiting for agent select…")
            self._thread = threading.Thread(
                target=self._loop,
                args=(agent, preset["mode"], preset["delay"], region, per_map_norm, preset["loop"]),
                daemon=True)
            self._thread.start()
        return {"ok": True, "running": True, "agent": agent["name"],
                "status": "waiting", "perMap": per_map_norm,
                "loop": preset["loop"], "delay": preset["delay"]}

    def save_preset(self, agent_id: str, mode: str = "lock", delay: float = 2,
                    region: str | None = None, per_map: dict | None = None,
                    loop: bool = True) -> dict:
        agent = resolve_agent(agent_id)
        if not agent:
            return {"ok": False, "message": f"Unknown agent '{agent_id}'."}
        per_map_norm = self._normalize_per_map(per_map)
        for mapn, config in per_map_norm.items():
            if not resolve_agent(config["agent"]):
                return {"ok": False,
                        "message": f"Unknown agent '{config['agent']}' for map '{mapn}'."}
        preset = {
            "agent": agent["name"],
            "mode": mode if mode in ("lock", "hover") else "lock",
            "delay": max(0, float(delay or 0)),
            "region": region,
            "loop": bool(loop),
            "perMap": per_map_norm,
        }
        self._save_preset(preset)
        return {"ok": True, "preset": preset}

    def stop(self) -> dict:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.5)
        if self.state.get("status") in ("waiting", "running"):
            self.state.update(status="stopped", message="Stopped.")
        self.state.update(running=False)
        return {"ok": True, "running": False}

    def _loop(self, agent: dict, mode: str, delay: float, region, per_map: dict, loop: bool):
        done: set[str] = set()
        auth = None

        while not self._stop.is_set():
            try:
                if auth is None:
                    auth = LocalAuth(region)
                    auth.headers()
                pg = auth.glz_get(f"/pregame/v1/players/{auth.puuid}")
                mid = pg.get("MatchID") if isinstance(pg, dict) else None
                if mid and mid not in done:
                    if delay > 0 and self._stop.wait(delay):
                        break
                    match = auth.glz_get(f"/pregame/v1/matches/{mid}")
                    side = _side_from_match(match, auth.puuid)
                    map_name = map_name_from_path((match or {}).get("MapID", ""))

                    chosen = agent
                    selected_mode = mode
                    override = per_map.get((map_name or "").lower())
                    if override:
                        override_agent = override.get("agent") if isinstance(override, dict) else override
                        selected_mode = override.get("mode", mode) if isinstance(override, dict) else mode
                        resolved = resolve_agent(override_agent)
                        if resolved:
                            chosen = resolved
                    agent_id = chosen["uuid"]
                    selected = auth.glz_post(
                        f"/pregame/v1/matches/{mid}/select/{agent_id}")
                    if selected.status_code >= 400:
                        raise RuntimeError(
                            f"Agent selection refused (HTTP {selected.status_code})")
                    if selected_mode == "lock":
                        locked = auth.glz_post(
                            f"/pregame/v1/matches/{mid}/lock/{agent_id}")
                        if locked.status_code >= 400:
                            raise RuntimeError(
                                f"Agent lock refused (HTTP {locked.status_code})")
                    done.add(mid)
                    self.state.update(
                        running=loop, status="locked", side=side,
                        agent=chosen["name"], map=map_name,
                        message=f"{'Locked' if selected_mode == 'lock' else 'Hovered'} "
                                f"{chosen['name']}"
                                + (f" on {map_name}" if map_name and map_name != "Unknown" else "")
                                + "!"
                                + (f"  You're {side}." if side else ""))
                    if not loop:
                        return
                    done.clear()
                    self.state.update(status="waiting", message="Boucle active — prochaine sélection surveillée…")
                self.state.update(
                    running=True, status="waiting",
                    message="Instalock armed — waiting for agent select…")
                if self._stop.wait(1.0):
                    break
            except Exception as error:
                auth = None
                self.state.update(
                    running=True, status="waiting",
                    message=f"Instalock retrying after error: {error}")
                if self._stop.wait(1.5):
                    break

        self.state.update(running=False)
        if self.state.get("status") not in ("locked", "error"):
            self.state.update(status="stopped", message="Stopped.")
