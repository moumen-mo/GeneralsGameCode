#!/usr/bin/env python3
"""
Local AI agent example for C&C Generals Zero Hour RPC control.

Features:
1. Robust newline-delimited JSON RPC client (handles buffered multi-response reads)
2. Auto-detects controllable player (or use MY_PLAYER_ID env override)
3. Optional local LLM planning via OpenAI-compatible local endpoint
4. Fallback heuristic behavior when local LLM is disabled/unavailable

Run the game in SKIRMISH mode first, then run this script.
"""

import json
import math
import os
import socket
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest


# Message type values come from GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h
MSG_CREATE_SELECTED_GROUP = 1001
MSG_DO_ATTACK_OBJECT = 1059
MSG_DO_MOVETO = 1068
MSG_DO_ATTACKMOVETO = 1069
MSG_DO_FORCEMOVETO = 1070


IGNORE_PLAYER_SIDES = {"", "civilian", "observer"}
BUILDING_KEYWORDS = (
    "commandcenter",
    "warfactory",
    "barracks",
    "supply",
    "power",
    "reactor",
    "airfield",
    "palace",
    "propaganda",
    "center",
    "depot",
    "building",
    "scaffold",
    "bunker",
    "tower",
    "wall",
)


@dataclass
class Position:
    x: float
    y: float
    z: float = 0.0

    def distance_to(self, other: "Position") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass
class Unit:
    id: int
    name: str
    position: Position
    player_id: int
    health: float
    max_health: float

    @property
    def health_percent(self) -> float:
        if self.max_health <= 0:
            return 100.0
        return (self.health / self.max_health) * 100.0

    @property
    def is_building_like(self) -> bool:
        n = self.name.lower()
        return any(k in n for k in BUILDING_KEYWORDS)


@dataclass
class Player:
    id: int
    side: str
    money: float


