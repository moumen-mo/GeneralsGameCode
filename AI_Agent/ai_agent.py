#!/usr/bin/env python3
"""
Local AI entrypoint for C&C Generals Zero Hour RPC control.

Run the game in SKIRMISH mode first, then run this script.
"""

import os

from dotenv import load_dotenv

from AI_Agent.game_logging import game_log
from AI_Agent.game_analyser import GameAnalyser
from AI_Agent.rpc_client import GameRpcClient

load_dotenv()


def main() -> None:
    print("=" * 60)
    print("C&C Generals Zero Hour - Local AI RPC Agent")
    print("=" * 60)

    host = os.getenv("RPC_HOST", "127.0.0.1")
    port = int(os.getenv("RPC_PORT", "4500"))
    log_file = os.getenv("RPC_LOG_FILE")

    if log_file:
        print(f"RPC communication will be logged to: {log_file}")
    else:
        print("(Set RPC_LOG_FILE environment variable to log RPC communication)")

    client = GameRpcClient(
        host=host,
        port=port,
        timeout=float(os.getenv("RPC_TIMEOUT", "10")),
    )
    if not client.ping():
        game_log("RPC ping failed")
        return

    state = client.get_state()
    if state.get("status") == "ok":
        game_log(f"Frame: {state.get('frame')}")
        game_log(f"Map: {state.get('map_width')} x {state.get('map_height')}")
        game_log(f"Objects: {state.get('object_count')}")

        players = state.get("players", [])
        game_log("Players:")
        for p in players:
            game_log(
                f"  Player {int(p.get('player_id', -1))}: {p.get('side', '')} "
                f"(${float(p.get('money', 0.0)):.0f})"
            )

    controller = GameAnalyser(client)
    try:
        controller.run()
    except KeyboardInterrupt:
        game_log("Stopped by user")
    finally:
        client.close()


if __name__ == "__main__":
    main()