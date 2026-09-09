from __future__ import annotations

import base64
import json
import threading

from agents import resolve_agent
from riot_client import LocalAuth
from vconstants import map_name_from_path

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
    pass

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.state = {"running": False, "status": "idle", "message": "",
                  "agent": None, "mode": "lock", "loop": False, "delay": 5.0,
                  "side": None, "map": None}

    def status(self) -> dict:
        return dict(self.state)

    @staticmethod
    def _normalize_per_map(per_map: dict | None) -> dict:
        pass
        out: dict[str, str] = {}
        for k, v in (per_map or {}).items():
            if k and v:
                out[str(k).strip().lower()] = str(v).strip()
        return out

    def start(self, agent_id: str, mode: str = "lock", delay: float = 5.0,
              region: str | None = None, per_map: dict | None = None,
              loop: bool = False) -> dict:
        agent = resolve_agent(agent_id)
        if not agent:
            return {"ok": False, "message": f"Agent inconnu : « {agent_id} »."}
        per_map_norm = self._normalize_per_map(per_map)

        for mapn, name in per_map_norm.items():
            if not resolve_agent(name):
                return {"ok": False,
                        "message": f"Agent inconnu : « {name} » pour la carte « {mapn} »."}
        self.stop()
        with self._lock:
            self._stop.clear()
            try:
                delay_seconds = max(0.0, float(delay if delay is not None else 5))
            except (TypeError, ValueError):
                return {"ok": False, "message": "Le délai doit être un nombre de secondes."}
            self.state.update(running=True, status="waiting", agent=agent["name"],
                              mode=mode, loop=bool(loop), delay=delay_seconds, side=None, map=None,
                              message="Instalock prêt : en attente de la sélection des agents…")
            self._thread = threading.Thread(
                target=self._loop,
                args=(agent, mode, delay_seconds, region, per_map_norm, bool(loop)),
                daemon=True)
            self._thread.start()
        return {"ok": True, "running": True, "agent": agent["name"],
                "status": "waiting", "loop": bool(loop), "delay": delay_seconds,
                "perMap": per_map_norm}

    def stop(self) -> dict:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.5)
        if self.state.get("status") in ("waiting", "running"):
            self.state.update(status="stopped", message="Stopped.")
        self.state.update(running=False)
        return {"ok": True, "running": False}

    def _loop(self, agent: dict, mode: str, delay: float, region, per_map: dict,
              loop: bool):
        done: set[str] = set()
        auth = None

        while not self._stop.is_set():
            try:
                if auth is None:
                    auth = LocalAuth(region)
                    auth.headers()
                presences = (auth.local_get("/chat/v4/presences") or {}).get("presences", [])
                st = _self_session_state(presences, auth.puuid)
                # The pregame endpoint is also authoritative for custom games;
                # chat presence can lag behind or use a different session state.
                pg = auth.glz_get(f"/pregame/v1/players/{auth.puuid}")
                mid = pg.get("MatchID") if isinstance(pg, dict) else None
                if mid and mid not in done:
                    if delay > 0 and self._stop.wait(delay):
                        break
                    match = auth.glz_get(f"/pregame/v1/matches/{mid}")
                    side = _side_from_match(match, auth.puuid)
                    map_name = map_name_from_path((match or {}).get("MapID", ""))

                    chosen = agent
                    override = per_map.get((map_name or "").lower())
                    if override:
                        resolved = resolve_agent(override)
                        if resolved:
                            chosen = resolved
                    agent_id = chosen["uuid"]
                    selected = auth.glz_post(f"/pregame/v1/matches/{mid}/select/{agent_id}")
                    if selected.status_code >= 400:
                        raise RuntimeError(f"sélection refusée (HTTP {selected.status_code})")
                    if mode == "lock":
                        locked = auth.glz_post(f"/pregame/v1/matches/{mid}/lock/{agent_id}")
                        if locked.status_code >= 400:
                            raise RuntimeError(f"verrouillage refusé (HTTP {locked.status_code})")
                    done.add(mid)
                    self.state.update(
                        running=bool(loop), status="waiting" if loop else "locked", side=side,
                        agent=chosen["name"], map=map_name,
                        message=(f"{'Agent verrouillé' if mode == 'lock' else 'Agent survolé'} : "
                            f"{chosen['name']}"
                            + (f" sur {map_name}" if map_name and map_name != "Unknown" else "")
                            + "!"
                            + (f"  Tu es en {side}." if side else "")
                            + (" Prochain cycle armé." if loop else "")))
                    if not loop:
                        return

                elif st is None:
                    self.state.update(
                        running=True, status="waiting",
                        message="En attente de VALORANT et de la sélection des agents…")
                if self._stop.wait(1.0):
                    break
            except Exception as error:
                auth = None
                self.state.update(
                    running=True, status="waiting",
                    message="Connexion au client local en attente…")
                if self._stop.wait(1.5):
                    break

        self.state.update(running=False)
        if self.state.get("status") not in ("locked", "error"):
            self.state.update(status="stopped", message="Instalock arrêté.")
