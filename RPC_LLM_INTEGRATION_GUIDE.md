# RPC Server Integration Guide for LLM AI Control

## Overview

Your RPC server enables real-time control of C&C Generals Zero Hour via JSON commands over TCP. This guide explains how to use it with an LLM agent to play against the PC AI.

## Quick Start

### 1. Server Connection
- **Host**: localhost (127.0.0.1)
- **Port**: 4500
- **Protocol**: JSON over TCP (one command per line, newline-delimited)

### 2. Supported Game Modes
✅ **GAME_SKIRMISH** - Single-player vs AI (recommended)
✅ **GAME_SINGLE_PLAYER** - Campaign/Challenge modes
✅ **GAME_LAN** - LAN multiplayer
✅ **GAME_INTERNET** - Online multiplayer
❌ **GAME_SHELL** - Menu (no game state)

### 3. Basic Workflow

```python
# 1. Connect to game server
client = connect_to_tcp("127.0.0.1", 4500)

# 2. Get current game state
response = send_command(client, {"action": "ping"})

# 3. Get full game state (players, units, buildings)
state = send_command(client, {"action": "get_state"})

# 4. Query players for AI decision-making
players = send_command(client, {"action": "list_players"})

# 5. Query objects (units, buildings, structures)
objects = send_command(client, {"action": "list_objects"})

# 6. Send unit commands (move, attack, build, etc.)
cmd = send_command(client, {
    "action": "create_game_message",
    "message_type": 1001,  # MSG_DO_MOVETO
    "arguments": [
        {"type": "location", "x": 1000.0, "y": 2000.0, "z": 0.0}
    ]
})
```

---

## RPC Actions Reference

### 1. PING (Connection Test)
```json
{
  "action": "ping"
}
```
**Response**: `{"status": "ok", "action": "ping"}`
- Works even if game is not in playable mode
- Use to verify connection and latency

---

### 2. GET_STATE (Full Game State)
```json
{
  "action": "get_state"
}
```

**Response**:
```json
{
  "status": "ok",
  "frame": 12345,
  "map_width": 4000.0,
  "map_height": 4000.0,
  "players": [
    {
      "player_id": 1,
      "side": "USA",
      "name_key": 42,
      "money": 15000
    },
    ...
  ],
  "objects": [...],
  "object_count": 127
}
```

**Use Case**: Get complete game snapshot for LLM decision-making

---

### 3. LIST_PLAYERS (Player Information)
```json
{
  "action": "list_players"
}
```

**Response**:
```json
{
  "status": "ok",
  "players": [
    {
      "player_id": 0,
      "side": "USA",
      "name_key": 0,
      "money": 5000.0
    },
    {
      "player_id": 1,
      "side": "GLA",
      "name_key": 1,
      "money": 3500.0
    }
  ],
  "player_count": 2
}
```

**Fields**:
- `player_id`: Player index (0 = your LLM AI, 1+ = opponent/allies)
- `side`: Faction (USA, GLA, CHINA)
- `money`: Current available funds
- `name_key`: Unique player identifier

**Use Case**: Track opponent resources and determine economic feasibility of actions

---

### 4. LIST_OBJECTS (Units & Buildings)
```json
{
  "action": "list_objects"
}
```

**Response**:
```json
{
  "status": "ok",
  "objects": [
    {
      "id": 1001,
      "template_id": 45,
      "template_name": "Ranger",
      "position": {"x": 1000.0, "y": 2000.0, "z": 10.0},
      "player_id": 0,
      "player_name": "USA",
      "team_name": "Team 0",
      "health": 100.0,
      "max_health": 100.0,
      "health_percent": 100.0,
      "is_selected": false,
      "distance_from_center": 500.5
    },
    ...
  ],
  "object_count": 127
}
```

**Fields**:
- `id`: Unique unit/building ID (use for targeting)
- `template_name`: Unit type (Ranger, Tank, War Factory, etc.)
- `position`: 3D coordinates on map
- `player_id`: Owner (0 = you, 1+ = opponent)
- `health_percent`: Health 0-100% (critical for attack decisions)
- `distance_from_center`: Distance from map center (useful for position assessment)

