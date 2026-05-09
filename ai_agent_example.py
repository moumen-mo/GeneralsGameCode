#!/usr/bin/env python3
"""
Local AI agent example for C&C Generals Zero Hour RPC control.

Features:
1. Robust newline-delimited JSON RPC client (handles buffered multi-response reads)
2. Auto-detects controllable player (or use MY_PLAYER_ID env override)
3. Uses persistent set_controlled_player once per socket
4. Optional local LLM planning via Ollama (OpenAI-compatible or native API)
5. Fallback heuristic behavior when local LLM is disabled/unavailable

Run the game in SKIRMISH mode first, then run this script.
"""

import json
import math
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from dotenv import load_dotenv
load_dotenv()

# Message type values come from GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h
MSG_CREATE_SELECTED_GROUP = 1001
MSG_DO_ATTACK_OBJECT = 1059
MSG_DO_MOVETO = 1068
MSG_DO_ATTACKMOVETO = 1069
MSG_DO_FORCEMOVETO = 1070


# Global logger
class GameLogger:
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        
    def log(self, message: str) -> None:
        """Log to both console and file."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted = f"[{timestamp}] {message}"
        print(formatted)
        
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass  # Silently fail if can't write


_game_logger: Optional[GameLogger] = None


def set_game_logger(logger: GameLogger) -> None:
    global _game_logger
    _game_logger = logger


def game_log(message: str) -> None:
    """Global logging function."""
    if _game_logger:
        _game_logger.log(message)
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")



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

LLM_COMMAND_TUTOR = f"""You MUST output ONLY valid JSON. No text before or after.

Output ONLY this exact structure:
{{
  "commands": [
    {{"type": "attack_object", "unit_ids": [1, 2], "target_id": 123}},
    {{"type": "attack_move", "unit_ids": [1, 2], "x": 100.0, "y": 200.0, "z": 0.0}}
  ]
}}

Types: "attack_object", "attack_move", "move", "force_move"
- attack_object: requires unit_ids, target_id
- attack_move/move/force_move: requires unit_ids, x, y, z

