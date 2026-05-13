#!/usr/bin/env python3
"""
Extract object template names from C&C Generals / Zero Hour game data.

Supports:
1) Extracted INI directories
2) BIG archives (e.g. INIZH.big) directly

Typical usage:
  python AI_Agent/utils_mm/extract_template_names.py --ini-root "C:\\Games\\Zero Hour\\Data\\INI" --out logs\\all_templates.txt
  python AI_Agent/utils_mm/extract_template_names.py --big-file "F:\\Games\\...\\Data\\INI\\INIZH.big" --out logs\\all_templates.txt
  python AI_Agent/utils_mm/extract_template_names.py --big-file "F:\\Games\\...\\INIZH.big" --prefixes America China GLA --out logs\\army_templates.txt
  python AI_Agent/utils_mm/extract_template_names.py --big-file "F:\\Games\\...\\INIZH.big" --list-entries --out logs\\inizh_entries.txt
  python AI_Agent/utils_mm/extract_template_names.py --big-file "F:\Games\Command and Conquer - Generals\Command and Conquer Generals Zero Hour\Data\INI\INIZH.big" --list-entries --entry-contains ".ini" --out "logs\\inizh_ini_entries.txt"
  """

from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path
from typing import Iterable, List, Set, Tuple


# Common INI declarations that carry template names.
OBJECT_RE = re.compile(r"^\s*Object\s+([A-Za-z0-9_]+)\b")
CHILD_OBJECT_RE = re.compile(r"^\s*ChildObject\s+([A-Za-z0-9_]+)\b")


def iter_ini_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.ini"):
        if path.is_file():
            yield path


def extract_names_from_file(path: Path) -> Set[str]:
    names: Set[str] = set()
    try:
        content = path.read_text(encoding="latin-1", errors="ignore")
    except OSError:
        return names

    for line in content.splitlines():
        m = OBJECT_RE.match(line)
        if m:
            names.add(m.group(1))
            continue
        m = CHILD_OBJECT_RE.match(line)
        if m:
            names.add(m.group(1))
    return names


def _read_c_string(data: bytes, start: int) -> Tuple[str, int]:
    end = data.find(b"\x00", start)
    if end == -1:
        raise ValueError("Malformed BIG directory entry: missing string terminator")
    return data[start:end].decode("latin-1", errors="ignore"), end + 1


def _parse_big_entries(blob: bytes) -> List[Tuple[int, int, str]]:
    # Matches Win32BIGFileSystem.cpp behavior:
    # - magic "BIGF"
    # - file count read as big-endian
    # - directory starts at offset 0x10
    if len(blob) < 0x10 or blob[:4] != b"BIGF":
        raise ValueError("Not a BIGF archive")

    file_count = struct.unpack(">I", blob[8:12])[0]
    cursor = 0x10
    entries: List[Tuple[int, int, str]] = []

    for _ in range(file_count):
        if cursor + 8 > len(blob):
            raise ValueError("Malformed BIG archive: truncated directory entry")
        file_offset = struct.unpack(">I", blob[cursor : cursor + 4])[0]
        file_size = struct.unpack(">I", blob[cursor + 4 : cursor + 8])[0]
        cursor += 8
        name, cursor = _read_c_string(blob, cursor)
        entries.append((file_offset, file_size, name))

    return entries


def extract_names_from_big(path: Path) -> Tuple[Set[str], int]:
    names: Set[str] = set()
    ini_entries = 0
    blob = path.read_bytes()
    entries = _parse_big_entries(blob)

    for file_offset, file_size, internal_name in entries:
        if not internal_name.lower().endswith(".ini"):
            continue
        ini_entries += 1
        if file_offset < 0 or file_size < 0 or file_offset + file_size > len(blob):
            # Skip malformed entries safely.
            continue
        ini_data = blob[file_offset : file_offset + file_size]
        text = ini_data.decode("latin-1", errors="ignore")
        for line in text.splitlines():
            m = OBJECT_RE.match(line)
            if m:
                names.add(m.group(1))
                continue
            m = CHILD_OBJECT_RE.match(line)
            if m:
                names.add(m.group(1))

    return names, ini_entries


def list_big_entries(path: Path) -> List[str]:
    blob = path.read_bytes()
    entries = _parse_big_entries(blob)
    return [name for _, _, name in entries]


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract template names from INI game data.")
    parser.add_argument("--ini-root", default="", help="Root folder that contains extracted game INI files.")
    parser.add_argument(
        "--big-file",
        action="append",
        default=[],
        help="Path to BIG archive (can be passed multiple times), e.g. INIZH.big.",
    )
    parser.add_argument(
        "--prefixes",
        nargs="*",
        default=[],
        help="Optional name prefixes to keep (example: America China GLA).",
    )
    parser.add_argument(
        "--list-entries",
        action="store_true",
        help="List internal file entries from BIG archives instead of extracting template names.",
    )
    parser.add_argument(
        "--entry-contains",
        default="",
        help="When used with --list-entries, only keep entries containing this substring (case-insensitive).",
    )
    parser.add_argument("--out", default="", help="Optional output file path. If omitted, prints to stdout.")
    args = parser.parse_args()

    names: Set[str] = set()
    listed_entries: List[str] = []
    ini_count = 0
    big_ini_count = 0

    if args.ini_root:
        root = Path(args.ini_root)
        if not root.exists() or not root.is_dir():
            raise SystemExit(f"INI root does not exist or is not a directory: {root}")
        for ini_path in iter_ini_files(root):
            ini_count += 1
            names.update(extract_names_from_file(ini_path))

    if args.big_file:
        for big_str in args.big_file:
            big_path = Path(big_str)
            if not big_path.exists() or not big_path.is_file():
                raise SystemExit(f"BIG file does not exist or is not a file: {big_path}")
            if args.list_entries:
                big_entries = list_big_entries(big_path)
                listed_entries.extend(big_entries)
                continue
            big_names, big_inis = extract_names_from_big(big_path)
            names.update(big_names)
            big_ini_count += big_inis

    if not args.ini_root and not args.big_file:
        raise SystemExit("Please provide --ini-root and/or --big-file.")

    if args.list_entries:
        if args.ini_root:
            raise SystemExit("--list-entries currently works with --big-file input only.")
        entries = listed_entries
        if args.entry_contains:
            needle = args.entry_contains.lower()
            entries = [e for e in entries if needle in e.lower()]
        entries = sorted(set(entries))
        output = "\n".join(entries)
        if args.out:
            out_path = Path(args.out)
            out_path.write_text(output + ("\n" if output else ""), encoding="utf-8")
            print(f"Listed {len(entries)} BIG entries. Saved to: {out_path}")
        else:
            print(output)
            print(f"\n# Listed {len(entries)} BIG entries.")
        return 0

    filtered = sorted(names)
    if args.prefixes:
        prefixes = tuple(args.prefixes)
        filtered = [n for n in filtered if n.startswith(prefixes)]

    output = "\n".join(filtered)
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(output + ("\n" if output else ""), encoding="utf-8")
        print(
            f"Scanned {ini_count} extracted INI files and {big_ini_count} INI entries in BIG archives; "
            f"found {len(filtered)} template names. "
            f"Saved to: {out_path}"
        )
    else:
        print(output)
        print(
            f"\n# Scanned {ini_count} extracted INI files and {big_ini_count} INI entries in BIG archives; "
            f"found {len(filtered)} template names."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