**Use Case**: Identify targets, friendly units, and resource availability

---

### 5. CREATE_GAME_MESSAGE (Send Unit Commands)

#### Message Format
```json
{
  "action": "create_game_message",
  "message_type": 1001,
  "arguments": [
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```

#### Common Command Types

##### Move Unit to Location
```json
{
  "message_type": 1001,
  "arguments": [
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```
- **Message Type**: 1001 (MSG_DO_MOVETO)
- **Arguments**: Target location

##### Attack Move (Move + Attack)
```json
{
  "message_type": 1002,
  "arguments": [
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```
- **Message Type**: 1002 (MSG_DO_ATTACKMOVETO)
- **Arguments**: Target location

##### Attack Specific Unit
```json
{
  "message_type": 1003,
  "arguments": [
    {"type": "integer", "value": 1234}
  ]
}
```
- **Message Type**: 1003 (MSG_DO_ATTACK_OBJECT)
- **Arguments**: Target object ID

##### Force Move (Ignore enemies)
```json
{
  "message_type": 1004,
  "arguments": [
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```
- **Message Type**: 1004 (MSG_DO_FORCEMOVETO)

##### Build Structure (Dozer)
```json
{
  "message_type": 1050,
  "arguments": [
    {"type": "integer", "value": 105},
    {"type": "location", "x": 2000.0, "y": 3000.0, "z": 0.0}
  ]
}
```
- **Message Type**: 1050 (MSG_DOZER_CONSTRUCT)
- **Arguments**: Template ID, Build location

##### Special Power at Location
```json
{
  "message_type": 1100,
  "arguments": [
    {"type": "integer", "value": 42},
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```
- **Message Type**: 1100 (MSG_DO_SPECIAL_POWER_AT_LOCATION)
- **Arguments**: Special power ID, Target location

#### Argument Types

| Type | Description | Example |
|------|-------------|---------|
| `integer` | Whole number | `{"type": "integer", "value": 42}` |
| `real` / `float` / `double` | Decimal number | `{"type": "real", "value": 123.45}` |
| `boolean` | True/False | `{"type": "boolean", "value": true}` |
| `location` / `coord` | 3D position | `{"type": "location", "x": 100, "y": 200, "z": 0}` |

**Response**:
```json
{
  "status": "ok",
  "action": "create_game_message"
}
```

---

## Error Responses

### Game Not in Playable Mode
```json
{
  "status": "error",
  "message": "Game is not in a playable mode. Valid modes: SKIRMISH, SINGLE_PLAYER, LAN, INTERNET"
}
```
**Solution**: Start a game in one of the supported modes

### Missing Required Fields
```json
{
  "status": "error",
  "message": "Missing or invalid action field"
}
```
**Solution**: Ensure all required JSON fields are present

### Invalid Command Structure
```json
{
  "status": "error",
  "message": "Argument missing value"
}
```
**Solution**: Check argument types and formats

### Command List Not Initialized
```json
{
  "status": "error",
  "message": "TheCommandList is not initialized"
}
```
**Solution**: Game is not ready; try after initial game load

---

## LLM AI Implementation Strategy

### Phase 1: Awareness (Read Game State)
```python
def get_game_intelligence():
    state = send_rpc("get_state")
    players = send_rpc("list_players")
    objects = send_rpc("list_objects")
    
    # Analyze:
    # - My resources vs opponent resources
    # - My unit positions and health
    # - Enemy unit positions and threats
    # - Strategic map control
    return {
        "my_resources": players[0]["money"],
        "enemy_resources": players[1]["money"],
        "my_units": [u for u in objects if u["player_id"] == 0],
        "enemy_units": [u for u in objects if u["player_id"] == 1],
    }
```

### Phase 2: Decision Making (LLM Analysis)
```python
def make_decision(game_state):
    # Prompt LLM with game state
    prompt = f"""
    Current game state:
    - My money: {game_state["my_resources"]}
    - Enemy money: {game_state["enemy_resources"]}
    - My units: {game_state["my_units"]}
    - Enemy units: {game_state["enemy_units"]}
    
    What should I do next? Return a list of unit commands.
    """
    
    llm_response = call_llm(prompt)
    return parse_commands(llm_response)
```

