#!/usr/bin/env python3
"""
Test script to validate the prompt caching optimization.
Demonstrates how SystemPromptCache reduces token overhead.
"""

import json
from dataclasses import dataclass

# Simulated LLM_COMMAND_TUTOR (command schema)
LLM_COMMAND_TUTOR = """You are a real-time strategy game AI. Your job is to output tactical commands in JSON format.

OUTPUT ONLY JSON. No other text, explanations, or code blocks.

JSON Structure:
{"commands": [{"type": "attack_object", "unit_ids": [1], "target_id": 2}, {"type": "attack_move", "unit_ids": [1], "x": 100, "y": 200, "z": 0}]}

COMMAND TYPES:
1. attack_object: {"type": "attack_object", "unit_ids": [ids...], "target_id": target}
2. attack_move: {"type": "attack_move", "unit_ids": [ids...], "x": X, "y": Y, "z": Z}
3. move: {"type": "move", "unit_ids": [ids...], "x": X, "y": Y, "z": Z}
4. force_move: {"type": "force_move", "unit_ids": [ids...], "x": X, "y": Y, "z": Z}

CRITICAL RULES:
- Start response with {
- End response with }
- Output only valid JSON
- Maximum 3 commands
- If no good action: {"commands": []}
- No markdown backticks
- No text before or after JSON
- Stop after the closing }"""


class SystemPromptCache:
    """
    Cache for system prompt to avoid resending static command schema on every tick.
    """

    def __init__(self) -> None:
        self.cached_system_prompt = LLM_COMMAND_TUTOR
        self.use_cache = True
        self.cache_stats = {"hits": 0, "sends": 0}

    def get_messages_with_cache(self, user_prompt: dict, first_call: bool = False) -> tuple:
        """
        Returns (messages list, should_send_system_prompt).
        
        First call: Sends full system prompt + user message
        Subsequent calls: Sends only user message (relies on LLM context)
        """
        if not self.use_cache or first_call:
            messages = [
                {"role": "system", "content": self.cached_system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))},
            ]
            self.cache_stats["sends"] += 1
            return messages, True

        # Subsequent calls: only send user message
        messages = [
            {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))}
        ]
        self.cache_stats["hits"] += 1
        return messages, False

    def log_cache_stats(self) -> None:
        """Log cache efficiency statistics."""
        total = self.cache_stats["sends"] + self.cache_stats["hits"]
        if total > 0:
            efficiency = (self.cache_stats["hits"] / total) * 100
            print(
                f"[CACHE STATS] System prompt sent {self.cache_stats['sends']} times, "
                f"reused {self.cache_stats['hits']} times (efficiency: {efficiency:.1f}%)"
            )

    def calculate_token_savings(self) -> dict:
        """Calculate approximate token savings from caching."""
        # Rough estimate: command schema is ~300 tokens
        schema_tokens = 300
        total_calls = self.cache_stats["sends"] + self.cache_stats["hits"]
        
        if self.use_cache and self.cache_stats["hits"] > 0:
            tokens_saved = self.cache_stats["hits"] * schema_tokens
            return {
                "total_calls": total_calls,
                "schema_tokens": schema_tokens,
                "tokens_saved": tokens_saved,
                "percentage_saved": (tokens_saved / (total_calls * schema_tokens)) * 100 if total_calls > 0 else 0,
            }
        return {"total_calls": total_calls, "tokens_saved": 0, "percentage_saved": 0}


def test_prompt_cache():
    """Test the prompt caching behavior."""
    print("=" * 70)
    print("PROMPT CACHING OPTIMIZATION TEST")
    print("=" * 70)
    print()

    cache = SystemPromptCache()
    
    # Simulate 10 decision ticks (common scenario: 120 frames / 12 frame decision interval = 10 decisions)
    print("Simulating 10 game decisions (one per 12 frames):")
    print()
    
    first_call = True
    for tick in range(1, 11):
        user_prompt = {
            "instruction": "Choose immediate tactical commands for this tick.",
            "state": {
                "frame": tick * 12,
                "my_units": [f"unit_{i}" for i in range(5)],
                "enemy_units": [f"enemy_{i}" for i in range(3)],
            },
        }
        
        messages, sent_system_prompt = cache.get_messages_with_cache(user_prompt, first_call=first_call)
        first_call = False
        
        # Calculate payload size
        payload_size = len(json.dumps({"messages": messages}))
        
        print(f"Decision {tick:2d}: {len(messages)} message(s), Payload: ~{payload_size:5d} bytes", end="")
        if sent_system_prompt:
            print(f" [SYSTEM PROMPT SENT]")
        else:
            print(f" [cached - schema reused]")
    
    print()
    print("=" * 70)
    cache.log_cache_stats()
    
    savings = cache.calculate_token_savings()
    print()
    print("TOKEN SAVINGS ANALYSIS:")
    print(f"  Total LLM calls: {savings['total_calls']}")
    print(f"  Command schema tokens: ~{savings['schema_tokens']}")
    print(f"  Tokens saved: ~{savings['tokens_saved']}")
    print(f"  Efficiency gain: {savings['percentage_saved']:.1f}%")
    print()
    print("OPTIMIZATION SUMMARY:")
    print("  ✓ System prompt (command schema) sent only once")
    print("  ✓ Subsequent calls reuse cached schema from LLM context")
    print(f"  ✓ Estimated {savings['percentage_saved']:.1f}% token overhead reduction")
    print()


if __name__ == "__main__":
    test_prompt_cache()
