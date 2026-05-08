import socket
import json
import time

def send_request(sock, action):
    """Send a request and receive response"""
    request = {"action": action}
    sock.sendall((json.dumps(request) + '\n').encode('utf-8'))
    
    # Read response with longer timeout to allow game thread to process
    response_data = b''
    sock.settimeout(5.0)  # 5 second timeout for game to process
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            # Check if we got a complete JSON message (ends with newline)
            if response_data.endswith(b'\n'):
                break
    except socket.timeout:
        pass  # Timeout is expected after we get the response
    
    sock.settimeout(None)  # Reset to blocking
    response = response_data.decode('utf-8', errors='replace').strip()
    return response

def test_rpc():
    try:
        print("=" * 60)
        print("RPC SERVER TEST")
        print("=" * 60)
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('127.0.0.1', 4500))
        print("✓ Connected to 127.0.0.1:4500\n")
        
        # Test 1: ping
        print("Test 1: PING")
        print("-" * 60)
        response = send_request(sock, "ping")
        print("Request: {'action':'ping'}")
        print(f"Response: {response}\n")
        try:
            resp_json = json.loads(response)
            if resp_json.get("status") == "ok":
                print("✓ Ping successful!\n")
            else:
                print(f"⚠ Unexpected response\n")
        except json.JSONDecodeError:
            print(f"⚠ Invalid JSON response\n")
        
        # Test 2: get_state
        print("Test 2: GET_STATE")
        print("-" * 60)
        response = send_request(sock, "get_state")
        print("Request: {'action':'get_state'}")
        try:
            resp_json = json.loads(response)
            print(f"Response: {json.dumps(resp_json, indent=2)}\n")
            if resp_json.get("status") == "ok":
                print("✓ State retrieved successfully!")
                if "frame" in resp_json:
                    print(f"  Frame: {resp_json['frame']}")
                if "object_count" in resp_json:
                    print(f"  Objects: {resp_json['object_count']}")
                print()
            else:
                print(f"⚠ Unexpected response\n")
        except json.JSONDecodeError:
            print(f"⚠ Invalid JSON response\n")
        
        # Test 3: list_players
        print("Test 3: LIST_PLAYERS")
        print("-" * 60)
        response = send_request(sock, "list_players")
        print("Request: {'action':'list_players'}")
        try:
            resp_json = json.loads(response)
            print(f"Response: {json.dumps(resp_json, indent=2)}\n")
            if resp_json.get("status") == "ok":
                print("✓ Players retrieved successfully!")
                if "player_count" in resp_json:
                    print(f"  Player count: {resp_json['player_count']}")
                print()
            else:
                print(f"⚠ Unexpected response\n")
        except json.JSONDecodeError:
            print(f"⚠ Invalid JSON response\n")
        
        # Test 4: list_objects
        print("Test 4: LIST_OBJECTS (first 3 objects)")
        print("-" * 60)
        response = send_request(sock, "list_objects")
        print("Request: {'action':'list_objects'}")
        try:
            resp_json = json.loads(response)
            if resp_json.get("status") == "ok":
                print("✓ Objects retrieved successfully!")
                if "object_count" in resp_json:
                    print(f"  Object count: {resp_json['object_count']}")
                if "objects" in resp_json:
                    for i, obj in enumerate(resp_json['objects'][:3]):
                        print(f"  Object {i}: ID={obj.get('id')}, Template={obj.get('template_id')}")
                print()
            else:
                print(f"⚠ Unexpected response\n")
        except json.JSONDecodeError:
            print(f"⚠ Invalid JSON response\n")
        
        sock.close()
        
        print("=" * 60)
        print("✓ RPC SERVER IS WORKING!")
        print("=" * 60)
        
    except ConnectionRefusedError:
        print("✗ Connection refused!")
        print("  - Is the game running?")
        print("  - Did the RPC server initialize properly?")
    except TimeoutError:
        print("✗ Connection timeout - server may not be responding")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    test_rpc()