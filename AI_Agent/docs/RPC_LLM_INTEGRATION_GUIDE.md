# RPC Server Integration Guide for LLM AI Control

## Overview

This RPC server exposes C&C Generals Zero Hour control through newline-delimited JSON over TCP.
The behavior documented here is verified against:

- `GeneralsMD/Code/GameEngine/Source/Common/RpcServer.cpp`
- `GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h`

## Quick Start

### 1. Server Connection

- Host: `127.0.0.1` (loopback only)
- Port: `4500`
- Protocol: JSON lines (one JSON request per line, newline-delimited)

### 2. Supported Game Modes

Allowed for gameplay actions (`get_state`, `list_players`, `list_objects`, `create_game_message`):

- `GAME_SKIRMISH`
- `GAME_SINGLE_PLAYER`
- `GAME_LAN`
- `GAME_INTERNET`

Not playable for those actions:

- `GAME_SHELL` (menu)

`ping` and `set_controlled_player` are connection-level actions.

### 3. Basic Workflow

```python
# 1) Connect to server
client = connect_to_tcp("127.0.0.1", 4500)

# 2) Connectivity test
send_command(client, {"action": "ping"})

# 3) Game snapshot
state = send_command(client, {"action": "get_state"})
players = send_command(client, {"action": "list_players"})
objects = send_command(client, {"action": "list_objects"})

# 4) Pick controlled player once per socket
send_command(client, {"action": "set_controlled_player", "player_index": 1})

# 5) Issue command (move) - uses controlled player set above
send_command(client, {
    "action": "create_game_message",
    "message_type": 1068,  # MSG_DO_MOVETO
    "arguments": [
        {"type": "location", "x": 1000.0, "y": 2000.0, "z": 0.0}
    ]
})
```

---

## RPC Actions Reference

### 1. PING

Request:
```json
{"action": "ping"}
```

Typical response:
```json
{"action": "ping", "status": "ok"}
```

### 2. GET_STATE

Request:
```json
{"action": "get_state"}
```

Response fields:

- `status`: `"ok"`
- `frame`
- `map_width`, `map_height`
- `players` (when available)
- `objects`
- `object_count`

### 3. LIST_PLAYERS

Request:
```json
{"action": "list_players"}
```

Player fields:

- `player_id`
- `side`
- `name_key`
- `money`

Also includes `player_count`.

### 4. LIST_OBJECTS

Request:
```json
{"action": "list_objects"}
```

Common object fields:

- `id`
- `template_id`, `template_name` (when template exists)
- `position` (`x`, `y`, `z`)
- `player_id`, `player_name`
- `team_name` (when available)
- `health`, `max_health`, `health_percent` (when body exists)
- `is_selected`
- `distance_from_center`

Also includes `object_count`.

### 5. SET_CONTROLLED_PLAYER

Set the default command owner for this TCP socket.

Request:
```json
{"action": "set_controlled_player", "player_index": 1}
```

Accepted aliases:

- `player_index` or `player_id`

Successful response:
```json
{"action": "set_controlled_player", "status": "ok", "player_index": 1}
```

### 6. CREATE_GAME_MESSAGE

Request shape:
```json
{
  "action": "create_game_message",
  "message_type": 1068,
  "player_index": 1,
  "arguments": [
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```

Accepted aliases:

- `message_type` or `type`
- `arguments` or `args`
- `player_index` or `player_id`

`player_index` is optional:

- If provided, it overrides socket default for this one command.
- If omitted, the server uses the socket's `set_controlled_player` value.
- If socket default was never set, local player is used.

All provided player indices must be valid integer slots from `list_players`.

Argument `type` values:

- `integer` / `int`
- `real` / `float` / `double`
- `boolean` / `bool`
- `location` / `coord`

Successful response:
```json
{"action": "create_game_message", "status": "ok", "player_index": 1}
```

### Controlling a Specific Army (Player Slot)

1. Call `list_players`.
2. Pick the `player_id` you want the LLM to control.
3. Call `set_controlled_player` once for that socket.
4. Send `create_game_message` without `player_index` (unless you want per-command override).

Example:
```json
{
  "action": "set_controlled_player",
  "player_index": 2
}
```

