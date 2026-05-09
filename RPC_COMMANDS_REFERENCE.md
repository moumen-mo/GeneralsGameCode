# RPC Server - Game Commands Reference

This reference is aligned with the current source in:
`GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h` and `GeneralsMD/Code/GameEngine/Source/Common/RpcServer.cpp`.

## Important: `message_type` values are engine enum values

RPC `create_game_message` sends a raw `GameMessage::Type` integer.
The IDs below are the current values in this repo.

## RPC Action Support (Current)

| Action | Playable Game Required | Notes |
|---|---|---|
| `ping` | No | Connection/latency check |
| `set_controlled_player` | No | Sets default command owner for this socket |
| `get_state` | Yes | Full snapshot |
| `list_players` | Yes | Player summary |
| `list_objects` | Yes | Object summary |
| `create_game_message` | Yes | Queues game command |

---

## Command Categories (Verified IDs)

<!-- AUTO-GENERATED:COMMAND_TABLES:START -->
Generated from `GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h` by `python utils_mm/regenerate_rpc_command_tables.py`.

### Movement Commands

| Command | Type | Arguments | Purpose |
|---|---:|---|---|
| `MSG_DO_MOVETO` | 1068 | `location` | Move selected units |
| `MSG_DO_ATTACKMOVETO` | 1069 | `location` | Move and attack en route |
| `MSG_DO_FORCEMOVETO` | 1070 | `location` | Force move |
| `MSG_ADD_WAYPOINT` | 1071 | `location` | Add waypoint |
| `MSG_DO_GUARD_POSITION` | 1072 | `location` | Guard a position |
| `MSG_DO_GUARD_OBJECT` | 1073 | `integer` (object id) | Guard an object |
| `MSG_DO_STOP` | 1074 | - | Stop selected units |
| `MSG_DO_SCATTER` | 1075 | - | Scatter selected units |
| `MSG_CREATE_FORMATION` | 1094 | - | Formation command |

### Combat Commands

| Command | Type | Arguments | Purpose |
|---|---:|---|---|
| `MSG_DO_ATTACK_OBJECT` | 1059 | `integer` (object id) | Attack target object |
| `MSG_DO_FORCE_ATTACK_OBJECT` | 1060 | `integer` (object id) | Force-attack target object |
| `MSG_DO_FORCE_ATTACK_GROUND` | 1061 | `location` | Attack ground location |
| `MSG_DO_ATTACKSQUAD` | 1036 | command-specific | Attack squad command |

### Building Commands

| Command | Type | Arguments | Purpose |
|---|---:|---|---|
| `MSG_DOZER_CONSTRUCT` | 1049 | `integer` (template id), `location` | Build structure |
| `MSG_DOZER_CONSTRUCT_LINE` | 1050 | command-specific | Line construction |
| `MSG_DOZER_CANCEL_CONSTRUCT` | 1051 | command-specific | Cancel construction |
| `MSG_SELL` | 1052 | `integer` (object id) | Sell structure |
| `MSG_DO_REPAIR` | 1064 | `integer` (object id) | Repair target |
| `MSG_RESUME_CONSTRUCTION` | 1065 | `integer` (object id) | Resume construction |
| `MSG_SET_RALLY_POINT` | 1043 | command-specific | Set rally point |

### Transportation / Utility Commands

| Command | Type | Arguments | Purpose |
|---|---:|---|---|
| `MSG_EXIT` | 1053 | - | Exit garrison/transport |
| `MSG_EVACUATE` | 1054 | command-specific | Evacuate contents |
| `MSG_GET_REPAIRED` | 1062 | `integer` (object id) | Go to repair facility |
| `MSG_GET_HEALED` | 1063 | `integer` (object id) | Go to healing facility |
| `MSG_ENTER` | 1066 | `integer` (object id) | Enter transport/building |
| `MSG_DOCK` | 1067 | `integer` (object id) | Dock at target |

### Special Powers

| Command | Type | Arguments | Purpose |
|---|---:|---|---|
| `MSG_DO_SPECIAL_POWER` | 1040 | command-specific | Special power command |
| `MSG_DO_SPECIAL_POWER_AT_LOCATION` | 1041 | `integer` (power id), `location` | Use power at location |
| `MSG_DO_SPECIAL_POWER_AT_OBJECT` | 1042 | `integer` (power id), `integer` (object id) | Use power on object |

