import os
from typing import Dict, List, Optional
import json

class SystemPromptCache:
    """
    Cache for system prompt to avoid resending static command schema on every tick.
    This implements the optimization where:
    - System Prompt (static schema) is sent once and cached
    - User Message (dynamic game state) is sent every tick
    """

    def __init__(self, build_system_prompt_fn=None, llm_command_tutor="") -> None:
        self.build_system_prompt_fn = build_system_prompt_fn
        self.llm_command_tutor = llm_command_tutor
        
        if build_system_prompt_fn:
            self.cached_system_prompt = build_system_prompt_fn(llm_command_tutor)
        else:
            self.cached_system_prompt = llm_command_tutor
            
        self.use_cache = os.getenv("PROMPT_CACHE_ENABLED", "1") == "1"
        self.cache_stats = {"hits": 0, "sends": 0}

    def get_messages_with_cache(
        self, user_prompt: Dict, first_call: bool = False
    ) -> tuple:
        """
        Returns (messages list, should_send_system_prompt).
        
        If use_cache is True:
        - First call: Returns full messages with system prompt
        - Subsequent calls: Returns user message only (relies on LLM context retention)
        
        This reduces token overhead by not resending the static command schema.
        """
        if not self.use_cache or first_call:
            messages = [
                {"role": "system", "content": self.cached_system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))},
            ]
            self.cache_stats["sends"] += 1
            return messages, True

        # Subsequent calls: only send user message (relies on LLM keeping schema in context)
        messages = [
            {"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))}
        ]
        self.cache_stats["hits"] += 1
        return messages, False

    def log_cache_stats(self, game_log_fn) -> None:
        """Log cache efficiency statistics."""
        total = self.cache_stats["sends"] + self.cache_stats["hits"]
        if total > 0:
            efficiency = (self.cache_stats["hits"] / total) * 100
            game_log_fn(
                f"[CACHE STATS] System prompt sent {self.cache_stats['sends']} times, "
                f"reused {self.cache_stats['hits']} times (efficiency: {efficiency:.1f}%)"
            )

