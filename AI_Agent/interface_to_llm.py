"""
Local LLM planner for C&C Generals Zero Hour.

Provides LocalLlmPlanner class for interfacing with local Ollama endpoints
to generate RTS commands using LLM-based planning.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from AI_Agent.system_prompt_cache import SystemPromptCache
from dotenv import load_dotenv

from AI_Agent.game_logging import game_log as default_game_log
from AI_Agent.prompt_utils import (
    LLM_COMMAND_TUTOR,
    build_system_prompt_with_command_library,
)

load_dotenv()

class InterfaceToLlm:
    """
    Calls a local Ollama endpoint.

    Supported endpoint styles:
    - OpenAI-compatible: http://127.0.0.1:11434/v1/chat/completions
    - Native Ollama API: http://127.0.0.1:11434/api/chat

    Expected assistant content JSON shape:
    {
      "commands": [
        {"type":"attack_object","target_id":123,"unit_ids":[10,11]},
        {"type":"attack_move","x":1000,"y":2000,"z":0,"unit_ids":[10,11]}
      ]
    }

    Optimization:
    - Caches static command schema in system prompt (sent once)
    - Sends only dynamic game state in user messages (every tick)
    - Reduces token waste from redundant schema transmission
    """

    def __init__(
        self,
        game_log_fn=None,
        build_system_prompt_fn=None,
        llm_command_tutor: Optional[str] = None,
    ) -> None:
        self.game_log = game_log_fn or default_game_log
        build_prompt = build_system_prompt_fn or build_system_prompt_with_command_library
        prompt_tutor = LLM_COMMAND_TUTOR if llm_command_tutor is None else llm_command_tutor
        # Default ON for local Ollama usage; set LOCAL_AGENT=0 to disable.
        self.endpoint = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions")
        self.model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5-coder:1.5b-base")  # Use a smaller model for faster responses; adjust as needed
        # Default timeout increased to 30 seconds; adjust with LOCAL_LLM_TIMEOUT env var
        self.timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "60"))
        self.temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.0"))
        self.enable_thinking = os.getenv("LOCAL_LLM_THINK", "0") == "1"
        self.llm_debug = os.getenv("LLM_DEBUG", "0") == "1"
        self.llm_log_enabled = os.getenv("LLM_INTERACTION_LOG_ENABLED", "1") == "1"
        self.llm_log_file = os.getenv("LLM_INTERACTION_LOG_FILE", "AI_Agent//llm_interactions_log.txt")
        
        # Initialize prompt cache to avoid resending command schema every tick
        self.prompt_cache = SystemPromptCache(build_prompt, prompt_tutor)
        self.first_plan_call = True
        if self.llm_log_enabled:
            self._init_llm_interaction_log()

    def _init_llm_interaction_log(self) -> None:
        """Initialize LLM interaction log file for readable prompt/response tracing."""
        try:
            with open(self.llm_log_file, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 100 + "\n")
                f.write(f"LLM Interaction Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 100 + "\n")
        except Exception as exc:
            self.game_log(f"[LLM LOG] Failed to initialize '{self.llm_log_file}': {exc}")
            self.llm_log_enabled = False

    def _format_commands_readable(self, commands: List[Dict]) -> str:
        """Human-readable command summary for text logs."""
        if not commands:
            return "No valid commands."

        lines: List[str] = []
        for idx, cmd in enumerate(commands, 1):
            cmd_type = str(cmd.get("type", "")).strip()
            unit_ids = cmd.get("unit_ids", [])
            units_text = ",".join(str(u) for u in unit_ids) if isinstance(unit_ids, list) else "?"

            if cmd_type == "attack_object":
                target = cmd.get("target_id", "?")
                lines.append(f"{idx}. {cmd_type}: units [{units_text}] -> target {target}")
                lines.append(f"   command: {cmd_type} {units_text} {target}")
            elif cmd_type in {"select_unit", "select_units"}:
                lines.append(f"{idx}. {cmd_type}: units [{units_text}]")
                lines.append(f"   command: {cmd_type} {units_text}")
            elif cmd_type in {"construct", "build_structure", "build"}:
                template_id = cmd.get("template_id", "?")
                x = cmd.get("x", "?")
                y = cmd.get("y", "?")
                z = cmd.get("z", 0)
                lines.append(
                    f"{idx}. {cmd_type}: units [{units_text}] -> template {template_id} at ({x},{y},{z})"
                )
                lines.append(f"   command: construct {units_text} {template_id} {x} {y} {z}")
            else:
                x = cmd.get("x", "?")
                y = cmd.get("y", "?")
                z = cmd.get("z", 0)
                lines.append(f"{idx}. {cmd_type}: units [{units_text}] -> ({x},{y},{z})")
                lines.append(f"   command: {cmd_type} {units_text} {x} {y} {z}")
        return "\n".join(lines)

    def _log_llm_interaction(
        self,
        user_prompt: Dict,
        snapshot: Dict,
        sent_system_prompt: bool,
        system_prompt_text: str,
        raw_body: str,
        content: str,
        thinking_text: str,
        parsed_commands: List[Dict],
        error_text: Optional[str] = None,
    ) -> None:
        """Write one complete LLM interaction in readable text format."""
        if not self.llm_log_enabled:
            return

        frame_value = snapshot.get("f", snapshot.get("frame", "?"))
        try:
            with open(self.llm_log_file, "a", encoding="utf-8") as f:
                f.write("\n" + "-" * 100 + "\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Frame: {frame_value}\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Endpoint: {self.endpoint}\n")
                f.write(f"System Prompt Sent This Call: {sent_system_prompt}\n")

                f.write("\n[SYSTEM PROMPT SENT TO LLM]\n")
                if sent_system_prompt:
                    f.write((system_prompt_text or "(empty)") + "\n")
                else:
                    f.write("(not sent this call; prompt caching reused prior system prompt)\n")

                f.write("\n[USER PROMPT]\n")
                f.write(json.dumps(user_prompt, indent=2, ensure_ascii=False) + "\n")

                f.write("\n[STATE SNAPSHOT]\n")
                f.write(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")

                f.write("\n[LLM THINKING]\n")
                f.write((thinking_text or "(none)") + "\n")

                f.write("\n[LLM CONTENT]\n")
                f.write((content or "(none)") + "\n")

                f.write("\n[PARSED COMMANDS - READABLE]\n")
                f.write(self._format_commands_readable(parsed_commands) + "\n")

                f.write("\n[PARSED COMMANDS - JSON]\n")
                f.write(json.dumps(parsed_commands, indent=2, ensure_ascii=False) + "\n")

                if error_text:
                    f.write("\n[ERROR]\n")
                    f.write(error_text + "\n")

                f.write("\n[RAW LLM RESPONSE BODY]\n")
                f.write((raw_body or "(none)") + "\n")
        except Exception as exc:
            self.game_log(f"[LLM LOG] Failed to write '{self.llm_log_file}': {exc}")

    def _extract_json(self, text: str) -> Optional[Dict]:
        text = text.strip()
        if not text:
            self.game_log("[LLM JSON] Empty response text")
            return None

        if self.llm_debug:
            self.game_log(f"[LLM JSON] Attempting to extract JSON from {len(text)} chars")

        # Direct parse
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                if self.llm_debug:
                    self.game_log(f"[LLM JSON] Direct parse succeeded")
                return value
            if isinstance(value, list):
                if self.llm_debug:
                    self.game_log(f"[LLM JSON] Direct parse succeeded (top-level list)")
                return {"commands": value}
        except json.JSONDecodeError as e:
            if self.llm_debug:
                self.game_log(f"[LLM JSON] Direct parse failed: {e}")

        # Parse JSON block in fenced output
        if "```" in text:
            parts = text.split("```")
            for idx, part in enumerate(parts):
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                try:
                    value = json.loads(candidate)
                    if isinstance(value, dict):
                        if self.llm_debug:
                            self.game_log(f"[LLM JSON] Fenced block parse succeeded at part {idx}")
                        return value
                    if isinstance(value, list):
                        if self.llm_debug:
                            self.game_log(f"[LLM JSON] Fenced block parse succeeded as list at part {idx}")
                        return {"commands": value}
                except json.JSONDecodeError as e:
                    if self.llm_debug:
                        self.game_log(f"[LLM JSON] Fenced block part {idx} failed: {e}")
                    continue

        # Parse first object substring - with improved boundary detection
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            # Try to find the most complete JSON object by checking bracket balance
            open_count = 0
            best_end = -1
            
            for i in range(start, min(end + 1, len(text))):
                if text[i] == "{":
                    open_count += 1
                elif text[i] == "}":
                    open_count -= 1
                    if open_count == 0:
                        best_end = i
                        break  # Found first complete object
            
            if best_end > start:
                candidate_text = text[start : best_end + 1]
                if self.llm_debug:
                    self.game_log(f"[LLM JSON] Trying substring extraction: chars {start}-{best_end} ({len(candidate_text)} bytes)")
                
                try:
                    value = json.loads(candidate_text)
                    if isinstance(value, dict) and "commands" in value:
                        if self.llm_debug:
                            self.game_log(f"[LLM JSON] Substring parse succeeded with 'commands' key")
                        return value
                    elif isinstance(value, dict):
                        if self.llm_debug:
                            self.game_log(f"[LLM JSON] Substring parse succeeded but missing 'commands' key")
                except json.JSONDecodeError as e:
                    if self.llm_debug:
                        self.game_log(f"[LLM JSON] Substring parse failed: {e}")
                        self.game_log(f"[LLM JSON] Failed text: {candidate_text[:150]}...")

        # Parse first JSON array substring when model returns bare command arrays
        array_start = text.find("[")
        array_end = text.rfind("]")
        if array_start >= 0 and array_end > array_start:
            open_count = 0
            best_array_end = -1
            for i in range(array_start, min(array_end + 1, len(text))):
                if text[i] == "[":
                    open_count += 1
                elif text[i] == "]":
                    open_count -= 1
                    if open_count == 0:
                        best_array_end = i
                        break
            if best_array_end > array_start:
                array_text = text[array_start : best_array_end + 1]
                try:
                    value = json.loads(array_text)
                    if isinstance(value, list):
                        if self.llm_debug:
                            self.game_log(f"[LLM JSON] Array substring parse succeeded")
                        return {"commands": value}
                except json.JSONDecodeError as e:
                    if self.llm_debug:
                        self.game_log(f"[LLM JSON] Array substring parse failed: {e}")
        
        if self.llm_debug:
            self.game_log(f"[LLM JSON] All extraction methods exhausted. First 200 chars: {text[:200]}")
        return None

    def _attempt_format_repair(
        self,
        bad_content: str,
        base_system_prompt: str,
        use_native_ollama: bool,
    ) -> str:
        """Ask the model to rewrite malformed content into canonical command JSON."""
        if not bad_content.strip():
            return ""

        repair_system = (
            "You are a strict JSON reformatter for RTS commands. "
            "Return ONLY canonical JSON with this shape: "
            '{"commands":[{"type":"..."}]}. '
            "Use key 'type' only. No markdown. No explanations."
        )
        repair_user = (
            "Rewrite the following content into canonical JSON only.\n\n"
            "Rules:\n"
            "1) top-level key must be commands (array)\n"
            "2) convert action/build aliases to canonical type names\n"
            "3) if no valid command can be formed, return {\"commands\":[]}\n\n"
            f"System Prompt Context:\n{base_system_prompt}\n\n"
            f"Content to repair:\n{bad_content}"
        )

        messages = [
            {"role": "system", "content": repair_system},
            {"role": "user", "content": repair_user},
        ]

        if use_native_ollama:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.0},
                "think": False,
            }
        else:
            payload = {
                "model": self.model,
                "temperature": 0.0,
                "messages": messages,
            }

        req = urlrequest.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=min(self.timeout, 45.0)) as resp:
                repair_body = resp.read().decode("utf-8", errors="replace")
            repair_result = json.loads(repair_body)
            if use_native_ollama:
                return str(repair_result.get("message", {}).get("content", "") or "")
            return str(repair_result.get("choices", [{}])[0].get("message", {}).get("content", "") or "")
        except Exception as exc:
            if self.llm_debug:
                self.game_log(f"[LLM REPAIR] Failed: {exc}")
            return ""

    def plan(self, snapshot: Dict) -> List[Dict]:
        user_prompt = {
            "instruction": (
            "Balance economy, production, expansion, scouting, defense, "
            "army control, and combat efficiency. "
            "Prefer high-value actions that improve strategic position. "
            "Preserve important units while maintaining map control and resource income. "
            "Avoid useless, repetitive, or low-impact commands. "
            "Do not interrupt effective ongoing actions unless necessary. "
            "Prefer stable coordinated behavior over constant retargeting."
            "Choose the best RTS actions for the current game state. "
            "Return ONLY canonical JSON with top-level {'commands': [...]} and canonical key 'type'. "
            "Do not output markdown or prose. "
            "For build actions, use only type='construct' with numeric template_id from state.build_catalog. "
            "Do not guess template_id. "
            "Use short, high-impact command sequences."
            ),
            "state": snapshot,
        }

        # Use cached system prompt to avoid resending command schema every tick
        messages, sent_system_prompt = self.prompt_cache.get_messages_with_cache(
            user_prompt, first_call=self.first_plan_call
        )
        system_prompt_text = (
            str(messages[0].get("content", ""))
            if sent_system_prompt and messages and messages[0].get("role") == "system"
            else ""
        )
        if self.first_plan_call:
            self.first_plan_call = False

        use_native_ollama = "/api/chat" in self.endpoint.lower()
        if use_native_ollama:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.temperature},
                "think": self.enable_thinking,
            }
        else:
            payload = {
                "model": self.model,
                "temperature": self.temperature,
                "messages": messages,
            }

        if self.llm_debug:
            self.game_log(f"[LLM DEBUG] Sending request to: {self.endpoint}")
            self.game_log(f"[LLM DEBUG] Model: {self.model}")
            self.game_log(f"[LLM DEBUG] Timeout: {self.timeout}s")
            self.game_log(f"[LLM DEBUG] Temperature: {self.temperature}, Thinking: {self.enable_thinking}")
            self.game_log(f"[LLM DEBUG] System prompt sent: {sent_system_prompt} (messages: {len(messages)})")
            self.game_log(f"[LLM DEBUG] Payload size: {len(json.dumps(payload))} bytes")
            my_units_count = len(snapshot.get("my_units", snapshot.get("my_units", [])))
            enemy_units_count = len(snapshot.get("enemy_units", snapshot.get("enemy_units", [])))
            objects_count = len(snapshot.get("objects_in_prompt", snapshot.get("objects_in_prompt", [])))
            civilian_objects_count = len(snapshot.get("civilian_objects", snapshot.get("civilian_objects", [])))
            self.game_log(
                f"[LLM DEBUG] Snapshot - my_units: {my_units_count}, "
                f"enemy_units: {enemy_units_count}, objects: {objects_count}, "
                f"civilian_objects: {civilian_objects_count}"
            )

        req = urlrequest.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        body = ""
        content = ""
        thinking_text = ""

        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urlerror.HTTPError as http_err:
            self.game_log(f"Local LLM HTTP Error {http_err.code}: {http_err.reason} - Check if Ollama is running and endpoint is correct")
            self.game_log(f"  Endpoint: {self.endpoint}")
            self.game_log(f"  Model: {self.model}")
            self.game_log(f"  Timeout: {self.timeout}s (increase with LOCAL_LLM_TIMEOUT env var)")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"HTTP Error {http_err.code}: {http_err.reason}",
            )
            return []
        except TimeoutError as exc:
            self.game_log(f"Local LLM timeout ({self.timeout}s): {exc}")
            self.game_log(f"  The LLM is taking too long. Try:")
            self.game_log(f"  1. Increase timeout: set LOCAL_LLM_TIMEOUT=60")
            self.game_log(f"  2. Use a faster model: ollama pull mistral:7b")
            self.game_log(f"  3. Check Ollama: curl http://127.0.0.1:11434/api/tags")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Timeout Error: {exc}",
            )
            return []
        except (urlerror.URLError, OSError) as exc:
            self.game_log(f"Local LLM unavailable: {exc}")
            self.game_log(f"  Check if Ollama is running: ollama serve")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Connection Error: {exc}",
            )
            return []

        if self.llm_debug:
            self.game_log(f"[LLM RESPONSE] Raw response body ({len(body)} bytes): {body[:300]}..." if len(body) > 300 else f"[LLM RESPONSE] Raw response body: {body}")

        try:
            result = json.loads(body)
            if use_native_ollama:
                content = result["message"]["content"]
                thinking_text = str(result.get("message", {}).get("thinking", "") or result.get("thinking", ""))
            else:
                content = result["choices"][0]["message"]["content"]
                choice_msg = result.get("choices", [{}])[0].get("message", {})
                thinking_text = str(choice_msg.get("thinking", "") or result.get("thinking", ""))
            if self.llm_debug:
                self.game_log(f"[LLM RESPONSE] Extracted content ({len(content)} bytes): {content[:200]}..." if len(content) > 200 else f"[LLM RESPONSE] Extracted content: {content}")
                self.game_log(f"[LLM RESPONSE] thinking trace (if available): {thinking_text if thinking_text else 'N/A'}")
        except Exception as e:
            self.game_log(f"Local LLM response format unexpected: {e}")
            if self.llm_debug:
                self.game_log(f"[LLM RESPONSE] Failed to extract content. Full body: {body[:500]}")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Response format error: {e}",
            )
            return []

        parsed = self._extract_json(content)
        if not parsed:
            repaired_content = self._attempt_format_repair(
                bad_content=content,
                base_system_prompt=self.prompt_cache.cached_system_prompt,
                use_native_ollama=use_native_ollama,
            )
            if repaired_content:
                repaired = self._extract_json(repaired_content)
                if repaired:
                    parsed = repaired
                    content = repaired_content
                else:
                    self.game_log("Local LLM did not return parseable JSON commands")
                    if self.llm_debug:
                        self.game_log(f"[LLM RESPONSE] Content that failed JSON parsing: {content[:500]}")
                    self._log_llm_interaction(
                        user_prompt=user_prompt,
                        snapshot=snapshot,
                        sent_system_prompt=sent_system_prompt,
                        system_prompt_text=system_prompt_text,
                        raw_body=body,
                        content=content,
                        thinking_text=thinking_text,
                        parsed_commands=[],
                        error_text="Parse error: Could not extract JSON commands from content",
                    )
                    return []
            else:
                self.game_log("Local LLM did not return parseable JSON commands")
                if self.llm_debug:
                    self.game_log(f"[LLM RESPONSE] Content that failed JSON parsing: {content[:500]}")
                self._log_llm_interaction(
                    user_prompt=user_prompt,
                    snapshot=snapshot,
                    sent_system_prompt=sent_system_prompt,
                    system_prompt_text=system_prompt_text,
                    raw_body=body,
                    content=content,
                    thinking_text=thinking_text,
                    parsed_commands=[],
                    error_text="Parse error: Could not extract JSON commands from content",
                )
                return []

        # Accept flexible response formats:
        # - {"commands":[...]}
        # - {"actions":[...]}
        # - [ ...commands... ]
        # - single command object
        commands: List = []
        if isinstance(parsed, dict):
            candidate = parsed.get("commands")
            if candidate is None:
                candidate = parsed.get("actions")
            if candidate is None and any(k in parsed for k in ("type", "action", "command")):
                candidate = [parsed]
            if not isinstance(candidate, list):
                self.game_log(f"Local LLM commands payload is not a list, got {type(candidate).__name__}")
                self._log_llm_interaction(
                    user_prompt=user_prompt,
                    snapshot=snapshot,
                    sent_system_prompt=sent_system_prompt,
                    system_prompt_text=system_prompt_text,
                    raw_body=body,
                    content=content,
                    thinking_text=thinking_text,
                    parsed_commands=[],
                    error_text=f"Commands payload is not a list (got {type(candidate).__name__})",
                )
                return []
            commands = candidate
        elif isinstance(parsed, list):
            commands = parsed
        else:
            self.game_log(f"Local LLM response is unsupported type: {type(parsed).__name__}")
            self._log_llm_interaction(
                user_prompt=user_prompt,
                snapshot=snapshot,
                sent_system_prompt=sent_system_prompt,
                system_prompt_text=system_prompt_text,
                raw_body=body,
                content=content,
                thinking_text=thinking_text,
                parsed_commands=[],
                error_text=f"Unsupported parsed type: {type(parsed).__name__}",
            )
            return []
        
        if not commands:
            if self.llm_debug:
                self.game_log("[LLM] Empty commands list returned")

        safe_commands: List[Dict] = []
        max_commands = max(1, int(os.getenv("LLM_MAX_COMMANDS_PER_TICK", "8")))
        for cmd in commands[:max_commands]:
            if not isinstance(cmd, dict):
                continue
            normalized = dict(cmd)
            cmd_type = str(
                normalized.get("type")
                or normalized.get("action")
                or normalized.get("command")
                or ""
            ).strip().lower()
            if not cmd_type:
                continue

            normalized["type"] = cmd_type
            if "action" in normalized:
                del normalized["action"]
            if "command" in normalized:
                del normalized["command"]

            if "unit_id" in normalized and "unit_ids" not in normalized:
                unit_id = normalized.get("unit_id")
                if isinstance(unit_id, (int, float)):
                    normalized["unit_ids"] = [int(unit_id)]

            safe_commands.append(normalized)

        self._log_llm_interaction(
            user_prompt=user_prompt,
            snapshot=snapshot,
            sent_system_prompt=sent_system_prompt,
            system_prompt_text=system_prompt_text,
            raw_body=body,
            content=content,
            thinking_text=thinking_text,
            parsed_commands=safe_commands,
            error_text=None,
        )

        return safe_commands
