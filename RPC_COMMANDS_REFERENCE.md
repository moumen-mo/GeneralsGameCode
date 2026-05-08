# RPC Server - Game Commands Reference

## Command Categories

### Movement Commands

| Command | Type | Arguments | Purpose |
|---------|------|-----------|---------|
| MSG_DO_MOVETO | 1001 | location | Move unit to position |
| MSG_DO_ATTACKMOVETO | 1002 | location | Move and attack enemies en route |
| MSG_DO_FORCEMOVETO | 1004 | location | Move ignoring obstacles/enemies |
| MSG_DO_TIGHTCLUSTER | 1010 | - | Form tight formation |
| MSG_DO_LOOSEGROUP | 1011 | - | Form loose group |
| MSG_DO_SCATTER | 1012 | - | Scatter unit formation |

### Combat Commands

| Command | Type | Arguments | Purpose |
|---------|------|-----------|---------|
| MSG_DO_ATTACK_OBJECT | 1003 | object_id | Attack specific unit/building |
| MSG_DO_FORCE_ATTACK_OBJECT | 1007 | object_id | Attack with max force |
| MSG_DO_ATTACKSQUAD | 1008 | squad_id | Attack squad of units |

### Building Commands

| Command | Type | Arguments | Purpose |
|---------|------|-----------|---------|
| MSG_DOZER_CONSTRUCT | 1050 | template_id, location | Build structure (Dozer only) |
| MSG_SELL | 1051 | object_id | Sell building for funds |
| MSG_REPAIR | 1052 | object_id | Repair building/unit |
| MSG_SET_RALLY_POINT | 1055 | location | Set production rally point |

### Transportation Commands

| Command | Type | Arguments | Purpose |
|---------|------|-----------|---------|
| MSG_ENTER | 1060 | object_id | Enter transport/building |
| MSG_EXIT | 1061 | - | Exit transport |
| MSG_DOCK | 1062 | object_id | Dock at facility |
| MSG_GET_REPAIRED | 1063 | object_id | Move to repair facility |
| MSG_GET_HEALED | 1064 | object_id | Move to healing facility |

### Special Powers

| Command | Type | Arguments | Purpose |
|---------|------|-----------|---------|
| MSG_DO_SPECIAL_POWER_AT_LOCATION | 1100 | power_id, location | Use special power at location |
| MSG_DO_SPECIAL_POWER_ON_OBJECT | 1101 | power_id, object_id | Use special power on unit/building |

### Unit Management

| Command | Type | Arguments | Purpose |
|---------|------|-----------|---------|
| MSG_CREATE_SELECTED_GROUP | 1200 | object_id | Create group from units |
| MSG_SELECT_TEAM0-9 | 1210-1219 | - | Select saved unit group |
| MSG_ADD_TEAM0-9 | 1220-1229 | - | Add to saved unit group |

---

## Argument Type Reference

### location / coord
Specifies a 3D position on the map.

**Format**:
```json
{"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
```

**Alternative format** (nested value):
```json
{"type": "location", "value": {"x": 1500.0, "y": 2500.0, "z": 0.0}}
```

**Examples**:
- `"x": 0, "y": 0` - Map corner
- `"x": 2000, "y": 2000` - Map center (for 4000x4000 map)
- `"z": 10` - Height above terrain (optional, defaults to 0)

---

### integer
Specifies an integer value (object ID, count, etc.).

**Format**:
```json
{"type": "integer", "value": 42}
```

**Examples**:
- Object/Unit ID: `{"type": "integer", "value": 1234}`
- Template ID: `{"type": "integer", "value": 105}`
- Special Power ID: `{"type": "integer", "value": 1}`

---

### real / float / double
Specifies a decimal number.

**Format**:
```json
{"type": "real", "value": 123.45}
```

**Examples**:
- Damage: `{"type": "real", "value": 50.5}`
- Duration: `{"type": "real", "value": 10.0}`

