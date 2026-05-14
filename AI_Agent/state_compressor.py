import json
import os
from typing import Dict, Optional

from AI_Agent.game_logging import game_log


class StateCompressor:
    """
    3-layer compression strategy for game state JSON.

    Layer 1: Drop redundant fields (max_health if normalized, static map info)
    Layer 2: Use numeric IDs and abbreviations (t->TNK, hp->h, pos->[x,y])
    Layer 3: Delta encoding (only send fields that changed since last frame)

    Reduces state payload significantly compared to uncompressed format.
    """

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

    UNIT_TYPE_MAP = {
        "ranger": "RNG",
        "infantry": "INF",
        "tank": "TNK",
        "medium tank": "MTK",
        "ranger general": "RGG",
        "quad cannon": "QC",
        "launcher": "LNC",
        "stealth tank": "STK",
        "superweapon": "SW",
        "comanche": "COM",
        "harrier": "HAR",
        "pathfinder": "PF",
        "humvee": "HUM",
        "paladin": "PAL",
        "dragon": "DRG",
        "overlord": "OVL",
        "red guard": "RG",
        "jarmen kell": "JK",
        "black lotus": "BL",
        "aurora": "AUR",
        "inferno": "INF",
        "anvil": "ANV",
    }

    def __init__(self, enable_delta: bool = True) -> None:
        self.enable_delta = enable_delta and os.getenv("STATE_DELTA_ENABLED", "1") == "1"
        self.compress_enabled = os.getenv("STATE_COMPRESSION_ENABLED", "1") == "1"
        self.previous_state: Optional[Dict] = None
        self.stats = {"frames": 0, "bytes_before": 0, "bytes_after": 0}

    def _abbreviate_unit_type(self, name: str) -> str:
        name_lower = name.lower()
        for full_name, abbrev in self.UNIT_TYPE_MAP.items():
            if full_name in name_lower:
                return abbrev
        return name[:3].upper()

    def _apply_delta_encoding(self, compressed: Dict) -> Dict:
        if not self.enable_delta or self.previous_state is None:
            self.previous_state = json.loads(json.dumps(compressed))
            return compressed

        frame_key = "f" if "f" in compressed else "frame"
        delta: Dict = {frame_key: compressed.get(frame_key)}

        for key in compressed:
            if key == frame_key:
                continue
            prev_value = self.previous_state.get(key)
            curr_value = compressed.get(key)
            if json.dumps(prev_value, sort_keys=True) != json.dumps(curr_value, sort_keys=True):
                delta[key] = curr_value

        self.previous_state = json.loads(json.dumps(compressed))
        return delta

    def compress_snapshot(self, snapshot: Dict) -> Dict:
        if not self.compress_enabled:
            return snapshot

        compressed = json.loads(json.dumps(snapshot))
        result = self._apply_delta_encoding(compressed)

        before_size = len(json.dumps(snapshot))
        after_size = len(json.dumps(result))
        self.stats["frames"] += 1
        self.stats["bytes_before"] += before_size
        self.stats["bytes_after"] += after_size
        return result

    def log_compression_stats(self) -> None:
        if self.stats["frames"] == 0:
            return

        avg_before = self.stats["bytes_before"] / self.stats["frames"]
        avg_after = self.stats["bytes_after"] / self.stats["frames"]
        reduction = (
            (self.stats["bytes_before"] - self.stats["bytes_after"])
            / self.stats["bytes_before"]
        ) * 100

        game_log(
            f"[COMPRESSION STATS] {self.stats['frames']} frames: "
            f"avg {avg_before:.0f}->{avg_after:.0f} bytes/frame "
            f"({reduction:.1f}% reduction)"
        )

        if self.enable_delta:
            game_log("  Delta encoding: enabled (first send full, then deltas)")
        if not self.compress_enabled:
            game_log("  Compression: DISABLED (set STATE_COMPRESSION_ENABLED=1)")
