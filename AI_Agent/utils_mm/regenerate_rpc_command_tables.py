#!/usr/bin/env python3
"""
Regenerate the command ID tables in RPC_COMMANDS_REFERENCE.md from GameMessage::Type.

Usage:
  python AI_Agent/utils_mm/regenerate_rpc_command_tables.py
  python AI_Agent/utils_mm/regenerate_rpc_command_tables.py --check
  python AI_Agent/utils_mm/regenerate_rpc_command_tables.py --header <path> --reference <path>
"""

from __future__ import annotations

import argparse
import ast
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


AUTO_START = "<!-- AUTO-GENERATED:COMMAND_TABLES:START -->"
AUTO_END = "<!-- AUTO-GENERATED:COMMAND_TABLES:END -->"


@dataclass(frozen=True)
class CommandRow:
    command: str
    args: str
    purpose: str


@dataclass(frozen=True)
class CommandRangeRow:
    start: str
    end: str
    label: str
    args: str
    purpose: str


@dataclass(frozen=True)
class Category:
    title: str
    rows: Tuple[object, ...]


CATEGORIES: Tuple[Category, ...] = (
    Category(
        title="Movement Commands",
        rows=(
            CommandRow("MSG_DO_MOVETO", "`location`", "Move selected units"),
            CommandRow("MSG_DO_ATTACKMOVETO", "`location`", "Move and attack en route"),
            CommandRow("MSG_DO_FORCEMOVETO", "`location`", "Force move"),
            CommandRow("MSG_ADD_WAYPOINT", "`location`", "Add waypoint"),
            CommandRow("MSG_DO_GUARD_POSITION", "`location`", "Guard a position"),
            CommandRow("MSG_DO_GUARD_OBJECT", "`integer` (object id)", "Guard an object"),
            CommandRow("MSG_DO_STOP", "-", "Stop selected units"),
            CommandRow("MSG_DO_SCATTER", "-", "Scatter selected units"),
            CommandRow("MSG_CREATE_FORMATION", "-", "Formation command"),
        ),
    ),
    Category(
        title="Combat Commands",
        rows=(
            CommandRow("MSG_DO_ATTACK_OBJECT", "`integer` (object id)", "Attack target object"),
            CommandRow(
                "MSG_DO_FORCE_ATTACK_OBJECT",
                "`integer` (object id)",
                "Force-attack target object",
            ),
            CommandRow("MSG_DO_FORCE_ATTACK_GROUND", "`location`", "Attack ground location"),
            CommandRow("MSG_DO_ATTACKSQUAD", "command-specific", "Attack squad command"),
        ),
    ),
    Category(
        title="Building Commands",
        rows=(
            CommandRow(
                "MSG_DOZER_CONSTRUCT",
                "`integer` (template id), `location`",
                "Build structure",
            ),
            CommandRow("MSG_DOZER_CONSTRUCT_LINE", "command-specific", "Line construction"),
            CommandRow("MSG_DOZER_CANCEL_CONSTRUCT", "command-specific", "Cancel construction"),
            CommandRow("MSG_SELL", "`integer` (object id)", "Sell structure"),
            CommandRow("MSG_DO_REPAIR", "`integer` (object id)", "Repair target"),
            CommandRow(
                "MSG_RESUME_CONSTRUCTION",
                "`integer` (object id)",
                "Resume construction",
            ),
            CommandRow("MSG_SET_RALLY_POINT", "command-specific", "Set rally point"),
        ),
    ),
    Category(
        title="Transportation / Utility Commands",
        rows=(
            CommandRow("MSG_EXIT", "-", "Exit garrison/transport"),
            CommandRow("MSG_EVACUATE", "command-specific", "Evacuate contents"),
            CommandRow(
                "MSG_GET_REPAIRED",
                "`integer` (object id)",
                "Go to repair facility",
            ),
            CommandRow("MSG_GET_HEALED", "`integer` (object id)", "Go to healing facility"),
            CommandRow(
                "MSG_ENTER",
                "`integer` (object id)",
                "Enter transport/building",
            ),
            CommandRow("MSG_DOCK", "`integer` (object id)", "Dock at target"),
        ),
    ),
    Category(
        title="Special Powers",
        rows=(
            CommandRow("MSG_DO_SPECIAL_POWER", "command-specific", "Special power command"),
            CommandRow(
                "MSG_DO_SPECIAL_POWER_AT_LOCATION",
                "`integer` (power id), `location`",
                "Use power at location",
            ),
            CommandRow(
                "MSG_DO_SPECIAL_POWER_AT_OBJECT",
                "`integer` (power id), `integer` (object id)",
                "Use power on object",
            ),
        ),
    ),
    Category(
        title="Unit Group Management",
        rows=(
            CommandRow("MSG_CREATE_SELECTED_GROUP", "command-specific", "Create control group"),
            CommandRangeRow(
                start="MSG_SELECT_TEAM0",
                end="MSG_SELECT_TEAM9",
                label="`MSG_SELECT_TEAM0`-`MSG_SELECT_TEAM9`",
                args="-",
                purpose="Select control group",
            ),
            CommandRangeRow(
                start="MSG_ADD_TEAM0",
                end="MSG_ADD_TEAM9",
                label="`MSG_ADD_TEAM0`-`MSG_ADD_TEAM9`",
                args="-",
                purpose="Add control group to selection",
            ),
        ),
    ),
)