---

### boolean / bool
Specifies true or false.

**Format**:
```json
{"type": "boolean", "value": true}
```

---

## Common Command Patterns

### Pattern 1: Move Selected Units
```json
{
  "action": "create_game_message",
  "message_type": 1001,
  "arguments": [
    {"type": "location", "x": 2000, "y": 2500, "z": 0}
  ]
}
```

### Pattern 2: Attack Enemy Unit
```json
{
  "action": "create_game_message",
  "message_type": 1003,
  "arguments": [
    {"type": "integer", "value": 5001}
  ]
}
```

### Pattern 3: Build Structure
```json
{
  "action": "create_game_message",
  "message_type": 1050,
  "arguments": [
    {"type": "integer", "value": 105},
    {"type": "location", "x": 3000, "y": 3000, "z": 0}
  ]
}
```

### Pattern 4: Use Special Power
```json
{
  "action": "create_game_message",
  "message_type": 1100,
  "arguments": [
    {"type": "integer", "value": 42},
    {"type": "location", "x": 2500, "y": 2500, "z": 0}
  ]
}
```

---

## Finding Template IDs

To determine template IDs for building commands:

1. **Use list_objects** RPC action
2. Look at the "template_id" field for known buildings
3. Common template IDs:
   - War Factory: ~105
   - Power Plant: ~110
   - Barracks: ~115
   - Defense Tower: ~120

---

## Finding Special Power IDs

To find available special powers:

1. Query the game's special power manager (future enhancement)
2. Common special powers:
   - Air Strike: ID ~1
   - Nuclear Strike: ID ~2
   - Superweapon: ID ~3

---

## Validation Tips

Before sending commands, validate:

```python
# 1. Unit exists (via list_objects)
units = client.list_objects()
unit_ids = [u["id"] for u in units if u["player_id"] == 0]

# 2. Target exists (via list_objects)
targets = [u for u in units if u["player_id"] != 0]

# 3. Have enough money (via list_players)
players = client.list_players()
my_money = players[0]["money"]

# 4. Position is valid (within map bounds)
state = client.get_state()
if x < 0 or x > state["map_width"]:
    print("Invalid X coordinate")
```

---

## Command Execution Flow

```
LLM Agent
    ↓
Build JSON Command
    ↓
Send via RPC (TCP port 4500)
    ↓
RpcServer receives JSON
    ↓
parseJson() → JsonValue
    ↓
buildGameMessageFromJson() → GameMessage
    ↓
TheCommandList->appendMessage()
    ↓
GameLogic::update() processes
    ↓
AI Group executes (move/attack/build)
    ↓
Game state updates
    ↓
Next RPC query sees new state
```

---

## Performance Tips

1. **Batch commands**: Send multiple commands in one decision frame
2. **Sampling rate**: Query state every 100-200ms (5-10 Hz)
3. **Command interval**: Queue commands but don't spam (1 per unit per decision)
4. **Early abort**: Cancel unnecessary commands if situation changes
5. **Predictive**: Anticipate enemy moves based on previous state

---

## Debugging

### Enable verbose responses

All RPC responses include `"status": "ok"` or `"status": "error"`.

### Check error messages
```python
response = client.send_command(cmd)
if response.get("status") == "error":
    print(f"Error: {response['message']}")
```

### Log all commands
```python
def log_command(cmd):
    print(f"[{time.time()}] Sending: {json.dumps(cmd)}")
```

### Monitor frame rate
```python
state = client.get_state()
print(f"Current frame: {state['frame']}")
```

---

## Limitations & Constraints

- **Command latency**: ~50-100ms between RPC and execution
- **Sync in multiplayer**: Commands must be compatible with network sync
- **Unit capacity**: Map can support ~500 objects (performance limit)
- **AI complexity**: Simple strategy recommended for latency tolerance
- **Message types**: Only types 1000+ are safe for RPC (network-safe)