class GameRpcClient:
    """TCP RPC client for newline-delimited JSON protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4500, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.recv_buffer = ""
        self.connect()

    def connect(self) -> None:
        self.close()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        self.recv_buffer = ""
        print(f"Connected to {self.host}:{self.port}")

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _readline(self) -> str:
        if self.sock is None:
            raise RuntimeError("Socket is not connected")

        while True:
            newline_pos = self.recv_buffer.find("\n")
            if newline_pos >= 0:
                line = self.recv_buffer[:newline_pos]
                self.recv_buffer = self.recv_buffer[newline_pos + 1 :]
                return line.rstrip("\r")

            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("Connection closed by server")
            self.recv_buffer += chunk.decode("utf-8", errors="replace")

    def request(self, payload: Dict, retries: int = 1) -> Dict:
        if self.sock is None:
            self.connect()

        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

        for attempt in range(retries + 1):
            try:
                assert self.sock is not None
                self.sock.sendall(encoded)

                while True:
                    line = self._readline()
                    if not line.strip():
                        continue
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError:
                        # If this line is malformed, continue to next line.
                        # This keeps the client resilient when mixed/garbled fragments appear.
                        continue
            except (socket.timeout, OSError, RuntimeError):
                if attempt >= retries:
                    raise
                time.sleep(0.2)
                self.connect()

        raise RuntimeError("Unreachable")

    def ping(self) -> bool:
        try:
            reply = self.request({"action": "ping"}, retries=1)
            return reply.get("status") == "ok"
        except Exception:
            return False

    def get_state(self) -> Dict:
        return self.request({"action": "get_state"}, retries=1)

    def create_game_message(self, message_type: int, arguments: List[Dict]) -> Dict:
        return self.request(
            {
                "action": "create_game_message",
                "message_type": message_type,
                "arguments": arguments,
            },
            retries=1,
        )

    def select_objects(self, object_ids: List[int], create_new: bool = True) -> Dict:
        args: List[Dict] = [{"type": "boolean", "value": bool(create_new)}]
        args.extend({"type": "integer", "value": int(obj_id)} for obj_id in object_ids)
        return self.create_game_message(MSG_CREATE_SELECTED_GROUP, args)

    def move_to(self, x: float, y: float, z: float = 0.0) -> Dict:
        return self.create_game_message(
            MSG_DO_MOVETO,
            [{"type": "location", "x": x, "y": y, "z": z}],
        )

    def attack_move_to(self, x: float, y: float, z: float = 0.0) -> Dict:
        return self.create_game_message(
            MSG_DO_ATTACKMOVETO,
            [{"type": "location", "x": x, "y": y, "z": z}],
        )

    def force_move_to(self, x: float, y: float, z: float = 0.0) -> Dict:
        return self.create_game_message(
            MSG_DO_FORCEMOVETO,
            [{"type": "location", "x": x, "y": y, "z": z}],
        )

    def attack_object(self, target_id: int) -> Dict:
        return self.create_game_message(
            MSG_DO_ATTACK_OBJECT,
            [{"type": "integer", "value": int(target_id)}],
        )


class LocalLlmPlanner:
    """
    Calls a local OpenAI-compatible endpoint.

    Expected response content JSON shape:
    {
      "commands": [
        {"type":"attack_object","target_id":123,"unit_ids":[10,11]},
        {"type":"attack_move","x":1000,"y":2000,"z":0,"unit_ids":[10,11]}
      ]
    }
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("LOCAL_LLM_ENABLED", "0") == "1"
        self.endpoint = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions")
        self.model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct")
        self.timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "12"))

    def _extract_json(self, text: str) -> Optional[Dict]:
        text = text.strip()
        if not text:
            return None

        # Direct parse
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

        # Parse JSON block in fenced output
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                try:
                    value = json.loads(candidate)
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    continue

        # Parse first object substring
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                return None
        return None

    def plan(self, snapshot: Dict) -> List[Dict]:
        if not self.enabled:
            return []

        system_prompt = (
            "You are an RTS micro planner for C&C Generals Zero Hour. "
            "Return ONLY JSON object with key 'commands'. "
            "Each command: type in ['attack_object','attack_move','move','force_move'], "
            "optional unit_ids array, and required fields for that type. "
            "Maximum 3 commands."
        )

        user_prompt = {
            "instruction": "Choose immediate tactical commands for this tick.",
            "state": snapshot,
        }

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))},
            ],
        }

        req = urlrequest.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            print(f"Local LLM unavailable: {exc}")
            return []

        try:
            result = json.loads(body)
            content = result["choices"][0]["message"]["content"]
        except Exception:
            print("Local LLM response format unexpected")
            return []

        parsed = self._extract_json(content)
        if not parsed:
            print("Local LLM did not return parseable JSON commands")
            return []

        commands = parsed.get("commands", [])
        if not isinstance(commands, list):
            return []

        safe_commands: List[Dict] = []
        for cmd in commands[:3]:
            if not isinstance(cmd, dict):
                continue
            cmd_type = str(cmd.get("type", "")).strip().lower()
            if cmd_type not in {"attack_object", "attack_move", "move", "force_move"}:
                continue

            normalized: Dict = {"type": cmd_type}
            unit_ids = cmd.get("unit_ids", [])
            if isinstance(unit_ids, list):
                normalized["unit_ids"] = [int(v) for v in unit_ids if isinstance(v, (int, float))]

            if cmd_type == "attack_object":
                target_id = cmd.get("target_id")
                if not isinstance(target_id, (int, float)):
                    continue
                normalized["target_id"] = int(target_id)
            else:
                x = cmd.get("x")
                y = cmd.get("y")
                z = cmd.get("z", 0.0)
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    continue
                normalized["x"] = float(x)
                normalized["y"] = float(y)
                normalized["z"] = float(z) if isinstance(z, (int, float)) else 0.0

            safe_commands.append(normalized)

        return safe_commands


