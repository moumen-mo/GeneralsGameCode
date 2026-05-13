import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple


def _get_agent_module() -> Any:
    import AI_Agent.ai_agent as agent
    return agent


class LocalAiController:
    def __init__(self, client: Any):
        self.client = client
        agent = _get_agent_module()
        self._agent = agent
        self.game_log = agent.game_log
        self.IGNORE_PLAYER_SIDES = agent.IGNORE_PLAYER_SIDES
        self.DEFAULT_COMMAND_LIBRARY_PATH = agent.DEFAULT_COMMAND_LIBRARY_PATH
        self._load_command_library = agent._load_command_library
        self.Player = agent.Player
        self.Unit = agent.Unit
        self.Position = agent.Position

        self.planner = agent.LocalLlmPlanner()
        self.state_compressor = agent.StateCompressor()  # Initialize state compression (3-layer)
        self.frame_count = 0
        self.decision_interval = int(os.getenv("DECISION_INTERVAL_FRAMES", "12"))
        self.max_frames = int(os.getenv("MAX_FRAMES", "10000"))
        self.sleep_seconds = float(os.getenv("AI_LOOP_SLEEP", "0.12"))
        self.llm_object_limit = int(os.getenv("LLM_STATE_OBJECT_LIMIT", "140"))
        self.llm_civilian_object_limit = int(os.getenv("LLM_CIVILIAN_OBJECT_LIMIT", "40"))
        self.llm_debug = os.getenv("LLM_DEBUG", "0") == "1"
        self.use_semantic_analysis = os.getenv("USE_SEMANTIC_ANALYSIS", "1") == "1"
        self.template_name_to_id: Dict[str, int] = {}
        self.static_template_name_to_id: Dict[str, int] = {}
        self.static_template_catalog: List[Dict] = []
        self.command_message_type_by_name: Dict[str, int] = {}
        self._load_static_template_map()
        self._load_command_message_types()

        my_player_env = os.getenv("MY_PLAYER_ID")
        self.my_player_id = int(my_player_env) if my_player_env is not None else None
        self.rpc_controlled_player_id: Optional[int] = None
        self.rpc_controlled_player_connection_id: Optional[int] = None
    def _preprocess_state(self, state: Dict[str, Any]) -> None:
        """
        Preprocess the raw state from RPC server to minimize information.
        Keep only SupplyDock and TechOilDerrick objects, and create summarized arrays.
        """
        capturable_techs: List[Dict[str, Any]] = []
        resource_locations: List[Dict[str, Any]] = []
        filtered_objects: List[Dict[str, Any]] = []

        for obj in state.get("objects", []):
            template_name = str(obj.get("template_name", ""))
            if template_name == "TechOilDerrick":
                pos = obj.get("position", {})
                capturable_techs.append({
                    "type": "TechOilDerrick",
                    "x": float(pos.get("x", 0.0)),
                    "y": float(pos.get("y", 0.0)),
                    "z": float(pos.get("z", 0.0))
                })
                filtered_objects.append(obj)
            elif template_name == "SupplyDock":
                pos = obj.get("position", {})
                resource_locations.append({
                    "type": "SupplyDock",
                    "x": float(pos.get("x", 0.0)),
                    "y": float(pos.get("y", 0.0)),
                    "z": float(pos.get("z", 0.0))
                })
                filtered_objects.append(obj)
            # Remove other objects (birds, rocks, etc.)

        state["capturable_techs"] = capturable_techs
        state["resource_locations"] = resource_locations
        state["objects"] = filtered_objects
    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _round_coord(value: float) -> int:
        """Round world coordinate to nearest integer."""
        return int(round(float(value)))

    @staticmethod
    def _norm_template_key(name: str) -> str:
        return "".join(ch for ch in str(name).lower() if ch.isalnum())

    def _load_static_template_map(self) -> None:
        """
        Optional static mapping for build commands that return structure names.
        Env var format:
        BUILD_TEMPLATE_MAP_JSON={"AmericaPowerPlant":1234,"AmericaBarracks":1235}
        """
        raw = os.getenv("BUILD_TEMPLATE_MAP_JSON", "").strip()
        if not raw:
            return
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                mapped: Dict[str, int] = {}
                catalog: List[Dict] = []
                for key, value in payload.items():
                    if isinstance(value, (int, float)):
                        key_str = str(key)
                        value_int = int(value)
                        mapped[self._norm_template_key(key_str)] = value_int
                        catalog.append(
                            {
                                "structure_type": key_str,
                                "template_id": value_int,
                                "builder": "AmericaVehicleDozer",
                            }
                        )
                self.static_template_name_to_id = mapped
                self.static_template_catalog = catalog
                self.game_log(f"[BUILD MAP] Loaded {len(mapped)} static template mappings from BUILD_TEMPLATE_MAP_JSON")
        except Exception as exc:
            self.game_log(f"[BUILD MAP] Failed to parse BUILD_TEMPLATE_MAP_JSON: {exc}")

    def _load_command_message_types(self) -> None:
        """Load command name -> message_type index from Commands_Library.json."""
        path = os.getenv("COMMAND_LIBRARY_PATH", self.DEFAULT_COMMAND_LIBRARY_PATH)
        entries = self._load_command_library(path)
        index: Dict[str, int] = {}
        for entry in entries:
            command_name = str(entry.get("command", "")).strip().lower()
            message_type = entry.get("message_type")
            if command_name and isinstance(message_type, (int, float)):
                index[command_name] = int(message_type)
        self.command_message_type_by_name = index
        if self.llm_debug:
            self.game_log(f"[COMMAND LIB] Loaded {len(index)} command message_type entries")

    def _resolve_template_id(self, cmd: Dict) -> Optional[int]:
        """Resolve build template id from command payload."""
        template_id = cmd.get("template_id")
        if isinstance(template_id, (int, float)):
            return int(template_id)

        for key in ("structure_type", "template_name", "structure", "build", "building_type"):
            value = cmd.get(key)
            if not value:
                continue
            norm = self._norm_template_key(str(value))
            if norm in self.template_name_to_id:
                return int(self.template_name_to_id[norm])
            if norm in self.static_template_name_to_id:
                return int(self.static_template_name_to_id[norm])

        return None

    @staticmethod
    def _extract_xy_from_cmd(cmd: Dict) -> Tuple[Optional[float], Optional[float], float]:
        """Extract x/y/z from either explicit fields or location array/object."""
        x = cmd.get("x")
        y = cmd.get("y")
        z_raw = cmd.get("z", 0.0)

        location = cmd.get("location")
        if (not isinstance(x, (int, float)) or not isinstance(y, (int, float))) and location is not None:
            if isinstance(location, list) and len(location) >= 2:
                x = location[0]
                y = location[1]
                if len(location) >= 3:
                    z_raw = location[2]
            elif isinstance(location, dict):
                x = location.get("x")
                y = location.get("y")
                z_raw = location.get("z", z_raw)

        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None, None, 0.0
        z = float(z_raw) if isinstance(z_raw, (int, float)) else 0.0
        return float(x), float(y), z

    def _build_generic_rpc_arguments(self, cmd: Dict) -> List[Dict]:
        """
        Best-effort argument builder for generic create_game_message execution.
        Priority:
        1) explicit 'arguments' list from model
        2) infer from common fields (target_id/object_id or x/y/z)
        """
        explicit_args = cmd.get("arguments")
        if isinstance(explicit_args, list):
            return explicit_args

        if isinstance(cmd.get("target_id"), (int, float)):
            return [{"type": "integer", "value": int(cmd["target_id"])}]
        if isinstance(cmd.get("object_id"), (int, float)):
            return [{"type": "integer", "value": int(cmd["object_id"])}]
        if isinstance(cmd.get("x"), (int, float)) and isinstance(cmd.get("y"), (int, float)):
            return [
                {
                    "type": "location",
                    "x": float(cmd["x"]),
                    "y": float(cmd["y"]),
                    "z": float(cmd.get("z", 0.0)) if isinstance(cmd.get("z", 0.0), (int, float)) else 0.0,
                }
            ]
        return []

    def _to_players(self, state: Dict) -> List[Any]:
        out: List[Any] = []
        for p in state.get("players", []):
            out.append(
                self.Player(
                    id=int(p.get("player_id", -1)),
                    side=str(p.get("side", "")),
                    money=float(p.get("money", 0.0)),
                )
            )
        return out

    def _to_units(self, state: Dict) -> List[Any]:
        out: List[Any] = []
        for obj in state.get("objects", []):
            pos = obj.get("position", {}) or {}
            out.append(
                self.Unit(
                    id=int(obj.get("id", -1)),
                    name=str(obj.get("template_name", "Unknown")),
                    position=self.Position(
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

    def _infer_unit_role(self, name: str) -> str:
        n = str(name).lower()
        if any(key in n for key in ("dozer", "worker", "collector", "mule", "engineer", "harvester")):
            return "worker"
        if any(key in n for key in ("supply", "depot", "tent", "center", "commandcenter", "hospital", "palace", "reactor", "power", "airfield", "barracks", "warfactory", "tower", "bunker", "scaffold")):
            return "structure"
        if any(key in n for key in ("harrier", "comanche", "apache", "ironclad", "aircraft", "rocketplane", "cyborg")):
            return "air"
        if any(key in n for key in ("patriot", "quad", "aaa", "rocket", "launcher", "stinger", "missile", "inferno")):
            return "anti_air"
        if any(key in n for key in ("tank", "crusader", "paladin", "anvil", "overlord", "vindicator", "scorpion", "mammoth", "juggernaut", "raider", "humvee", "jeep", "pathfinder", "ranger", "grenadier", "redguard", "jarmen", "kell")):
            return "frontline_tank"
        if any(key in n for key in ("rocket", "artillery", "howitzer", "launcher", "longbow")):
            return "artillery"
        if any(key in n for key in ("engineer", "spy", "cyborg", "saboteur", "medic")):
            return "support"
        return "unknown"

    def _infer_threat_type(self, role: str) -> str:
        if role in ("air", "anti_air"):
            return "air"
        if role in ("frontline_tank", "artillery", "support"):
            return "ground"
        return "support"

    def _estimate_army_strength(self, units: List[Any]) -> float:
        total = 0.0
        for u in units:
            role = self._infer_unit_role(u.name)
            weight = 1.0
            if role == "worker":
                weight = 0.15
            elif role == "anti_air":
                weight = 0.9
            elif role == "air":
                weight = 1.1
            elif role == "frontline_tank":
                weight = 1.2
            elif role == "artillery":
                weight = 1.0
            elif role == "support":
                weight = 0.7
            total += weight * (u.health_percent / 100.0)
        return self._clamp(total / 20.0, 0.0, 1.0)

    def _build_map_control(self, my_units: List[Any], enemy_units: List[Any], map_height: float) -> Dict[str, str]:
        zones = {"north": 0, "center": 0, "south": 0}
        enemy_zones = {"north": 0, "center": 0, "south": 0}
        for u in my_units:
            if u.position.y < map_height * 0.33:
                zones["north"] += 1
            elif u.position.y < map_height * 0.66:
                zones["center"] += 1
            else:
                zones["south"] += 1
        for u in enemy_units:
            if u.position.y < map_height * 0.33:
                enemy_zones["north"] += 1
            elif u.position.y < map_height * 0.66:
                enemy_zones["center"] += 1
            else:
                enemy_zones["south"] += 1

        control: Dict[str, str] = {}
        for region in ("north", "center", "south"):
            if zones[region] > enemy_zones[region] * 1.3:
                control[region] = "friendly"
            elif enemy_zones[region] > zones[region] * 1.3:
                control[region] = "enemy"
            elif zones[region] or enemy_zones[region]:
                control[region] = "contested"
            else:
                control[region] = "neutral"
        return control

    def _build_expansion_candidates(self, state: Dict, my_units: List[Any], enemy_units: List[Any], map_width: float, map_height: float) -> List[Dict]:
        candidates: List[Dict] = []
        points = [
            (map_width * 0.5, map_height * 0.15, "north"),
            (map_width * 0.5, map_height * 0.85, "south"),
            (map_width * 0.85, map_height * 0.5, "east"),
        ]
        max_dist = max(map_width, map_height)
        for x, y, region in points:
            closest_enemy = min(
                [self.Position(x=u.position.x, y=u.position.y).distance_to(self.Position(x=x, y=y)) for u in enemy_units] or [max_dist]
            )
            closest_friendly = min(
                [self.Position(x=u.position.x, y=u.position.y).distance_to(self.Position(x=x, y=y)) for u in my_units] or [max_dist]
            )
            distance_score = round(1.0 - min(closest_friendly, closest_enemy) / max_dist, 2)
            safe = closest_enemy > 4000.0
            resource_value = round(0.4 + (0.4 if safe else 0.0) + (0.2 if closest_friendly < closest_enemy else 0.0), 2)
            candidates.append(
                {
                    "region": region,
                    "location": [int(round(x)), int(round(y))],
                    "safe": safe,
                    "distance_score": self._clamp(distance_score, 0.0, 1.0),
                    "resource_value": self._clamp(resource_value, 0.0, 1.0),
                    "enemy_distance": int(round(closest_enemy)),
                    "friendly_distance": int(round(closest_friendly)),
                }
            )
        return candidates

    def _build_semantic_analysis(self, state: Dict, my_id: int, my_units: List[Any], enemy_units: List[Any]) -> Dict:
        players = {p.id: p for p in self._to_players(state)}
        my_money = players.get(my_id, self.Player(id=my_id, side="", money=0.0)).money
        worker_units = [u for u in my_units if self._infer_unit_role(u.name) == "worker"]
        total_workers = len(worker_units)
        supply_buildings = 0
        structure_units = 0
        for obj in state.get("objects", []):
            if int(obj.get("player_id", -1)) != my_id:
                continue
            name = str(obj.get("template_name", "")).lower()
            if any(key in name for key in ("supply", "depot", "tent", "recycler", "storehouse")):
                supply_buildings += 1
            if any(key in name for key in ("commandcenter", "center", "palace", "reactor", "airfield", "barracks", "warfactory", "power", "tower", "bunker")):
                structure_units += 1

        idle_worker_count = len(worker_units)
        resource_collection_efficiency = 1.0
        if total_workers > 0:
            resource_collection_efficiency = round(max(0.0, 1.0 - (idle_worker_count / float(total_workers))), 2)

        strong_money = my_money >= 9000
        income_level = "low"
        if my_money >= 6000:
            income_level = "high"
        elif my_money >= 2500:
            income_level = "medium"

        friendly_strength = self._estimate_army_strength(my_units)
        enemy_strength = self._estimate_army_strength(enemy_units)
        win_probability = round(
            friendly_strength / max(0.001, friendly_strength + enemy_strength),
            2,
        )
        role_counts: Dict[str, int] = {}
        for u in my_units:
            role = self._infer_unit_role(u.name)
            role_counts[role] = role_counts.get(role, 0) + 1
        enemy_role_counts: Dict[str, int] = {}
        for u in enemy_units:
            role = self._infer_unit_role(u.name)
            enemy_role_counts[role] = enemy_role_counts.get(role, 0) + 1

        enemy_rush_detected = False
        if enemy_units and friendly_strength > 0.0:
            distances: List[float] = []
            for eu in enemy_units:
                closest_my = min([eu.position.distance_to(mu.position) for mu in my_units] or [9999])
                distances.append(closest_my)
            if len(distances) >= 4 and sum(distances) / len(distances) < 450.0 and len(enemy_units) >= 6:
                enemy_rush_detected = True

        base_under_attack = False
        for eu in enemy_units:
            for u in my_units:
                if eu.position.distance_to(u.position) < 220.0:
                    base_under_attack = True
                    break
            if base_under_attack:
                break

        can_expand_safely = enemy_strength < friendly_strength * 0.7 and not base_under_attack
        map_control = self._build_map_control(my_units, enemy_units, float(state.get("map_height", 0.0)))
        expansions = self._build_expansion_candidates(
            state,
            my_units,
            enemy_units,
            float(state.get("map_width", 0.0)),
            float(state.get("map_height", 0.0)),
        )

        local_battles: List[Dict[str, Any]] = []
        if map_control.get("center") == "contested" or (len(my_units) >= 2 and len(enemy_units) >= 2):
            local_battles.append(
                {
                    "location": [
                        int(round(float(state.get("map_width", 0.0)) * 0.5)),
                        int(round(float(state.get("map_height", 0.0)) * 0.5)),
                    ],
                    "friendly_strength": friendly_strength,
                    "enemy_strength": enemy_strength,
                    "win_probability": win_probability,
                }
            )

        return {
            "economy": {
                "income_level": income_level,
                "money": my_money,
                "idle_worker_count": idle_worker_count,
                "supply_buildings": supply_buildings,
                "structure_count": structure_units,
                "floating_resources": my_money > 5000 and idle_worker_count > 0,
                "resource_collection_efficiency": resource_collection_efficiency,
            },
            "military": {
                "friendly_strength": friendly_strength,
                "enemy_strength": enemy_strength,
                "win_probability": win_probability,
                "anti_air": any(role == "anti_air" for role in role_counts),
                "enemy_air_threat": any(role == "air" for role in enemy_role_counts),
                "unit_counts": role_counts,
                "enemy_unit_counts": enemy_role_counts,
            },
            "situations": {
                "enemy_rush_detected": enemy_rush_detected,
                "base_under_attack": base_under_attack,
                "can_expand_safely": can_expand_safely,
                "has_high_money": strong_money,
            },
            "map_control": map_control,
            "local_battles": local_battles,
            "expansions": expansions,
        }

    def _detect_player_id(self, players: List[Any], units: List[Any]) -> int:
        if self.my_player_id is not None:
            return self.my_player_id

        unit_counts: Dict[int, int] = {}
        for u in units:
            if u.player_id >= 0:
                unit_counts[u.player_id] = unit_counts.get(u.player_id, 0) + 1

        candidates: List[Any] = []
        for p in players:
            if p.side.lower() in self.IGNORE_PLAYER_SIDES:
                continue
            candidates.append(p)

        if candidates:
            candidates.sort(key=lambda p: p.id)
            with_units = [p for p in candidates if unit_counts.get(p.id, 0) > 0]
            self.my_player_id = (with_units[0] if with_units else candidates[0]).id
            self.game_log(f"Using player_id={self.my_player_id} ({next((p.side for p in players if p.id == self.my_player_id), 'unknown')})")
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
        self.game_log(f"RPC controlled player set to {player_id}")

    def _split_for_decision(self, players: List[Any], units: List[Any]) -> Dict[str, Any]:
        my_id = self._detect_player_id(players, units)

        my_units = [u for u in units if u.player_id == my_id and u.health > 0 and not u.is_building_like]

        enemy_player_ids = {
            p.id for p in players if p.id != my_id and p.side.lower() not in self.IGNORE_PLAYER_SIDES
        }
        enemy_units = [u for u in units if u.player_id in enemy_player_ids and u.health > 0 and not u.is_building_like]

        return {
            "my_player_id": my_id,
            "my_units": my_units,
            "enemy_units": enemy_units,
        }

    def _build_llm_snapshot(self, state: Dict, my_id: int, my_units: List[Any], enemy_units: List[Any]) -> Dict[str, Any]:
        # Refresh template lookup map from live world objects (best-effort).
        template_map: Dict[str, int] = {}
        observed_america_build_catalog: List[Dict] = []
        for obj in state.get("objects", []):
            tname = obj.get("template_name")
            tid = obj.get("template_id")
            if tname and isinstance(tid, (int, float)):
                tname_str = str(tname)
                tid_int = int(tid)
                template_map[self._norm_template_key(tname_str)] = tid_int
                if tname_str.lower().startswith("america") and any(
                    key in tname_str.lower()
                    for key in ("power", "barracks", "supply", "warfactory", "airfield", "center", "patriot")
                ):
                    observed_america_build_catalog.append(
                        {
                            "structure_type": tname_str,
                            "template_id": tid_int,
                            "builder": "AmericaVehicleDozer",
                        }
                    )
        self.template_name_to_id = template_map

        players_payload: List[Dict[str, Any]] = []
        civilian_player_ids = set()
        for p in state.get("players", [])[:16]:
            side = str(p.get("side", "")).lower()
            player_id = int(p.get("player_id", -1))

            if side in self.IGNORE_PLAYER_SIDES:
                civilian_player_ids.add(player_id)
                continue

            players_payload.append(
                {
                    "player_id": player_id,
                    "side": side,
                    "money": float(p.get("money", 0.0)),
                }
            )

        objects_payload: List[Dict[str, Any]] = []
        civilian_objects_payload: List[Dict[str, Any]] = []
        objects = state.get("objects", [])
        for obj in objects:
            obj_player_id = int(obj.get("player_id", -1))

            if obj_player_id in civilian_player_ids:
                if len(civilian_objects_payload) < self.llm_civilian_object_limit:
                    pos = obj.get("position", {}) or {}
                    x = self._round_coord(pos.get("x", 0.0))
                    y = self._round_coord(pos.get("y", 0.0))
                    z = self._round_coord(pos.get("z", 0.0))
                    civilian_objects_payload.append(
                        {
                            "team_name": str(obj.get("team_name", "")),
                            "template_id": int(obj.get("template_id", -1)),
                            "template_name": str(obj.get("template_name", "Unknown")),
                            "position": f"({x},{y},{z})",
                        }
                    )
                continue

            if len(objects_payload) >= self.llm_object_limit:
                continue

            pos = obj.get("position", {}) or {}
            object_name = str(obj.get("template_name", "Unknown"))
            role = self._infer_unit_role(object_name)
            threat_type = self._infer_threat_type(role)
            objects_payload.append(
                {
                    "id": int(obj.get("id", -1)),
                    "template_name": object_name,
                    "player_id": obj_player_id,
                    "x": self._round_coord(pos.get("x", 0.0)),
                    "y": self._round_coord(pos.get("y", 0.0)),
                    "z": self._round_coord(pos.get("z", 0.0)),
                    "health_percent": float(obj.get("health_percent", 100.0)),
                    "is_selected": bool(obj.get("is_selected", False)),
                    "role": role,
                    "threat_type": threat_type,
                }
            )

        snapshot: Dict[str, Any] = {
            "frame": int(float(state.get("frame", self.frame_count))),
            "map_width": float(state.get("map_width", 0.0)),
            "map_height": float(state.get("map_height", 0.0)),
            "my_player_id": my_id,
            "players": players_payload,
            "object_count_total": int(state.get("object_count", len(objects))),
            "objects_in_prompt": objects_payload,
            "civilian_objects": civilian_objects_payload,
            "my_units": [
                {
                    "id": u.id,
                    "name": u.name,
                    "x": self._round_coord(u.position.x),
                    "y": self._round_coord(u.position.y),
                    "hp": round(u.health_percent, 1),
                    "role": self._infer_unit_role(u.name),
                    "threat_type": self._infer_threat_type(self._infer_unit_role(u.name)),
                }
                for u in my_units[:40]
            ],
            "enemy_units": [
                {
                    "id": u.id,
                    "name": u.name,
                    "x": self._round_coord(u.position.x),
                    "y": self._round_coord(u.position.y),
                    "hp": round(u.health_percent, 1),
                    "role": self._infer_unit_role(u.name),
                    "threat_type": self._infer_threat_type(self._infer_unit_role(u.name)),
                }
                for u in enemy_units[:40]
            ],
        }

        if self.use_semantic_analysis:
            snapshot["analysis"] = self._build_semantic_analysis(state, my_id, my_units, enemy_units)

        selected_obj = next((obj for obj in objects_payload if obj.get("is_selected")), None)
        builder_unit_ids = [
            u.id for u in my_units
            if "dozer" in u.name.lower() or "worker" in u.name.lower() or "constructor" in u.name.lower()
        ]
        build_catalog: List[Dict[str, Any]] = list(self.static_template_catalog)
        seen_ids = {entry["template_id"] for entry in build_catalog}
        for entry in observed_america_build_catalog:
            if entry["template_id"] not in seen_ids:
                build_catalog.append(entry)
                seen_ids.add(entry["template_id"])

        snapshot["selected_object_id"] = selected_obj.get("id") if selected_obj else None
        snapshot["selected_template_name"] = selected_obj.get("template_name") if selected_obj else None
        snapshot["builder_unit_ids"] = builder_unit_ids
        snapshot["can_construct_now"] = bool(builder_unit_ids)
        snapshot["build_catalog"] = build_catalog
        snapshot["build_catalog_note"] = (
            "Use only template_id values from build_catalog for construct commands. Never guess template IDs."
        )
        snapshot["capturable_techs"] = state.get("capturable_techs", [])
        snapshot["resource_locations"] = state.get("resource_locations", [])
        return snapshot

    def _sanitize_llm_commands(
        self,
        commands: List[Dict],
        my_units: List[Any],
        enemy_units: List[Any],
        map_width: float,
        map_height: float,
    ) -> List[Dict]:
        if not commands:
            return []

        my_ids = {u.id for u in my_units}
        enemy_ids = {u.id for u in enemy_units}
        fallback_squad = [u.id for u in my_units[:8]]

        sanitized: List[Dict] = []
        max_commands = max(1, int(os.getenv("LLM_MAX_COMMANDS_PER_TICK", "8")))
        for cmd in commands[:max_commands]:
            if not isinstance(cmd, dict):
                continue

            cmd_type = str(cmd.get("type", "")).strip().lower()
            if not cmd_type:
                continue
            normalized: Dict[str, Any] = {"type": cmd_type}

            unit_ids: List[int] = []
            unit_ids_raw = cmd.get("unit_ids", [])
            if isinstance(unit_ids_raw, list):
                for v in unit_ids_raw:
                    if isinstance(v, (int, float)) and int(v) in my_ids:
                        unit_ids.append(int(v))
            unit_id_single = cmd.get("unit_id")
            if isinstance(unit_id_single, (int, float)) and int(unit_id_single) in my_ids:
                unit_ids = [int(unit_id_single)]
            if unit_ids:
                normalized["unit_ids"] = unit_ids

            if cmd_type in {"select_unit", "select_units"}:
                if not unit_ids and fallback_squad:
                    normalized["unit_ids"] = [fallback_squad[0]]
                if "unit_ids" in normalized:
                    sanitized.append(normalized)
                continue

            if cmd_type in {"attack_object"}:
                target_id = cmd.get("target_id")
                if not isinstance(target_id, (int, float)):
                    continue
                target_id_int = int(target_id)
                if enemy_ids and target_id_int not in enemy_ids:
                    continue
                if "unit_ids" not in normalized and fallback_squad:
                    normalized["unit_ids"] = fallback_squad
                normalized["target_id"] = target_id_int
                sanitized.append(normalized)
                continue

            if cmd_type in {"attack_move", "move", "force_move"}:
                x, y, z = self._extract_xy_from_cmd(cmd)
                if x is None or y is None:
                    continue
                if "unit_ids" not in normalized and fallback_squad:
                    normalized["unit_ids"] = fallback_squad
                normalized["x"] = self._clamp(float(x), 0.0, map_width)
                normalized["y"] = self._clamp(float(y), 0.0, map_height)
                normalized["z"] = float(z)
                sanitized.append(normalized)
                continue

            if cmd_type in {"construct", "build_structure", "build", "build_building"}:
                x, y, z = self._extract_xy_from_cmd(cmd)
                if x is None or y is None:
                    continue
                template_id = self._resolve_template_id(cmd)
                if template_id is None:
                    self.game_log(f"[LLM] Could not resolve template_id for build command: {cmd}")
                    continue
                if "unit_ids" not in normalized and fallback_squad:
                    normalized["unit_ids"] = [fallback_squad[0]]
                normalized["template_id"] = int(template_id)
                normalized["x"] = self._clamp(float(x), 0.0, map_width)
                normalized["y"] = self._clamp(float(y), 0.0, map_height)
                normalized["z"] = float(z)
                normalized["type"] = "construct"
                sanitized.append(normalized)
                continue

            for key, value in cmd.items():
                if key not in normalized:
                    normalized[key] = value
            sanitized.append(normalized)

        return sanitized

    def _nearest_enemy(self, unit: Any, enemies: List[Any]) -> Optional[Any]:
        if not enemies:
            return None
        return min(enemies, key=lambda e: unit.position.distance_to(e.position))

    def _fallback_commands(self, my_units: List[Any], enemy_units: List[Any]) -> List[Dict]:
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
        max_commands = max(1, int(os.getenv("LLM_MAX_COMMANDS_PER_TICK", "8")))
        for cmd in commands[:max_commands]:
            unit_ids = [int(i) for i in cmd.get("unit_ids", []) if isinstance(i, int)]
            cmd_type = str(cmd.get("type", "")).strip().lower()

            if cmd_type in {"select_unit", "select_units"}:
                if unit_ids:
                    self.client.select_objects(unit_ids, create_new=True)
                continue

            if unit_ids:
                self.client.select_objects(unit_ids, create_new=True)

            if cmd_type == "attack_object":
                self.client.attack_object(int(cmd["target_id"]))
            elif cmd_type == "attack_move":
                self.client.attack_move_to(float(cmd["x"]), float(cmd["y"]), float(cmd.get("z", 0.0)))
            elif cmd_type == "move":
                self.client.move_to(float(cmd["x"]), float(cmd["y"]), float(cmd.get("z", 0.0)))
            elif cmd_type == "force_move":
                self.client.force_move_to(float(cmd["x"]), float(cmd["y"]), float(cmd.get("z", 0.0)))
            elif cmd_type in {"construct", "build_structure", "build"}:
                self.client.construct(
                    int(cmd["template_id"]),
                    float(cmd["x"]),
                    float(cmd["y"]),
                    float(cmd.get("z", 0.0)),
                )
            else:
                message_type = self.command_message_type_by_name.get(cmd_type)
                if message_type is None:
                    self.game_log(f"[LLM] Unsupported command type '{cmd_type}', skipping: {cmd}")
                    continue
                args = self._build_generic_rpc_arguments(cmd)
                self.client.create_game_message(message_type, args)

    def run(self) -> None:
        self.game_log("Starting AI loop")
        self.game_log(f"Decision interval: {self.decision_interval} frames")
        if self.planner.enabled:
            self.game_log(f"Local LLM planner enabled: model={self.planner.model}")
            self.game_log(f"Local LLM endpoint: {self.planner.endpoint}")
            self.game_log(f"LLM state object limit: {self.llm_object_limit}")
            if self.planner.prompt_cache.use_cache:
                self.game_log("[OPTIMIZATION] System prompt caching enabled - command schema sent once")
            else:
                self.game_log("[INFO] System prompt caching disabled (set PROMPT_CACHE_ENABLED=1 to enable)")
        else:
            self.game_log("Local LLM planner disabled (set LOCAL_LLM_ENABLED=1 to enable)")

        if self.state_compressor.compress_enabled:
            self.game_log("[OPTIMIZATION] State processing enabled - full schema kept")
            if self.state_compressor.enable_delta:
                self.game_log("  └─ Delta encoding: enabled (only changed fields sent after first frame)")
            else:
                self.game_log("  └─ Delta encoding: disabled (set STATE_DELTA_ENABLED=1 to enable)")
        else:
            self.game_log("[INFO] State compression disabled (set STATE_COMPRESSION_ENABLED=1 to enable)")

        try:
            while self.frame_count < self.max_frames:
                try:
                    state = self.client.get_state()
                    self._preprocess_state(state)
                except Exception as exc:
                    self.game_log(f"RPC state fetch failed: {exc}")
                    time.sleep(0.4)
                    continue

                if state.get("status") != "ok":
                    self.game_log(f"State error: {state}")
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
                    self.game_log(f"Failed to set controlled player: {exc}")
                    time.sleep(0.4)
                    continue

                if frame % self.decision_interval == 0:
                    snapshot = self._build_llm_snapshot(state, my_id, my_units, enemy_units)

                    snapshot = self.state_compressor.compress_snapshot(snapshot)

                    if self.llm_debug:
                        self.game_log(
                            f"[Frame {frame}] Compressed snapshot keys: {list(snapshot.keys())}"
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
                        self.game_log("warning: LLM returned no valid commands, using fallback behavior")

                    if commands:
                        try:
                            self._execute_commands(commands)
                            self.game_log(f"[Frame {frame}] Commands: {commands}")
                        except Exception as exc:
                            self.game_log(f"[Frame {frame}] Command execution failed: {exc}")
                    else:
                        self.game_log(
                            f"[Frame {frame}] No commands (my_units={len(my_units)}, enemy_units={len(enemy_units)}, my_player={my_id})"
                        )

                time.sleep(self.sleep_seconds)
        finally:
            if self.planner.enabled and self.planner.prompt_cache.use_cache:
                self.planner.prompt_cache.log_cache_stats()
            if self.state_compressor.compress_enabled:
                self.state_compressor.log_compression_stats()