### Phase 3: Execution (Send Commands)
```python
def execute_commands(commands):
    for cmd in commands:
        if cmd["type"] == "move":
            send_rpc({
                "action": "create_game_message",
                "message_type": 1001,
                "arguments": [
                    {"type": "location", "x": cmd["x"], "y": cmd["y"], "z": 0}
                ]
            })
        elif cmd["type"] == "attack":
            send_rpc({
                "action": "create_game_message",
                "message_type": 1003,
                "arguments": [
                    {"type": "integer", "value": cmd["target_id"]}
                ]
            })
```

### Phase 4: Loop (Every Frame/Decision Tick)
```python
def ai_game_loop():
    while game_running():
        game_state = get_game_intelligence()
        decisions = make_decision(game_state)
        execute_commands(decisions)
        sleep(0.1)  # ~10 times per second
```

---

## Important Notes

### 1. Unit Selection
- Commands are executed by the **currently selected group**
- Make sure your LLM AI's units are selected before sending commands
- Consider: "Select my Ranger unit at position X" action

### 2. Timing
- Optimal decision frequency: **5-10 times per second** (0.1-0.2s intervals)
- Too fast = spam, too slow = unresponsive
- Frame rate: Check `frame` field in get_state response

### 3. Target Validation
- Always verify object exists before attacking (use `list_objects`)
- Filter objects by `player_id` to find enemies
- Check `health_percent` to avoid targeting dead units

### 4. Resource Management
- Monitor money via `list_players`
- Ensure enough resources before issuing build commands
- Consider: Tech requirements for units/buildings

### 5. Multiplayer Sync (LAN/Internet)
- Commands are automatically validated
- Avoid command spam (queue commands, don't spam same command)
- Game applies commands every frame for network sync

---

## Python Example Client

```python
import socket
import json
import time

class GameRpcClient:
    def __init__(self, host="127.0.0.1", port=4500):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((host, port))
    
    def send_command(self, action, **kwargs):
        msg = {"action": action}
        msg.update(kwargs)
        
        # Send JSON command (newline-delimited)
        self.socket.sendall((json.dumps(msg) + "\n").encode())
        
        # Receive response (read until newline)
        response = b""
        while True:
            chunk = self.socket.recv(1024)
            response += chunk
            if b"\n" in response:
                break
        
        return json.loads(response.decode().strip())
    
    def ping(self):
        return self.send_command("ping")
    
    def get_state(self):
        return self.send_command("get_state")
    
    def list_players(self):
        return self.send_command("list_players")
    
    def list_objects(self):
        return self.send_command("list_objects")
    
    def move_unit(self, x, y, z=0):
        return self.send_command(
            "create_game_message",
            message_type=1001,
            arguments=[{"type": "location", "x": x, "y": y, "z": z}]
        )
    
    def attack_object(self, object_id):
        return self.send_command(
            "create_game_message",
            message_type=1003,
            arguments=[{"type": "integer", "value": object_id}]
        )

# Usage
if __name__ == "__main__":
    client = GameRpcClient()
    
    # Test connection
    print(client.ping())
    
    # Get game state
    state = client.get_state()
    print(f"Frame: {state['frame']}, Map: {state['map_width']}x{state['map_height']}")
    
    # Get players
    players = client.list_players()
    print(f"Players: {players['player_count']}")
    
    # Get objects
    objects = client.list_objects()
    print(f"Total objects: {objects['object_count']}")
    
    # Issue a command
    result = client.move_unit(1500, 2500, 0)
    print(f"Command result: {result}")
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection refused" | Start Generals first, ensure game is running |
| "Game is not in a playable mode" | Load a SKIRMISH game first |
| "Unknown action" | Check action spelling (lowercase) |
| "TheCommandList not initialized" | Wait for game to fully load |
| Empty object list | Check game state, units may not be visible yet |
| Commands not executing | Verify correct message type and argument format |

