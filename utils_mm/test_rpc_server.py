import socket
import json


def send_json_request(sock, request):
    """Send a JSON request and receive one JSON-line response."""
    sock.sendall((json.dumps(request) + "\n").encode("utf-8"))

    response_data = b""
    sock.settimeout(5.0)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            if response_data.endswith(b"\n"):
                break
    except socket.timeout:
        pass

    sock.settimeout(None)
    return response_data.decode("utf-8", errors="replace").strip()


def send_request(sock, action):
    """Send an action-only request and receive response."""
    return send_json_request(sock, {"action": action})


def test_rpc():
    try:
        print("=" * 60)
        print("RPC SERVER TEST")
        print("=" * 60)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", 4500))
        print("[OK] Connected to 127.0.0.1:4500\n")

        # Test 1: ping
        print("Test 1: PING")
        print("-" * 60)
        response = send_request(sock, "ping")
        print("Request: {'action':'ping'}")
        print(f"Response: {response}\n")
        try:
            resp_json = json.loads(response)
            if resp_json.get("status") == "ok":
                print("[OK] Ping successful!\n")
            else:
                print("[WARN] Unexpected response\n")
        except json.JSONDecodeError:
            print("[WARN] Invalid JSON response\n")

        # Test 2: get_state
        print("Test 2: GET_STATE")
        print("-" * 60)
        response = send_request(sock, "get_state")
        print("Request: {'action':'get_state'}")
        try:
            resp_json = json.loads(response)
            print(f"Response: {json.dumps(resp_json, indent=2)}\n")
            if resp_json.get("status") == "ok":
                print("[OK] State retrieved successfully!")
                if "frame" in resp_json:
                    print(f"  Frame: {resp_json['frame']}")
                if "object_count" in resp_json:
                    print(f"  Objects: {resp_json['object_count']}")
                print()
            else:
                print("[WARN] Unexpected response\n")
        except json.JSONDecodeError:
            print("[WARN] Invalid JSON response\n")

        # Test 3: list_players
        print("Test 3: LIST_PLAYERS")
        print("-" * 60)
        response = send_request(sock, "list_players")
        print("Request: {'action':'list_players'}")
        first_player_id = None
        try:
            resp_json = json.loads(response)
            print(f"Response: {json.dumps(resp_json, indent=2)}\n")
            if resp_json.get("status") == "ok":
                print("[OK] Players retrieved successfully!")
                if "player_count" in resp_json:
                    print(f"  Player count: {resp_json['player_count']}")
                players = resp_json.get("players") or []
                if players and players[0].get("player_id") is not None:
                    first_player_id = int(players[0]["player_id"])
                print()
            else:
                print("[WARN] Unexpected response\n")
        except json.JSONDecodeError:
            print("[WARN] Invalid JSON response\n")

        # Test 3b: set_controlled_player
        if first_player_id is not None:
            print("Test 3b: SET_CONTROLLED_PLAYER")
            print("-" * 60)
            request = {"action": "set_controlled_player", "player_index": first_player_id}
            response = send_json_request(sock, request)
            print(f"Request: {request}")
            print(f"Response: {response}\n")
            try:
                resp_json = json.loads(response)
                if resp_json.get("status") == "ok":
                    print("[OK] set_controlled_player successful!")
                    print(f"  Controlled player: {resp_json.get('player_index')}\n")
                else:
                    print("[WARN] set_controlled_player returned error\n")
            except json.JSONDecodeError:
                print("[WARN] Invalid JSON response from set_controlled_player\n")

        # Test 4: list_objects
        print("Test 4: LIST_OBJECTS (first 3 objects)")
        print("-" * 60)
        response = send_request(sock, "list_objects")
        print("Request: {'action':'list_objects'}")
        try:
            resp_json = json.loads(response)
            if resp_json.get("status") == "ok":
                print("[OK] Objects retrieved successfully!")
                if "object_count" in resp_json:
                    print(f"  Object count: {resp_json['object_count']}")
                if "objects" in resp_json:
                    for i, obj in enumerate(resp_json["objects"][:3]):
                        print(f"  Object {i}: ID={obj.get('id')}, Template={obj.get('template_id')}")
                print()
            else:
                print("[WARN] Unexpected response\n")
        except json.JSONDecodeError:
            print("[WARN] Invalid JSON response\n")

        sock.close()

        print("=" * 60)
        print("[OK] RPC SERVER IS WORKING!")
        print("=" * 60)

    except ConnectionRefusedError:
        print("[ERROR] Connection refused!")
        print("  - Is the game running?")
        print("  - Did the RPC server initialize properly?")
    except TimeoutError:
        print("[ERROR] Connection timeout - server may not be responding")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")


if __name__ == "__main__":
    test_rpc()