### Unit Group Management

| Command | Type | Arguments | Purpose |
|---|---:|---|---|
| `MSG_CREATE_SELECTED_GROUP` | 1001 | command-specific | Create control group |
| `MSG_SELECT_TEAM0`-`MSG_SELECT_TEAM9` | 1016-1025 | - | Select control group |
| `MSG_ADD_TEAM0`-`MSG_ADD_TEAM9` | 1026-1035 | - | Add control group to selection |

<!-- AUTO-GENERATED:COMMAND_TABLES:END -->

## Argument Type Reference

### `location` / `coord`

Direct form:
```json
{"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
```

Nested form:
```json
{"type": "location", "value": {"x": 1500.0, "y": 2500.0, "z": 0.0}}
```

### `integer` / `int`
```json
{"type": "integer", "value": 42}
```

### `real` / `float` / `double`
```json
{"type": "real", "value": 123.45}
```

### `boolean` / `bool`
```json
{"type": "boolean", "value": true}
```

---

## Common Command Patterns (Corrected)

### Move Selected Units (`MSG_DO_MOVETO` = 1068)
```json
{
  "action": "create_game_message",
  "message_type": 1068,
  "arguments": [
    {"type": "location", "x": 2000, "y": 2500, "z": 0}
  ]
}
```

### Attack Object (`MSG_DO_ATTACK_OBJECT` = 1059)
```json
{
  "action": "create_game_message",
  "message_type": 1059,
  "arguments": [
    {"type": "integer", "value": 5001}
  ]
}
```

### Build Structure (`MSG_DOZER_CONSTRUCT` = 1049)
```json
{
  "action": "create_game_message",
  "message_type": 1049,
  "arguments": [
    {"type": "integer", "value": 105},
    {"type": "location", "x": 3000, "y": 3000, "z": 0}
  ]
}
```

### Use Special Power (`MSG_DO_SPECIAL_POWER_AT_LOCATION` = 1041)
```json
{
  "action": "create_game_message",
  "message_type": 1041,
  "arguments": [
    {"type": "integer", "value": 42},
    {"type": "location", "x": 2500, "y": 2500, "z": 0}
  ]
}
```

---

## RPC Parser Behavior (Useful for Integrators)

- `action` is case-insensitive (`Ping`, `PING`, `ping` all work).
- `message_type` and `type` are accepted aliases.
- `arguments` and `args` are accepted aliases.
- `player_index` and `player_id` are accepted aliases for command ownership.
- `set_controlled_player` sets socket-level default command ownership.
- `ping` and `set_controlled_player` work outside playable game modes.

For `create_game_message`:

- `player_index` is optional; if omitted, socket default from `set_controlled_player` is used.
- If no socket default was set, local player is used.
- If provided, it must be a valid player slot from `list_players`.
- Success response echoes the effective `player_index`.

For `set_controlled_player`:

- Requires `player_index` (or `player_id`) as an integer.
- Persists for the lifetime of the TCP socket.
- Can be overridden per command by passing `player_index` directly to `create_game_message`.

---

## Validate Before Sending Commands

```python
# 1. Unit/target existence
objects = client.list_objects()["objects"]
controlled_player = 1
# Optional once per connection:
# client.send_command("set_controlled_player", player_index=controlled_player)
my_units = [o for o in objects if o.get("player_id") == controlled_player]
enemies = [o for o in objects if o.get("player_id") != controlled_player]

# 2. Resource check
players = client.list_players()["players"]
my_money = next((p["money"] for p in players if p["player_id"] == controlled_player), 0)

# 3. Map bounds check
state = client.get_state()
if not (0 <= x <= state["map_width"] and 0 <= y <= state["map_height"]):
    raise ValueError("Invalid location")
```

---

## Keeping This File Up To Date

Regenerate the command tables with:

```bash
python utils_mm/regenerate_rpc_command_tables.py
```

CI/drift check mode:

```bash
python utils_mm/regenerate_rpc_command_tables.py --check
```

The RPC server does not remap names to IDs; it uses the raw `GameMessage::Type` enum integer.