class ExpressionEvaluator(ast.NodeVisitor):
    _binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.BitOr: operator.or_,
        ast.BitAnd: operator.and_,
        ast.BitXor: operator.xor,
        ast.LShift: operator.lshift,
        ast.RShift: operator.rshift,
    }
    _unary_ops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
        ast.Invert: operator.invert,
    }

    def __init__(self, names: Dict[str, int]):
        self.names = names

    def visit_Expression(self, node: ast.Expression) -> int:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> int:
        if not isinstance(node.value, int):
            raise ValueError(f"Unsupported constant: {node.value!r}")
        return int(node.value)

    def visit_Name(self, node: ast.Name) -> int:
        if node.id not in self.names:
            raise ValueError(f"Unknown enum reference: {node.id}")
        return self.names[node.id]

    def visit_BinOp(self, node: ast.BinOp) -> int:
        op = self._binary_ops.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> int:
        op = self._unary_ops.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op(self.visit(node.operand))

    def generic_visit(self, node: ast.AST) -> int:
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def eval_enum_expr(expr: str, known: Dict[str, int]) -> int:
    tree = ast.parse(expr, mode="eval")
    evaluator = ExpressionEvaluator(known)
    value = evaluator.visit(tree)
    if not isinstance(value, int):
        raise ValueError(f"Enum expression is not an int: {expr}")
    return value


def extract_enum_type_block(source: str) -> str:
    game_message_match = re.search(r"\bclass\s+GameMessage\b", source)
    if not game_message_match:
        raise ValueError("Could not find 'class GameMessage' in header.")

    enum_match = re.search(r"\benum\s+Type\b", source[game_message_match.end() :])
    if not enum_match:
        raise ValueError("Could not find 'enum Type' in header.")
    enum_offset = game_message_match.end() + enum_match.start()

    brace_start = source.find("{", enum_offset)
    if brace_start == -1:
        raise ValueError("Could not find '{' for enum Type.")

    depth = 0
    for i in range(brace_start, len(source)):
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : i]

    raise ValueError("Could not find closing '}' for enum Type.")


def strip_c_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    return text


