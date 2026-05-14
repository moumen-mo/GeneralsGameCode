import json
import os
import socket
import time
from datetime import datetime
from typing import Dict, List, Optional

from AI_Agent.game_logging import GameLogger, game_log, set_game_logger

# Message type values come from:
# GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h
MSG_CREATE_SELECTED_GROUP = 1001
MSG_DO_ATTACK_OBJECT = 1059
MSG_DO_MOVETO = 1068
MSG_DO_ATTACKMOVETO = 1069
MSG_DO_FORCEMOVETO = 1070
MSG_DOZER_CONSTRUCT = 1049


class GameRpcClient:
    """TCP RPC client for newline-delimited JSON protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4500, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.recv_buffer = ""
        self.connection_id = 0

        log_file = os.getenv("RPC_LOG_FILE")
        self.log_enabled = log_file is not None and log_file.strip() != ""
        self.log_file = log_file if self.log_enabled else None
        self.logger = GameLogger(self.log_file)

        if self.log_enabled:
            try:
                with open(self.log_file, "w", encoding="utf-8") as f:
                    f.write("=" * 80 + "\n")
                    f.write(
                        f"RPC Communication Log - Started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
                    f.write("=" * 80 + "\n\n")
                self.logger.log(f"RPC communication logging enabled: {self.log_file}")
            except Exception as e:
                print(f"Warning: Failed to initialize log file: {e}")
                self.log_enabled = False

        set_game_logger(self.logger)
        self.connect()

    def _log_message(self, message_type: str, content: Dict) -> None:
        if not self.log_enabled or not self.log_file:
            return

        try:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            with open(self.log_file, "a", encoding="utf-8") as f:
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
                        self._log_message("RESPONSE RECEIVED", response)
                        return response
                    except json.JSONDecodeError:
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
            {"action": "set_controlled_player", "player_index": int(player_index)},
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
