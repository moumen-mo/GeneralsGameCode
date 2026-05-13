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
from AI_Agent.m_logs.local_ai_controller import LocalAiController
load_dotenv()

# Message type values come from GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h
MSG_CREATE_SELECTED_GROUP = 1001
MSG_DO_ATTACK_OBJECT = 1059
MSG_DO_MOVETO = 1068
MSG_DO_ATTACKMOVETO = 1069
MSG_DO_FORCEMOVETO = 1070
MSG_DOZER_CONSTRUCT = 1049


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

DEFAULT_SYSTEM_PROMPT_PATH = "system_prompt.txt"


def _load_system_prompt(path: str) -> str:
    """Load base system prompt text from file."""
    with open(path, "r", encoding="utf-8") as f:
        prompt_text = f.read().strip()

    if not prompt_text:
        raise ValueError(f"System prompt file '{path}' is empty")

    return prompt_text


_system_prompt_path = os.getenv("SYSTEM_PROMPT_PATH", DEFAULT_SYSTEM_PROMPT_PATH)
LLM_COMMAND_TUTOR = _load_system_prompt(_system_prompt_path)

DEFAULT_COMMAND_LIBRARY_PATH = "Commands_Library.json"


def _load_command_library(path: str) -> List[Dict]:
    """Load command definitions from Commands_Library.json."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        game_log(f"[PROMPT] Could not load command library '{path}': {exc}")
        return []

    if not isinstance(payload, list):
        game_log(f"[PROMPT] Command library '{path}' must be a JSON array")
        return []

    commands: List[Dict] = []
    for item in payload:
        if isinstance(item, dict) and item.get("command"):
            commands.append(item)
    return commands


def _build_command_library_section(commands: List[Dict]) -> str:
    """Render command library as prompt text."""
    lines = [
        "AVAILABLE COMMAND LIBRARY (use these command names/arguments when possible):"
    ]
    for entry in commands:
        command = str(entry.get("command", "")).strip()
        message_type = entry.get("message_type", "?")
        args = entry.get("args", [])
        if isinstance(args, list):
            args_text = ", ".join(str(arg) for arg in args) if args else "none"
        else:
            args_text = str(args)
        description = str(entry.get("description", "")).replace("\n", " ").strip()
        lines.append(
            f"- {command}: message_type={message_type}, args=[{args_text}], description={description}"
        )
    return "\n".join(lines)


def build_system_prompt_with_command_library(base_prompt: str) -> str:
    """
    Build final system prompt by appending Commands_Library.json content.
    Controls:
    - COMMAND_LIBRARY_PATH (default: Commands_Library.json)
    - SYSTEM_PROMPT_INCLUDE_COMMAND_LIBRARY=0 to disable
    - SYSTEM_PROMPT_COMMAND_LIMIT (default: 120)
    """
    if os.getenv("SYSTEM_PROMPT_INCLUDE_COMMAND_LIBRARY", "1") != "1":
        return base_prompt

    path = os.getenv("COMMAND_LIBRARY_PATH", DEFAULT_COMMAND_LIBRARY_PATH)
    try:
        limit = max(1, int(os.getenv("SYSTEM_PROMPT_COMMAND_LIMIT", "120")))
    except ValueError:
        limit = 120

    commands = _load_command_library(path)
    if not commands:
        return base_prompt

    selected = commands[:limit]
    game_log(f"[PROMPT] Added {len(selected)} commands from '{path}' to system prompt")
    return f"{base_prompt}\n\n{_build_command_library_section(selected)}"


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

    def construct(self, template_id: int, x: float, y: float, z: float = 0.0) -> Dict:
        return self.create_game_message(
            MSG_DOZER_CONSTRUCT,
            [
                {"type": "integer", "value": int(template_id)},
                {"type": "location", "x": x, "y": y, "z": z},
            ],
        )


class SystemPromptCache:
    """
    Cache for system prompt to avoid resending static command schema on every tick.
    This implements the optimization from tasl.txt:
    - System Prompt (static schema) is sent once and cached
    - User Message (dynamic game state) is sent every tick
    """

    def __init__(self) -> None:
        self.cached_system_prompt = build_system_prompt_with_command_library(LLM_COMMAND_TUTOR)
        self.use_cache = os.getenv("PROMPT_CACHE_ENABLED", "1") == "1"
        self.cache_stats = {"hits": 0, "sends": 0}

    def get_messages_with_cache(
        self, user_prompt: Dict, first_call: bool = False
    ) -> tuple[list, bool]:
        """
        Returns (messages list, should_send_system_prompt).
        
        If use_cache is True:
        - First call: Returns full messages with system prompt
        - Subsequent calls: Returns user message only (relies on LLM context retention)
        
        This reduces token overhead by not resending the static command schema.
        """
        if not self.use_cache or first_call:
            messages = [
                {"role": "system", "content": self.cached_system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))},
            ]
            self.cache_stats["sends"] += 1
            return messages, True

        # Subsequent calls: only send user message (relies on LLM keeping schema in context)
        messages = [
            {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))}
        ]
        self.cache_stats["hits"] += 1
        return messages, False

    def log_cache_stats(self) -> None:
        """Log cache efficiency statistics."""
        total = self.cache_stats["sends"] + self.cache_stats["hits"]
        if total > 0:
            efficiency = (self.cache_stats["hits"] / total) * 100
            game_log(
                f"[CACHE STATS] System prompt sent {self.cache_stats['sends']} times, "
                f"reused {self.cache_stats['hits']} times (efficiency: {efficiency:.1f}%)"
            )


class StateCompressor:
    """
    3-layer compression strategy for game state JSON (from tasl.txt):
    
    Layer 1: Drop redundant fields (max_health if normalized, static map info)
    Layer 2: Use numeric IDs and abbreviations (t→TNK, hp→h, pos→[x,y])
    Layer 3: Delta encoding (only send fields that changed since last frame)
    
    Reduces state payload by ~85% compared to uncompressed format.
    """

    # Field abbreviation mappings
    PLAYER_FIELDS = {
        "player_id": "p",
        "side": "s", 
        "money": "$",
    }

    OBJECT_FIELDS = {
        "id": "i",
        "template_name": "t",
        "player_id": "p",
        "x": "x",
        "y": "y",
        "z": "z",
        "health_percent": "h",
    }

    UNIT_FIELDS = {
        "id": "i",
        "name": "nm",
        "x": "x",
        "y": "y",
        "hp": "h",
    }

    # Unit name to type abbreviation (Layer 2 compression)
    UNIT_TYPE_MAP = {
        "ranger": "RNG", "infantry": "INF", "tank": "TNK", "medium tank": "MTK",
        "ranger general": "RGG", "quad cannon": "QC", "launcher": "LNC",
        "stealth tank": "STK", "superweapon": "SW", "comanche": "COM",
        "harrier": "HAR", "pathfinder": "PF", "humvee": "HUM", "paladin": "PAL",
        "dragon": "DRG", "overlord": "OVL", "red guard": "RG", "jarmen kell": "JK",
        "black lotus": "BL", "aurora": "AUR", "inferno": "INF", "anvil": "ANV",
    }

    def __init__(self, enable_delta: bool = True) -> None:
        self.enable_delta = enable_delta and os.getenv("STATE_DELTA_ENABLED", "1") == "1"
        self.compress_enabled = os.getenv("STATE_COMPRESSION_ENABLED", "1") == "1"
        self.previous_state: Optional[Dict] = None
        self.stats = {"frames": 0, "bytes_before": 0, "bytes_after": 0}

    def _abbreviate_unit_type(self, name: str) -> str:
        """Convert full unit name to 3-letter type code."""
        name_lower = name.lower()
        for full_name, abbrev in self.UNIT_TYPE_MAP.items():
            if full_name in name_lower:
                return abbrev
        return name[:3].upper()

    def _compress_object(self, obj: Dict) -> Dict:
        """Layer 2: Compress object structure with abbreviations."""
        pos_x = obj.get("x", 0.0)
        pos_y = obj.get("y", 0.0)
        
        compressed = {
            "i": obj.get("id", -1),
            "t": self._abbreviate_unit_type(obj.get("template_name", "?")),
            "p": obj.get("player_id", -1),
            "pos": [int(round(pos_x)), int(round(pos_y))],  # Compact integer position array
            "h": round(obj.get("health_percent", 1.0) / 100.0, 2),  # Normalize to 0-1
        }
        
        # Include Z only if non-zero
        pos_z = obj.get("z", 0.0)
        if pos_z != 0.0:
            compressed["z"] = int(round(pos_z))
        
        return compressed

    def _compress_unit(self, unit: Dict) -> Dict:
        """Layer 2: Compress unit structure."""
        return {
            "i": unit.get("id", -1),
            "t": self._abbreviate_unit_type(unit.get("name", "?")),
            "pos": [int(round(unit.get("x", 0.0))), int(round(unit.get("y", 0.0)))],
            "h": round(unit.get("hp", 100.0) / 100.0, 2),  # Normalize to 0-1
        }

    def _compress_player(self, player: Dict) -> Dict:
        """Layer 2: Compress player structure."""
        return {
            "p": player.get("player_id", -1),
            "s": player.get("side", "?")[:1].upper(),  # Single letter side
            "$": int(player.get("money", 0.0)),
        }

    def _compress_civilian_object(self, obj: Dict) -> Dict:
        """Keep only minimal civilian object info."""
        return {
            "tm": str(obj.get("team_name", "")),
            "tid": int(obj.get("template_id", -1)),
            "t": str(obj.get("template_name", "Unknown")),
            "position": str(obj.get("position", "(0,0,0)")),
        }

    def _apply_delta_encoding(self, compressed: Dict) -> Dict:
        """
        Layer 3: Delta encoding - only include fields that changed.
        For first call, returns full state. For subsequent calls, returns delta.
        """
        if not self.enable_delta or self.previous_state is None:
            self.previous_state = json.loads(json.dumps(compressed))
            return compressed

        frame_key = "f" if "f" in compressed else "frame"
        delta: Dict = {frame_key: compressed.get(frame_key)}
        
        # Compare each top-level key
        for key in compressed:
            if key == frame_key:
                continue
            
            prev_value = self.previous_state.get(key)
            curr_value = compressed.get(key)
            
            # Use JSON serialization for deep comparison
            if json.dumps(prev_value, sort_keys=True) != json.dumps(curr_value, sort_keys=True):
                delta[key] = curr_value
        
        self.previous_state = json.loads(json.dumps(compressed))
        return delta

    def compress_snapshot(self, snapshot: Dict) -> Dict:
        """
        Keep full key names/structure and optionally apply delta encoding.
        Returns original or delta-encoded snapshot.
        """
        if not self.compress_enabled:
            return snapshot

        # Reverted key reduction: keep the original snapshot schema.
        compressed = json.loads(json.dumps(snapshot))

        # Layer 3: Apply delta encoding
        result = self._apply_delta_encoding(compressed)

        # Track compression stats
        before_size = len(json.dumps(snapshot))
        after_size = len(json.dumps(result))
        self.stats["frames"] += 1
        self.stats["bytes_before"] += before_size
        self.stats["bytes_after"] += after_size

        return result

    def log_compression_stats(self) -> None:
        """Log compression efficiency metrics."""
        if self.stats["frames"] == 0:
            return

        avg_before = self.stats["bytes_before"] / self.stats["frames"]
        avg_after = self.stats["bytes_after"] / self.stats["frames"]
        reduction = ((self.stats["bytes_before"] - self.stats["bytes_after"]) / self.stats["bytes_before"]) * 100

        game_log(
            f"[COMPRESSION STATS] {self.stats['frames']} frames: "
            f"avg {avg_before:.0f}→{avg_after:.0f} bytes/frame "
            f"({reduction:.1f}% reduction)"
        )

        if self.enable_delta:
            game_log(f"  Delta encoding: enabled (first send full, then deltas)")
        if not self.compress_enabled:
            game_log(f"  Compression: DISABLED (set STATE_COMPRESSION_ENABLED=1)")


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

    Optimization:
    - Caches static command schema in system prompt (sent once)
    - Sends only dynamic game state in user messages (every tick)
    - Reduces token waste from redundant schema transmission
    """

    def __init__(self) -> None:
        # Default ON for local Ollama usage; set LOCAL_LLM_ENABLED=0 to disable.
        self.enabled = os.getenv("LOCAL_LLM_ENABLED", "1") == "1"
        self.endpoint = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions")
        self.model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5-coder:1.5b-base")  # Use a smaller model for faster responses; adjust as needed
        # Default timeout increased to 30 seconds; adjust with LOCAL_LLM_TIMEOUT env var
        self.timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "60"))
        self.temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.0"))
        self.enable_thinking = os.getenv("LOCAL_LLM_THINK", "0") == "1"
        self.llm_debug = os.getenv("LLM_DEBUG", "0") == "1"
        self.llm_log_enabled = os.getenv("LLM_INTERACTION_LOG_ENABLED", "1") == "1"
        self.llm_log_file = os.getenv("LLM_INTERACTION_LOG_FILE", "llm_interactions_log.txt")
        
        # Initialize prompt cache to avoid resending command schema every tick
        self.prompt_cache = SystemPromptCache()
        self.first_plan_call = True
        if self.llm_log_enabled:
            self._init_llm_interaction_log()

    def _init_llm_interaction_log(self) -> None:
        """Initialize LLM interaction log file for readable prompt/response tracing."""
        try:
            with open(self.llm_log_file, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 100 + "\n")
                f.write(f"LLM Interaction Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 100 + "\n")
        except Exception as exc:
            game_log(f"[LLM LOG] Failed to initialize '{self.llm_log_file}': {exc}")
            self.llm_log_enabled = False

    def _format_commands_readable(self, commands: List[Dict]) -> str:
        """Human-readable command summary for text logs."""
        if not commands:
            return "No valid commands."

        lines: List[str] = []
        for idx, cmd in enumerate(commands, 1):
            cmd_type = str(cmd.get("type", "")).strip()
            unit_ids = cmd.get("unit_ids", [])
            units_text = ",".join(str(u) for u in unit_ids) if isinstance(unit_ids, list) else "?"

            if cmd_type == "attack_object":
                target = cmd.get("target_id", "?")
                lines.append(f"{idx}. {cmd_type}: units [{units_text}] -> target {target}")
                lines.append(f"   command: {cmd_type} {units_text} {target}")
            elif cmd_type in {"select_unit", "select_units"}:
                lines.append(f"{idx}. {cmd_type}: units [{units_text}]")
                lines.append(f"   command: {cmd_type} {units_text}")
            elif cmd_type in {"construct", "build_structure", "build"}:
                template_id = cmd.get("template_id", "?")
                x = cmd.get("x", "?")
                y = cmd.get("y", "?")
                z = cmd.get("z", 0)
                lines.append(
                    f"{idx}. {cmd_type}: units [{units_text}] -> template {template_id} at ({x},{y},{z})"
                )
                lines.append(f"   command: construct {units_text} {template_id} {x} {y} {z}")
            else:
                x = cmd.get("x", "?")
                y = cmd.get("y", "?")
                z = cmd.get("z", 0)
                lines.append(f"{idx}. {cmd_type}: units [{units_text}] -> ({x},{y},{z})")
                lines.append(f"   command: {cmd_type} {units_text} {x} {y} {z}")
        return "\n".join(lines)

    def _log_llm_interaction(
        self,
        user_prompt: Dict,
        snapshot: Dict,
        sent_system_prompt: bool,
        system_prompt_text: str,
        raw_body: str,
        content: str,
        thinking_text: str,
        parsed_commands: List[Dict],
        error_text: Optional[str] = None,
    ) -> None:
        """Write one complete LLM interaction in readable text format."""
        if not self.llm_log_enabled:
            return

        frame_value = snapshot.get("f", snapshot.get("frame", "?"))
        try:
            with open(self.llm_log_file, "a", encoding="utf-8") as f:
                f.write("\n" + "-" * 100 + "\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Frame: {frame_value}\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Endpoint: {self.endpoint}\n")
                f.write(f"System Prompt Sent This Call: {sent_system_prompt}\n")

                f.write("\n[SYSTEM PROMPT SENT TO LLM]\n")
                if sent_system_prompt:
                    f.write((system_prompt_text or "(empty)") + "\n")
                else:
                    f.write("(not sent this call; prompt caching reused prior system prompt)\n")

                f.write("\n[USER PROMPT]\n")
                f.write(json.dumps(user_prompt, indent=2, ensure_ascii=False) + "\n")

                f.write("\n[STATE SNAPSHOT]\n")
                f.write(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")

                f.write("\n[LLM THINKING]\n")
                f.write((thinking_text or "(none)") + "\n")

                f.write("\n[LLM CONTENT]\n")
                f.write((content or "(none)") + "\n")

                f.write("\n[PARSED COMMANDS - READABLE]\n")
                f.write(self._format_commands_readable(parsed_commands) + "\n")

                f.write("\n[PARSED COMMANDS - JSON]\n")
                f.write(json.dumps(parsed_commands, indent=2, ensure_ascii=False) + "\n")

                if error_text:
                    f.write("\n[ERROR]\n")
                    f.write(error_text + "\n")

                f.write("\n[RAW LLM RESPONSE BODY]\n")
                f.write((raw_body or "(none)") + "\n")
        except Exception as exc:
            game_log(f"[LLM LOG] Failed to write '{self.llm_log_file}': {exc}")

    def _extract_json(self, text: str) -> Optional[Dict]:
        text = text.strip()
        if not text:
            game_log("[LLM JSON] Empty response text")
            return None

        if self.llm_debug:
            game_log(f"[LLM JSON] Attempting to extract JSON from {len(text)} chars")

        # Direct parse
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                if self.llm_debug:
                    game_log(f"[LLM JSON] Direct parse succeeded")
                return value
            if isinstance(value, list):
                if self.llm_debug:
                    game_log(f"[LLM JSON] Direct parse succeeded (top-level list)")
                return {"commands": value}
        except json.JSONDecodeError as e:
            if self.llm_debug:
                game_log(f"[LLM JSON] Direct parse failed: {e}")

        # Parse JSON block in fenced output
        if "```" in text:
            parts = text.split("```")
            for idx, part in enumerate(parts):
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                try:
                    value = json.loads(candidate)
                    if isinstance(value, dict):
                        if self.llm_debug:
                            game_log(f"[LLM JSON] Fenced block parse succeeded at part {idx}")
                        return value
                    if isinstance(value, list):
                        if self.llm_debug:
                            game_log(f"[LLM JSON] Fenced block parse succeeded as list at part {idx}")
                        return {"commands": value}
                except json.JSONDecodeError as e:
                    if self.llm_debug:
                        game_log(f"[LLM JSON] Fenced block part {idx} failed: {e}")
                    continue

        # Parse first object substring - with improved boundary detection
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            # Try to find the most complete JSON object by checking bracket balance
            open_count = 0
            best_end = -1
            
            for i in range(start, min(end + 1, len(text))):
                if text[i] == "{":
                    open_count += 1
                elif text[i] == "}":
                    open_count -= 1
                    if open_count == 0:
                        best_end = i
                        break  # Found first complete object
            
            if best_end > start:
                candidate_text = text[start : best_end + 1]
                if self.llm_debug:
                    game_log(f"[LLM JSON] Trying substring extraction: chars {start}-{best_end} ({len(candidate_text)} bytes)")
                
                try:
                    value = json.loads(candidate_text)
                    if isinstance(value, dict) and "commands" in value:
                        if self.llm_debug:
                            game_log(f"[LLM JSON] Substring parse succeeded with 'commands' key")
                        return value
                    elif isinstance(value, dict):
                        if self.llm_debug:
                            game_log(f"[LLM JSON] Substring parse succeeded but missing 'commands' key")
                except json.JSONDecodeError as e:
                    if self.llm_debug:
                        game_log(f"[LLM JSON] Substring parse failed: {e}")
                        game_log(f"[LLM JSON] Failed text: {candidate_text[:150]}...")

        # Parse first JSON array substring when model returns bare command arrays
        array_start = text.find("[")
        array_end = text.rfind("]")
        if array_start >= 0 and array_end > array_start:
            open_count = 0
            best_array_end = -1
            for i in range(array_start, min(array_end + 1, len(text))):
                if text[i] == "[":
                    open_count += 1
                elif text[i] == "]":
                    open_count -= 1
                    if open_count == 0:
                        best_array_end = i
                        break
            if best_array_end > array_start:
                array_text = text[array_start : best_array_end + 1]
                try:
                    value = json.loads(array_text)
                    if isinstance(value, list):
                        if self.llm_debug:
                            game_log(f"[LLM JSON] Array substring parse succeeded")
                        return {"commands": value}
                except json.JSONDecodeError as e:
                    if self.llm_debug:
                        game_log(f"[LLM JSON] Array substring parse failed: {e}")
        
        if self.llm_debug:
            game_log(f"[LLM JSON] All extraction methods exhausted. First 200 chars: {text[:200]}")
        return None

    def _attempt_format_repair(
        self,
        bad_content: str,
        base_system_prompt: str,
        use_native_ollama: bool,
    ) -> str:
        """Ask the model to rewrite malformed content into canonical command JSON."""
        if not bad_content.strip():
            return ""

        repair_system = (
            "You are a strict JSON reformatter for RTS commands. "
            "Return ONLY canonical JSON with this shape: "
            '{"commands":[{"type":"..."}]}. '
            "Use key 'type' only. No markdown. No explanations."
        )
        repair_user = (
            "Rewrite the following content into canonical JSON only.\n\n"
            "Rules:\n"
            "1) top-level key must be commands (array)\n"
            "2) convert action/build aliases to canonical type names\n"
            "3) if no valid command can be formed, return {\"commands\":[]}\n\n"
            f"System Prompt Context:\n{base_system_prompt}\n\n"
            f"Content to repair:\n{bad_content}"
        )

        messages = [
            {"role": "system", "content": repair_system},
            {"role": "user", "content": repair_user},
        ]

        if use_native_ollama:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.0},
                "think": False,
            }
        else:
            payload = {
                "model": self.model,
                "temperature": 0.0,
                "messages": messages,
            }

        req = urlrequest.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=min(self.timeout, 45.0)) as resp:
                repair_body = resp.read().decode("utf-8", errors="replace")
            repair_result = json.loads(repair_body)
            if use_native_ollama:
                return str(repair_result.get("message", {}).get("content", "") or "")
            return str(repair_result.get("choices", [{}])[0].get("message", {}).get("content", "") or "")
        except Exception as exc:
            if self.llm_debug:
                game_log(f"[LLM REPAIR] Failed: {exc}")
            return ""

    def plan(self, snapshot: Dict) -> List[Dict]:
        if not self.enabled:
            return []

        user_prompt = {
            "instruction": (
            "Balance economy, production, expansion, scouting, defense, "
            "army control, and combat efficiency. "
            "Prefer high-value actions that improve strategic position. "
            "Preserve important units while maintaining map control and resource income. "
            "Avoid useless, repetitive, or low-impact commands. "
            "Do not interrupt effective ongoing actions unless necessary. "
            "Prefer stable coordinated behavior over constant retargeting."
            "Choose the best RTS actions for the current game state. "
            "Return ONLY canonical JSON with top-level {'commands': [...]} and canonical key 'type'. "
            "Do not output markdown or prose. "
            "For build actions, use only type='construct' with numeric template_id from state.build_catalog. "
            "Do not guess template_id. "
            "Use short, high-impact command sequences."
            ),
            "state": snapshot,
        }

        # Use cached system prompt to avoid resending command schema every tick
        messages, sent_system_prompt = self.prompt_cache.get_messages_with_cache(
            user_prompt, first_call=self.first_plan_call
        )
        system_prompt_text = (
            str(messages[0].get("content", ""))
            if sent_system_prompt and messages and messages[0].get("role") == "system"
            else ""
        )
        if self.first_plan_call:
            self.first_plan_call = False

        use_native_ollama = "/api/chat" in self.endpoint.lower()
        if use_native_ollama:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.temperature},
                "think": self.enable_thinking,
            }
        else:
            payload = {
                "model": self.model,
                "temperature": self.temperature,
                "messages": messages,
            }

        if self.llm_debug:
            game_log(f"[LLM DEBUG] Sending request to: {self.endpoint}")
            game_log(f"[LLM DEBUG] Model: {self.model}")
            game_log(f"[LLM DEBUG] Timeout: {self.timeout}s")
            game_log(f"[LLM DEBUG] Temperature: {self.temperature}, Thinking: {self.enable_thinking}")
            game_log(f"[LLM DEBUG] System prompt sent: {sent_system_prompt} (messages: {len(messages)})")
            game_log(f"[LLM DEBUG] Payload size: {len(json.dumps(payload))} bytes")
            my_units_count = len(snapshot.get("mu", snapshot.get("my_units", [])))
            enemy_units_count = len(snapshot.get("eu", snapshot.get("enemy_units", [])))
            objects_count = len(snapshot.get("obj", snapshot.get("objects_in_prompt", [])))
            civilian_objects_count = len(snapshot.get("cv", snapshot.get("civilian_objects", [])))
            game_log(
                f"[LLM DEBUG] Snapshot - my_units: {my_units_count}, "
                f"enemy_units: {enemy_units_count}, objects: {objects_count}, "
                f"civilian_objects: {civilian_objects_count}"
            )

        req = urlrequest.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        body = ""
        content = ""
        thinking_text = ""

        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urlerror.HTTPError as http_err:
            game_log(f"Local LLM HTTP Error {http_err.code}: {http_err.reason} - Check if Ollama is running and endpoint is correct")
            game_log(f"  Endpoint: {self.endpoint}")
            game_log(f"  Model: {self.model}")
            game_log(f"  Timeout: {self.timeout}s (increase with LOCAL_LLM_TIMEOUT env var)")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"HTTP Error {http_err.code}: {http_err.reason}",
            )
            return []
        except TimeoutError as exc:
            game_log(f"Local LLM timeout ({self.timeout}s): {exc}")
            game_log(f"  The LLM is taking too long. Try:")
            game_log(f"  1. Increase timeout: set LOCAL_LLM_TIMEOUT=60")
            game_log(f"  2. Use a faster model: ollama pull mistral:7b")
            game_log(f"  3. Check Ollama: curl http://127.0.0.1:11434/api/tags")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Timeout Error: {exc}",
            )
            return []
        except (urlerror.URLError, OSError) as exc:
            game_log(f"Local LLM unavailable: {exc}")
            game_log(f"  Check if Ollama is running: ollama serve")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Connection Error: {exc}",
            )
            return []

        if self.llm_debug:
            game_log(f"[LLM RESPONSE] Raw response body ({len(body)} bytes): {body[:300]}..." if len(body) > 300 else f"[LLM RESPONSE] Raw response body: {body}")

        try:
            result = json.loads(body)
            if use_native_ollama:
                content = result["message"]["content"]
                thinking_text = str(result.get("message", {}).get("thinking", "") or result.get("thinking", ""))
            else:
                content = result["choices"][0]["message"]["content"]
                choice_msg = result.get("choices", [{}])[0].get("message", {})
                thinking_text = str(choice_msg.get("thinking", "") or result.get("thinking", ""))
            if self.llm_debug:
                game_log(f"[LLM RESPONSE] Extracted content ({len(content)} bytes): {content[:200]}..." if len(content) > 200 else f"[LLM RESPONSE] Extracted content: {content}")
                game_log(f"[LLM RESPONSE] thinking trace (if available): {thinking_text if thinking_text else 'N/A'}")
        except Exception as e:
            game_log(f"Local LLM response format unexpected: {e}")
            if self.llm_debug:
                game_log(f"[LLM RESPONSE] Failed to extract content. Full body: {body[:500]}")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Response format error: {e}",
            )
            return []

        parsed = self._extract_json(content)
        if not parsed:
            repaired_content = self._attempt_format_repair(
                bad_content=content,
                base_system_prompt=self.prompt_cache.cached_system_prompt,
                use_native_ollama=use_native_ollama,
            )
            if repaired_content:
                repaired = self._extract_json(repaired_content)
                if repaired:
                    parsed = repaired
                    content = repaired_content
                else:
                    game_log("Local LLM did not return parseable JSON commands")
                    if self.llm_debug:
                        game_log(f"[LLM RESPONSE] Content that failed JSON parsing: {content[:500]}")
                    self._log_llm_interaction(
                        user_prompt=user_prompt,
                        snapshot=snapshot,
                        sent_system_prompt=sent_system_prompt,
                        system_prompt_text=system_prompt_text,
                        raw_body=body,
                        content=content,
                        thinking_text=thinking_text,
                        parsed_commands=[],
                        error_text="Parse error: Could not extract JSON commands from content",
                    )
                    return []
            else:
                game_log("Local LLM did not return parseable JSON commands")
                if self.llm_debug:
                    game_log(f"[LLM RESPONSE] Content that failed JSON parsing: {content[:500]}")
                self._log_llm_interaction(
                    user_prompt=user_prompt,
                    snapshot=snapshot,
                    sent_system_prompt=sent_system_prompt,
                    system_prompt_text=system_prompt_text,
                    raw_body=body,
                    content=content,
                    thinking_text=thinking_text,
                    parsed_commands=[],
                    error_text="Parse error: Could not extract JSON commands from content",
                )
                return []

        # Accept flexible response formats:
        # - {"commands":[...]}
        # - {"actions":[...]}
        # - [ ...commands... ]
        # - single command object
        commands: List = []
        if isinstance(parsed, dict):
            candidate = parsed.get("commands")
            if candidate is None:
                candidate = parsed.get("actions")
            if candidate is None and any(k in parsed for k in ("type", "action", "command")):
                candidate = [parsed]
            if not isinstance(candidate, list):
                game_log(f"Local LLM commands payload is not a list, got {type(candidate).__name__}")
                self._log_llm_interaction(
                    user_prompt=user_prompt,
                    snapshot=snapshot,
                    sent_system_prompt=sent_system_prompt,
                    system_prompt_text=system_prompt_text,
                    raw_body=body,
                    content=content,
                    thinking_text=thinking_text,
                    parsed_commands=[],
                    error_text=f"Commands payload is not a list (got {type(candidate).__name__})",
                )
                return []
            commands = candidate
        elif isinstance(parsed, list):
            commands = parsed
        else:
            game_log(f"Local LLM response is unsupported type: {type(parsed).__name__}")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Unsupported parsed type: {type(parsed).__name__}",
            )
            return []
        
        if not commands:
            if self.llm_debug:
                game_log("[LLM] Empty commands list returned")

        safe_commands: List[Dict] = []
        max_commands = max(1, int(os.getenv("LLM_MAX_COMMANDS_PER_TICK", "8")))
        for cmd in commands[:max_commands]:
            if not isinstance(cmd, dict):
                continue
            normalized = dict(cmd)
            cmd_type = str(
                normalized.get("type")
                or normalized.get("action")
                or normalized.get("command")
                or ""
            ).strip().lower()
            if not cmd_type:
                continue

            normalized["type"] = cmd_type
            if "action" in normalized:
                del normalized["action"]
            if "command" in normalized:
                del normalized["command"]

            if "unit_id" in normalized and "unit_ids" not in normalized:
                unit_id = normalized.get("unit_id")
                if isinstance(unit_id, (int, float)):
                    normalized["unit_ids"] = [int(unit_id)]

            safe_commands.append(normalized)

        self._log_llm_interaction(
            user_prompt=user_prompt,
            snapshot=snapshot,
            sent_system_prompt=sent_system_prompt,
            system_prompt_text=system_prompt_text,
            raw_body=body,
            content=content,
            thinking_text=thinking_text,
            parsed_commands=safe_commands,
            error_text=None,
        )

        return safe_commands



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