def parse_enum_values(enum_block: str) -> Dict[str, int]:
    enum_block = re.sub(r"//.*", "", enum_block)
    enum_block = re.sub(r"/\*.*?\*/", "", enum_block, flags=re.DOTALL)
    values: Dict[str, int] = {}
    current = -1

    for raw_line in enum_block.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = re.match(r"^(MSG_[A-Z0-9_]+)\s*(?:=\s*([^,]+))?\s*,?$", line)
        if not m:
            continue

        name = m.group(1)
        expr = m.group(2)
        if expr is None:
            current += 1
        else:
            current = eval_enum_expr(expr.strip(), values)
        values[name] = current

    if not values:
        raise ValueError("No MSG_* values parsed from enum Type block.")
    return values


def row_to_markdown(row: object, enum_values: Dict[str, int]) -> str:
    if isinstance(row, CommandRow):
        value = enum_values.get(row.command)
        if value is None:
            raise ValueError(f"Missing enum value for {row.command}")
        return f"| `{row.command}` | {value} | {row.args} | {row.purpose} |"

    if isinstance(row, CommandRangeRow):
        start = enum_values.get(row.start)
        end = enum_values.get(row.end)
        if start is None or end is None:
            raise ValueError(f"Missing enum value for range {row.start}..{row.end}")
        return f"| {row.label} | {start}-{end} | {row.args} | {row.purpose} |"

    raise TypeError(f"Unsupported row type: {type(row)}")


def build_generated_command_section(enum_values: Dict[str, int], header_path: Path) -> str:
    lines: List[str] = []
    lines.append("## Command Categories (Verified IDs)")
    lines.append("")
    lines.append(AUTO_START)
    lines.append(
        f"Generated from `{header_path.as_posix()}` by "
        f"`python utils_mm/regenerate_rpc_command_tables.py`."
    )
    lines.append("")

    for category in CATEGORIES:
        lines.append(f"### {category.title}")
        lines.append("")
        lines.append("| Command | Type | Arguments | Purpose |")
        lines.append("|---|---:|---|---|")
        for row in category.rows:
            lines.append(row_to_markdown(row, enum_values))
        lines.append("")

    lines.append(AUTO_END)
    return "\n".join(lines).rstrip() + "\n"


def replace_command_section(reference_text: str, generated_section: str) -> str:
    pattern = re.compile(
        r"## Command Categories \(Verified IDs\)\s*.*?(?=^## Argument Type Reference)",
        re.DOTALL | re.MULTILINE,
    )
    if not pattern.search(reference_text):
        raise ValueError(
            "Could not find command categories section. Expected heading "
            "'## Command Categories (Verified IDs)'."
        )
    return pattern.sub(generated_section + "\n", reference_text, count=1)


def compute_updated_reference(reference_path: Path, header_path: Path) -> str:
    header_text = header_path.read_text(encoding="utf-8", errors="replace")
    enum_block = extract_enum_type_block(header_text)
    enum_values = parse_enum_values(enum_block)
    generated = build_generated_command_section(enum_values, header_path)

    reference_text = reference_path.read_text(encoding="utf-8", errors="replace")
    return replace_command_section(reference_text, generated)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate RPC command ID tables in RPC_COMMANDS_REFERENCE.md "
            "from MessageStream.h enum values."
        )
    )
    parser.add_argument(
        "--header",
        type=Path,
        default=Path("GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h"),
        help="Path to MessageStream.h",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("RPC_COMMANDS_REFERENCE.md"),
        help="Path to RPC command reference markdown file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the reference file is up to date (non-zero exit if not).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.header.exists():
        raise FileNotFoundError(f"Header not found: {args.header}")
    if not args.reference.exists():
        raise FileNotFoundError(f"Reference markdown not found: {args.reference}")

    updated = compute_updated_reference(args.reference, args.header)
    current = args.reference.read_text(encoding="utf-8", errors="replace")

    if args.check:
        if current != updated:
            print("RPC command table is out of date.")
            print("Run: python utils_mm/regenerate_rpc_command_tables.py")
            return 1
        print("RPC command table is up to date.")
        return 0

    if current == updated:
        print("No changes needed. RPC command table already up to date.")
        return 0

    args.reference.write_text(updated, encoding="utf-8")
    print(f"Updated {args.reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