Rules:
- ONLY valid JSON output
- Max 3 commands
- Empty array if no good moves: {{"commands": []}}
- NO markdown, NO explanations, NO extra text"""


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
        self.connection_id = 0
        
        # Logging setup
        log_file = os.getenv("RPC_LOG_FILE")
        self.log_enabled = log_file is not None and log_file.strip() != ""
        self.log_file = log_file if self.log_enabled else None
        self.logger = GameLogger(self.log_file)
        
        if self.log_enabled:
            # Initialize log file with header
            try:
                with open(self.log_file, "w") as f:
                    f.write("=" * 80 + "\n")
                    f.write(f"RPC Communication Log - Started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 80 + "\n\n")
                self.logger.log(f"RPC communication logging enabled: {self.log_file}")
            except Exception as e:
                print(f"Warning: Failed to initialize log file: {e}")
                self.log_enabled = False
        
        # Set global logger for use throughout the script
        set_game_logger(self.logger)
        
        self.connect()

    def _log_message(self, message_type: str, content: Dict) -> None:
        """Log JSON message to file with timestamp."""
        if not self.log_enabled or not self.log_file:
            return
        
        try:
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]  # HH:MM:SS.ms
            with open(self.log_file, "a") as f:
                f.write(f"[{timestamp}] {message_type}\n")
                f.write(json.dumps(content, indent=2) + "\n")
                f.write("-" * 80 + "\n\n")
        except Exception as e:
            print(f"Warning: Failed to log message: {e}")

    def connect(self) -> None:
        self.close()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        self.recv_buffer = ""
        self.connection_id += 1
        game_log(f"Connected to {self.host}:{self.port}")

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
        
        # Log outgoing request
        self._log_message("REQUEST SENT", payload)

        for attempt in range(retries + 1):
            try:
                assert self.sock is not None
                self.sock.sendall(encoded)

                while True:
                    line = self._readline()
                    if not line.strip():
                        continue
                    try:
                        response = json.loads(line)
                        # Log received response
                        self._log_message("RESPONSE RECEIVED", response)
                        return response
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

    def set_controlled_player(self, player_index: int) -> Dict:
        return self.request(
            {
                "action": "set_controlled_player",
                "player_index": int(player_index),
            },
            retries=1,
        )

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
    Calls a local Ollama endpoint.

    Supported endpoint styles:
    - OpenAI-compatible: http://127.0.0.1:11434/v1/chat/completions
    - Native Ollama API: http://127.0.0.1:11434/api/chat

    Expected assistant content JSON shape:
    {
      "commands": [
        {"type":"attack_object","target_id":123,"unit_ids":[10,11]},
        {"type":"attack_move","x":1000,"y":2000,"z":0,"unit_ids":[10,11]}
      ]
    }
    """

    def __init__(self) -> None:
        # Default ON for local Ollama usage; set LOCAL_LLM_ENABLED=0 to disable.
        self.enabled = os.getenv("LOCAL_LLM_ENABLED", "1") == "1"
        self.endpoint = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions")
        self.model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:latest")
        # Default timeout increased to 30 seconds; adjust with LOCAL_LLM_TIMEOUT env var
        self.timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "30"))
        self.llm_debug = os.getenv("LLM_DEBUG", "0") == "1"

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

        system_prompt = LLM_COMMAND_TUTOR

        user_prompt = {
            "instruction": (
                "Choose immediate tactical commands for this tick. "
                "Prioritize survival, favorable trades, and short decisive actions."
            ),
            "state": snapshot,
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))},
        ]

        use_native_ollama = "/api/chat" in self.endpoint.lower()
        if use_native_ollama:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.2},
            }
        else:
            payload = {
                "model": self.model,
                "temperature": 0.2,
                "messages": messages,
            }

        if self.llm_debug:
            game_log(f"[LLM DEBUG] Sending request to: {self.endpoint}")
            game_log(f"[LLM DEBUG] Model: {self.model}")
            game_log(f"[LLM DEBUG] Timeout: {self.timeout}s")
            game_log(f"[LLM DEBUG] Payload size: {len(json.dumps(payload))} bytes")
            game_log(f"[LLM DEBUG] Snapshot - my_units: {len(snapshot.get('my_units', []))}, enemy_units: {len(snapshot.get('enemy_units', []))}, objects: {len(snapshot.get('objects_in_prompt', []))}")

        req = urlrequest.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urlerror.HTTPError as http_err:
            game_log(f"Local LLM HTTP Error {http_err.code}: {http_err.reason} - Check if Ollama is running and endpoint is correct")
            game_log(f"  Endpoint: {self.endpoint}")
            game_log(f"  Model: {self.model}")
            game_log(f"  Timeout: {self.timeout}s (increase with LOCAL_LLM_TIMEOUT env var)")
            return []
        except TimeoutError as exc:
            game_log(f"Local LLM timeout ({self.timeout}s): {exc}")
            game_log(f"  The LLM is taking too long. Try:")
            game_log(f"  1. Increase timeout: set LOCAL_LLM_TIMEOUT=60")
            game_log(f"  2. Use a faster model: ollama pull mistral:7b")
            game_log(f"  3. Check Ollama: curl http://127.0.0.1:11434/api/tags")
            return []
        except (urlerror.URLError, OSError) as exc:
            game_log(f"Local LLM unavailable: {exc}")
            game_log(f"  Check if Ollama is running: ollama serve")
            return []

        try:
            result = json.loads(body)
            if use_native_ollama:
                content = result["message"]["content"]
            else:
                content = result["choices"][0]["message"]["content"]
        except Exception:
            game_log("Local LLM response format unexpected")
            return []

        parsed = self._extract_json(content)
        if not parsed:
            game_log("Local LLM did not return parseable JSON commands")
            print("LLM response content:")
            print(content)
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
        self.llm_object_limit = int(os.getenv("LLM_STATE_OBJECT_LIMIT", "140"))
        self.llm_debug = os.getenv("LLM_DEBUG", "0") == "1"

        my_player_env = os.getenv("MY_PLAYER_ID")
        self.my_player_id = int(my_player_env) if my_player_env is not None else None
        self.rpc_controlled_player_id: Optional[int] = None
        self.rpc_controlled_player_connection_id: Optional[int] = None

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

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
            game_log(f"Using player_id={self.my_player_id} ({next((p.side for p in players if p.id == self.my_player_id), 'unknown')})")
            return self.my_player_id

        self.my_player_id = 0
        return self.my_player_id

    def _ensure_rpc_controlled_player(self, player_id: int) -> None:
        if (
            self.rpc_controlled_player_id == player_id
            and self.rpc_controlled_player_connection_id == self.client.connection_id
        ):
            return
        reply = self.client.set_controlled_player(player_id)
        if reply.get("status") != "ok":
            raise RuntimeError(f"set_controlled_player failed: {reply}")
        self.rpc_controlled_player_id = player_id
        self.rpc_controlled_player_connection_id = self.client.connection_id
        game_log(f"RPC controlled player set to {player_id}")

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

    def _build_llm_snapshot(self, state: Dict, my_id: int, my_units: List[Unit], enemy_units: List[Unit]) -> Dict:
        # Build players payload, excluding civilian players
        players_payload = []
        civilian_player_ids = set()
        for p in state.get("players", [])[:16]:
            side = str(p.get("side", "")).lower()
            player_id = int(p.get("player_id", -1))
            
            # Track civilian player IDs to filter their objects later
            if side in IGNORE_PLAYER_SIDES:
                civilian_player_ids.add(player_id)
                continue  # Skip adding civilian players to payload
            
            players_payload.append(
                {
                    "player_id": player_id,
                    "side": side,
                    "money": float(p.get("money", 0.0)),
                }
            )

        # Build objects payload, excluding objects from civilian players
        objects_payload = []
        objects = state.get("objects", [])
        for obj in objects[: self.llm_object_limit]:
            obj_player_id = int(obj.get("player_id", -1))
            
            # Skip objects belonging to civilian players
            if obj_player_id in civilian_player_ids:
                continue
            
            pos = obj.get("position", {}) or {}
            objects_payload.append(
                {
                    "id": int(obj.get("id", -1)),
                    "template_name": str(obj.get("template_name", "Unknown")),
                    "player_id": obj_player_id,
                    "x": float(pos.get("x", 0.0)),
                    "y": float(pos.get("y", 0.0)),
                    "z": float(pos.get("z", 0.0)),
                    "health_percent": float(obj.get("health_percent", 100.0)),
                    "is_selected": bool(obj.get("is_selected", False)),
                }
            )

        snapshot = {
            "frame": int(float(state.get("frame", self.frame_count))),
            "map_width": float(state.get("map_width", 0.0)),
            "map_height": float(state.get("map_height", 0.0)),
            "my_player_id": my_id,
            "players": players_payload,
            "object_count_total": int(state.get("object_count", len(objects))),
            "objects_in_prompt": objects_payload,
            "my_units": [
                {
                    "id": u.id,
                    "name": u.name,
                    "x": round(u.position.x, 1),
                    "y": round(u.position.y, 1),
                    "hp": round(u.health_percent, 1),
                }
                for u in my_units[:40]
            ],
            "enemy_units": [
                {
                    "id": u.id,
                    "name": u.name,
                    "x": round(u.position.x, 1),
                    "y": round(u.position.y, 1),
                    "hp": round(u.health_percent, 1),
                }
                for u in enemy_units[:40]
            ],
        }
        return snapshot

    def _sanitize_llm_commands(
        self,
        commands: List[Dict],
        my_units: List[Unit],
        enemy_units: List[Unit],
        map_width: float,
        map_height: float,
    ) -> List[Dict]:
        if not commands:
            return []

        my_ids = {u.id for u in my_units}
        enemy_ids = {u.id for u in enemy_units}
        fallback_squad = [u.id for u in my_units[:8]]
        if not fallback_squad:
            return []

        sanitized: List[Dict] = []
        for cmd in commands[:3]:
            if not isinstance(cmd, dict):
                continue

            cmd_type = str(cmd.get("type", "")).strip().lower()
            if cmd_type not in {"attack_object", "attack_move", "move", "force_move"}:
                continue

            unit_ids_raw = cmd.get("unit_ids", [])
            unit_ids = []
            if isinstance(unit_ids_raw, list):
                for v in unit_ids_raw:
                    if isinstance(v, (int, float)):
                        obj_id = int(v)
                        if obj_id in my_ids:
                            unit_ids.append(obj_id)
            if not unit_ids:
                unit_ids = fallback_squad

            normalized: Dict = {"type": cmd_type, "unit_ids": unit_ids}

            if cmd_type == "attack_object":
                target_id = cmd.get("target_id")
                if not isinstance(target_id, (int, float)):
                    continue
                target_id_int = int(target_id)
                if target_id_int not in enemy_ids:
                    continue
                normalized["target_id"] = target_id_int
            else:
                x = cmd.get("x")
                y = cmd.get("y")
                z = cmd.get("z", 0.0)
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    continue
                normalized["x"] = self._clamp(float(x), 0.0, map_width)
                normalized["y"] = self._clamp(float(y), 0.0, map_height)
                normalized["z"] = float(z) if isinstance(z, (int, float)) else 0.0

            sanitized.append(normalized)

        return sanitized

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
        game_log("Starting AI loop")
        game_log(f"Decision interval: {self.decision_interval} frames")
        if self.planner.enabled:
            game_log(f"Local LLM planner enabled: model={self.planner.model}")
            game_log(f"Local LLM endpoint: {self.planner.endpoint}")
            game_log(f"LLM state object limit: {self.llm_object_limit}")
        else:
            game_log("Local LLM planner disabled (set LOCAL_LLM_ENABLED=1 to enable)")

        while self.frame_count < self.max_frames:
            try:
                state = self.client.get_state()
            except Exception as exc:
                game_log(f"RPC state fetch failed: {exc}")
                time.sleep(0.4)
                continue

            if state.get("status") != "ok":
                game_log(f"State error: {state}")
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

            try:
                self._ensure_rpc_controlled_player(my_id)
            except Exception as exc:
                game_log(f"Failed to set controlled player: {exc}")
                time.sleep(0.4)
                continue

            if frame % self.decision_interval == 0:
                snapshot = self._build_llm_snapshot(state, my_id, my_units, enemy_units)
                if self.llm_debug:
                    game_log(
                        f"[Frame {frame}] LLM snapshot: objects_in_prompt={len(snapshot['objects_in_prompt'])}, "
                        f"my_units={len(snapshot['my_units'])}, enemy_units={len(snapshot['enemy_units'])}"
                    )

                commands = self.planner.plan(snapshot)
                commands = self._sanitize_llm_commands(
                    commands,
                    my_units,
                    enemy_units,
                    map_width=float(state.get("map_width", 0.0)),
                    map_height=float(state.get("map_height", 0.0)),
                )
                if not commands:
                    commands = self._fallback_commands(my_units, enemy_units)

                if commands:
                    try:
                        self._execute_commands(commands)
                        game_log(f"[Frame {frame}] Commands: {commands}")
                    except Exception as exc:
                        game_log(f"[Frame {frame}] Command execution failed: {exc}")
                else:
                    game_log(
                        f"[Frame {frame}] No commands (my_units={len(my_units)}, enemy_units={len(enemy_units)}, my_player={my_id})"
                    )

            time.sleep(self.sleep_seconds)


