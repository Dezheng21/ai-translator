#!/usr/bin/env python3
"""Convert Microsoft Terminology TBX files to simple glossary files."""

from __future__ import annotations

import argparse
import html
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def terms_for_lang(term_entry: ET.Element, lang: str) -> list[str]:
    terms: list[str] = []
    for lang_set in term_entry.findall("langSet"):
        if lang_set.attrib.get(XML_LANG) != lang:
            continue
        for term in lang_set.findall(".//term"):
            value = clean(term.text or "")
            if value:
                terms.append(value)
    return terms


def convert_tbx(input_path: Path, output_path: Path, target_lang: str) -> int:
    mapping: dict[str, set[str]] = defaultdict(set)
    for _event, elem in ET.iterparse(str(input_path), events=("end",)):
        if elem.tag != "termEntry":
            continue
        en_terms = terms_for_lang(elem, "en-US")
        target_terms = terms_for_lang(elem, target_lang)
        for source in en_terms:
            for target in target_terms:
                if source and target and source != target:
                    mapping[source].add(target)
        elem.clear()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Microsoft Terminology Collection\n")
        f.write("# Source: MicrosoftTermCollection.zip\n")
        f.write("# Format: source = target\n")
        for source in sorted(mapping, key=lambda s: (s.lower(), s)):
            targets = "; ".join(sorted(mapping[source]))
            f.write(f"{source} = {targets}\n")
    return len(mapping)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target-lang", default="zh-Hans")
    args = parser.parse_args()
    count = convert_tbx(args.input, args.output, args.target_lang)
    print(f"Wrote {count} entries to {args.output}")


if __name__ == "__main__":
    main()
