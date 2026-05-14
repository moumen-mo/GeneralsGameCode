import math
from dataclasses import dataclass

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