def main() -> None:
    print("=" * 60)
    print("C&C Generals Zero Hour - Local AI RPC Agent")
    print("=" * 60)

    host = os.getenv("RPC_HOST", "127.0.0.1")
    port = int(os.getenv("RPC_PORT", "4500"))
    log_file = os.getenv("RPC_LOG_FILE")
    
    if log_file:
        print(f"RPC communication will be logged to: {log_file}")
    else:
        print("(Set RPC_LOG_FILE environment variable to log RPC communication)")

    client = GameRpcClient(host=host, port=port, timeout=float(os.getenv("RPC_TIMEOUT", "10")))
    if not client.ping():
        game_log("RPC ping failed")
        return

    state = client.get_state()
    if state.get("status") == "ok":
        game_log(f"Frame: {state.get('frame')}")
        game_log(f"Map: {state.get('map_width')} x {state.get('map_height')}")
        game_log(f"Objects: {state.get('object_count')}")

        players = state.get("players", [])
        game_log("Players:")
        for p in players:
            game_log(f"  Player {int(p.get('player_id', -1))}: {p.get('side', '')} (${float(p.get('money', 0.0)):.0f})")

    controller = LocalAiController(client)
    try:
        controller.run()
    except KeyboardInterrupt:
        game_log("Stopped by user")
    finally:
        client.close()


if __name__ == "__main__":
    main()