class LocalAiController:
    def __init__(self, client: GameRpcClient):
        self.client = client
        self.planner = LocalLlmPlanner()
        self.frame_count = 0
        self.decision_interval = int(os.getenv("DECISION_INTERVAL_FRAMES", "12"))
        self.max_frames = int(os.getenv("MAX_FRAMES", "10000"))
        self.sleep_seconds = float(os.getenv("AI_LOOP_SLEEP", "0.12"))

        my_player_env = os.getenv("MY_PLAYER_ID")
        self.my_player_id = int(my_player_env) if my_player_env is not None else None

    def _to_players(self, state: Dict) -> List[Player]:
        out: List[Player] = []
        for p in state.get("players", []):
            out.append(
                Player(
                    id=int(p.get("player_id", -1)),
                    side=str(p.get("side", "")),
                    money=float(p.get("money", 0.0)),
                )
            )
        return out

    def _to_units(self, state: Dict) -> List[Unit]:
        out: List[Unit] = []
        for obj in state.get("objects", []):
            pos = obj.get("position", {}) or {}
            out.append(
                Unit(
                    id=int(obj.get("id", -1)),
                    name=str(obj.get("template_name", "Unknown")),
                    position=Position(
                        x=float(pos.get("x", 0.0)),
                        y=float(pos.get("y", 0.0)),
                        z=float(pos.get("z", 0.0)),
                    ),
                    player_id=int(obj.get("player_id", -1)),
                    health=float(obj.get("health", 0.0)),
                    max_health=float(obj.get("max_health", 1.0)),
                )
            )
        return out

    def _detect_player_id(self, players: List[Player], units: List[Unit]) -> int:
        if self.my_player_id is not None:
            return self.my_player_id

        unit_counts: Dict[int, int] = {}
        for u in units:
            if u.player_id >= 0:
                unit_counts[u.player_id] = unit_counts.get(u.player_id, 0) + 1

        candidates: List[Player] = []
        for p in players:
            if p.side.lower() in IGNORE_PLAYER_SIDES:
                continue
            candidates.append(p)

        if candidates:
            candidates.sort(key=lambda p: p.id)
            with_units = [p for p in candidates if unit_counts.get(p.id, 0) > 0]
            self.my_player_id = (with_units[0] if with_units else candidates[0]).id
            print(f"Using player_id={self.my_player_id} ({next((p.side for p in players if p.id == self.my_player_id), 'unknown')})")
            return self.my_player_id

        self.my_player_id = 0
        return self.my_player_id

    def _split_for_decision(self, players: List[Player], units: List[Unit]) -> Dict:
        my_id = self._detect_player_id(players, units)

        my_units = [u for u in units if u.player_id == my_id and u.health > 0 and not u.is_building_like]

        enemy_player_ids = {
            p.id for p in players if p.id != my_id and p.side.lower() not in IGNORE_PLAYER_SIDES
        }
        enemy_units = [u for u in units if u.player_id in enemy_player_ids and u.health > 0 and not u.is_building_like]

        return {
            "my_player_id": my_id,
            "my_units": my_units,
            "enemy_units": enemy_units,
        }

    def _nearest_enemy(self, unit: Unit, enemies: List[Unit]) -> Optional[Unit]:
        if not enemies:
            return None
        return min(enemies, key=lambda e: unit.position.distance_to(e.position))

    def _fallback_commands(self, my_units: List[Unit], enemy_units: List[Unit]) -> List[Dict]:
        if not my_units or not enemy_units:
            return []

        squad = [u.id for u in my_units[:8]]
        anchor = my_units[0]
        target = self._nearest_enemy(anchor, enemy_units)
        if target is None:
            return []

        distance = anchor.position.distance_to(target.position)
        if distance < 420.0:
            return [{"type": "attack_object", "target_id": target.id, "unit_ids": squad}]

        return [
            {
                "type": "attack_move",
                "x": target.position.x,
                "y": target.position.y,
                "z": target.position.z,
                "unit_ids": squad,
            }
        ]

    def _execute_commands(self, commands: List[Dict]) -> None:
        for cmd in commands[:3]:
            unit_ids = [int(i) for i in cmd.get("unit_ids", []) if isinstance(i, int)]
            if unit_ids:
                self.client.select_objects(unit_ids, create_new=True)

            cmd_type = cmd.get("type")
            if cmd_type == "attack_object":
                self.client.attack_object(int(cmd["target_id"]))
            elif cmd_type == "attack_move":
                self.client.attack_move_to(float(cmd["x"]), float(cmd["y"]), float(cmd.get("z", 0.0)))
            elif cmd_type == "move":
                self.client.move_to(float(cmd["x"]), float(cmd["y"]), float(cmd.get("z", 0.0)))
            elif cmd_type == "force_move":
                self.client.force_move_to(float(cmd["x"]), float(cmd["y"]), float(cmd.get("z", 0.0)))

    def run(self) -> None:
        print("Starting AI loop")
        print(f"Decision interval: {self.decision_interval} frames")
        if self.planner.enabled:
            print(f"Local LLM planner enabled: model={self.planner.model}")
        else:
            print("Local LLM planner disabled (set LOCAL_LLM_ENABLED=1 to enable)")

        while self.frame_count < self.max_frames:
            try:
                state = self.client.get_state()
            except Exception as exc:
                print(f"RPC state fetch failed: {exc}")
                time.sleep(0.4)
                continue

            if state.get("status") != "ok":
                print(f"State error: {state}")
                time.sleep(0.4)
                continue

            frame = int(float(state.get("frame", self.frame_count)))
            self.frame_count = max(self.frame_count + 1, frame)

            players = self._to_players(state)
            units = self._to_units(state)
            sliced = self._split_for_decision(players, units)
            my_id = sliced["my_player_id"]
            my_units = sliced["my_units"]
            enemy_units = sliced["enemy_units"]

            if frame % self.decision_interval == 0:
                snapshot = {
                    "frame": frame,
                    "my_player_id": my_id,
                    "my_units": [
                        {
                            "id": u.id,
                            "name": u.name,
                            "x": round(u.position.x, 1),
                            "y": round(u.position.y, 1),
                            "hp": round(u.health_percent, 1),
                        }
                        for u in my_units[:20]
                    ],
                    "enemy_units": [
                        {
                            "id": u.id,
                            "name": u.name,
                            "x": round(u.position.x, 1),
                            "y": round(u.position.y, 1),
                            "hp": round(u.health_percent, 1),
                        }
                        for u in enemy_units[:20]
                    ],
                }

                commands = self.planner.plan(snapshot)
                if not commands:
                    commands = self._fallback_commands(my_units, enemy_units)

                if commands:
                    try:
                        self._execute_commands(commands)
                        print(f"[Frame {frame}] Commands: {commands}")
                    except Exception as exc:
                        print(f"[Frame {frame}] Command execution failed: {exc}")
                else:
                    print(
                        f"[Frame {frame}] No commands (my_units={len(my_units)}, enemy_units={len(enemy_units)}, my_player={my_id})"
                    )

            time.sleep(self.sleep_seconds)


def main() -> None:
    print("=" * 60)
    print("C&C Generals Zero Hour - Local AI RPC Agent")
    print("=" * 60)

    host = os.getenv("RPC_HOST", "127.0.0.1")
    port = int(os.getenv("RPC_PORT", "4500"))

    client = GameRpcClient(host=host, port=port, timeout=float(os.getenv("RPC_TIMEOUT", "10")))
    if not client.ping():
        print("RPC ping failed")
        return

    state = client.get_state()
    if state.get("status") == "ok":
        print(f"Frame: {state.get('frame')}")
        print(f"Map: {state.get('map_width')} x {state.get('map_height')}")
        print(f"Objects: {state.get('object_count')}")

        players = state.get("players", [])
        print("Players:")
        for p in players:
            print(f"  Player {int(p.get('player_id', -1))}: {p.get('side', '')} (${float(p.get('money', 0.0)):.0f})")

    controller = LocalAiController(client)
    try:
        controller.run()
    except KeyboardInterrupt:
        print("Stopped by user")
    finally:
        client.close()


if __name__ == "__main__":
    main()
