#!/usr/bin/env python3
"""Convert CC-CEDICT to a simple glossary file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

CEDICT_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[[^\]]+\]\s+/(.+)/$")


def clean_definition(definition: str) -> str:
    parts = [part.strip() for part in definition.split("/") if part.strip()]
    parts = [part for part in parts if not part.lower().startswith("variant of ")]
    return "; ".join(parts[:4])


def convert(input_path: Path, output_path: Path) -> int:
    count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8", errors="replace") as src, output_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as dst:
        dst.write("# CC-CEDICT\n")
        dst.write("# Direction: zh -> en\n")
        dst.write("# License: Creative Commons Attribution-ShareAlike 4.0 International\n")
        dst.write("# Format: source = target\n")
        for raw_line in src:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = CEDICT_RE.match(line)
            if not match:
                continue
            traditional, simplified, definition = match.groups()
            target = clean_definition(definition)
            if not target:
                continue
            sources = [simplified]
            if traditional != simplified:
                sources.append(traditional)
            for source in sources:
                dst.write(f"{source} = {target}\n")
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    count = convert(args.input, args.output)
    print(f"Wrote {count} entries to {args.output}")


if __name__ == "__main__":
    main()
