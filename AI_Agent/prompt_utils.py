import json
import os
from typing import Dict, List

from dotenv import load_dotenv

from AI_Agent.game_logging import game_log

load_dotenv()

DEFAULT_SYSTEM_PROMPT_PATH = "AI_Agent/system_prompt.txt"
DEFAULT_COMMAND_LIBRARY_PATH = "AI_Agent/Commands_Library.json"


def _load_system_prompt(path: str) -> str:
    """Load base system prompt text from file."""
    with open(path, "r", encoding="utf-8") as f:
        prompt_text = f.read().strip()

    if not prompt_text:
        raise ValueError(f"System prompt file '{path}' is empty")

    return prompt_text


def _load_command_library(path: str) -> List[Dict]:
    """Load command definitions from Commands_Library.json."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        game_log(f"[PROMPT] Could not load command library '{path}': {exc}")
        return []

    if not isinstance(payload, list):
        game_log(f"[PROMPT] Command library '{path}' must be a JSON array")
        return []

    commands: List[Dict] = []
    for item in payload:
        if isinstance(item, dict) and item.get("command"):
            commands.append(item)
    return commands


def _build_command_library_section(commands: List[Dict]) -> str:
    """Render command library as prompt text."""
    lines = [
        "AVAILABLE COMMAND LIBRARY (use these command names/arguments when possible):"
    ]
    for entry in commands:
        command = str(entry.get("command", "")).strip()
        message_type = entry.get("message_type", "?")
        args = entry.get("args", [])
        if isinstance(args, list):
            args_text = ", ".join(str(arg) for arg in args) if args else "none"
        else:
            args_text = str(args)
        description = str(entry.get("description", "")).replace("\n", " ").strip()
        lines.append(
            f"- {command}: message_type={message_type}, args=[{args_text}], description={description}"
        )
    return "\n".join(lines)


def build_system_prompt_with_command_library(base_prompt: str) -> str:
    """
    Build final system prompt by appending Commands_Library.json content.
    Controls:
    - COMMAND_LIBRARY_PATH (default: AI_Agent/Commands_Library.json)
    - SYSTEM_PROMPT_INCLUDE_COMMAND_LIBRARY=0 to disable
    - SYSTEM_PROMPT_COMMAND_LIMIT (default: 120)
    """
    if os.getenv("SYSTEM_PROMPT_INCLUDE_COMMAND_LIBRARY", "1") != "1":
        return base_prompt

    path = os.getenv("COMMAND_LIBRARY_PATH", DEFAULT_COMMAND_LIBRARY_PATH)
    try:
        limit = max(1, int(os.getenv("SYSTEM_PROMPT_COMMAND_LIMIT", "120")))
    except ValueError:
        limit = 120

    commands = _load_command_library(path)
    if not commands:
        return base_prompt

    selected = commands[:limit]
    game_log(f"[PROMPT] Added {len(selected)} commands from '{path}' to system prompt")
    return f"{base_prompt}\n\n{_build_command_library_section(selected)}"


_system_prompt_path = os.getenv("SYSTEM_PROMPT_PATH", DEFAULT_SYSTEM_PROMPT_PATH)
LLM_COMMAND_TUTOR = _load_system_prompt(_system_prompt_path)