Then command:
```json
{
  "action": "create_game_message",
  "message_type": 1068,
  "arguments": [
    {"type": "location", "x": 1400.0, "y": 2100.0, "z": 0.0}
  ]
}
```

---

## Correct Message Type Examples

### Move Unit(s)

```json
{
  "action": "create_game_message",
  "message_type": 1068,
  "arguments": [
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```

### Attack Object

```json
{
  "action": "create_game_message",
  "message_type": 1059,
  "arguments": [
    {"type": "integer", "value": 1234}
  ]
}
```

### Build Structure

```json
{
  "action": "create_game_message",
  "message_type": 1049,
  "arguments": [
    {"type": "integer", "value": 105},
    {"type": "location", "x": 2000.0, "y": 3000.0, "z": 0.0}
  ]
}
```

### Special Power At Location

```json
{
  "action": "create_game_message",
  "message_type": 1041,
  "arguments": [
    {"type": "integer", "value": 42},
    {"type": "location", "x": 1500.0, "y": 2500.0, "z": 0.0}
  ]
}
```

---

## Error Responses

### Game not playable

```json
{
  "status": "error",
  "message": "Game is not in a playable mode. Valid modes: SKIRMISH, SINGLE_PLAYER, LAN, INTERNET"
}
```

### Invalid request/action

```json
{
  "status": "error",
  "message": "Missing or invalid action field"
}
```

or

```json
{
  "status": "error",
  "message": "Unknown action: <action>"
}
```

### Invalid command payload

Examples:

- `Missing or invalid message_type`
- `message_type must be an integer`
- `Missing player_index`
- `player_index must be an integer`
- `Invalid player_index: <value>`
- `arguments must be an array`
- `Argument missing type field`
- `Location argument requires x and y`

### Command system not ready

```json
{
  "status": "error",
  "message": "TheCommandList is not initialized"
}
```

---

## Practical LLM Loop

```python
while True:
    state = send_rpc({"action": "get_state"})
    players = send_rpc({"action": "list_players"})
    objects = send_rpc({"action": "list_objects"})

    # Build compact prompt state
    # Decide commands
    # Emit create_game_message calls

    time.sleep(0.1)  # 10 Hz
```

---

## Notes and Constraints

1. Commands are applied to current game selection/context.
2. Avoid command spam; issue deliberate commands at ~5-10 Hz.
3. Validate targets from fresh `list_objects` data before attack/build actions.
4. IDs are enum-backed and can change if enum order changes.

For a current message-type table, see `RPC_COMMANDS_REFERENCE.md`.

---

## Minimal Python Client

```python
import socket
import json

class GameRpcClient:
    def __init__(self, host="127.0.0.1", port=4500):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((host, port))

    def send_command(self, action, **kwargs):
        msg = {"action": action}
        msg.update(kwargs)
        self.socket.sendall((json.dumps(msg) + "\n").encode("utf-8"))

        buf = b""
        while b"\n" not in buf:
            chunk = self.socket.recv(4096)
            if not chunk:
                break
            buf += chunk

        return json.loads(buf.decode("utf-8").strip())

    def ping(self):
        return self.send_command("ping")

    def get_state(self):
        return self.send_command("get_state")

    def list_players(self):
        return self.send_command("list_players")

    def set_controlled_player(self, player_index):
        return self.send_command(
            "set_controlled_player",
            player_index=int(player_index),
        )

    def list_objects(self):
        return self.send_command("list_objects")

    def move_selected(self, x, y, z=0.0, player_index=None):
        payload = {
            "message_type": 1068,  # MSG_DO_MOVETO
            "arguments": [{"type": "location", "x": x, "y": y, "z": z}],
        }
        if player_index is not None:
            payload["player_index"] = int(player_index)
        return self.send_command("create_game_message", **payload)

    def attack_object(self, object_id, player_index=None):
        payload = {
            "message_type": 1059,  # MSG_DO_ATTACK_OBJECT
            "arguments": [{"type": "integer", "value": int(object_id)}],
        }
        if player_index is not None:
            payload["player_index"] = int(player_index)
        return self.send_command("create_game_message", **payload)
```
