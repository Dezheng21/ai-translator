#!/usr/bin/env python3
"""
Translate text or Markdown files with mainstream AI APIs.

Supported providers:
- openai: OpenAI Responses API
- anthropic: Anthropic Messages API
- gemini: Google Gemini generateContent API
- deepseek: DeepSeek Chat Completions API
- openai-compatible: any OpenAI-compatible /chat/completions endpoint

API keys are read from environment variables. See tools/translate_ai_README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_MODELS = {
    "openai": "gpt-5.6-luna",
    "anthropic": "claude-sonnet-4-5",
    "gemini": "gemini-3.5-flash",
    "deepseek": "deepseek-chat",
    "openai-compatible": "default",
}

STYLE_INSTRUCTIONS = {
    "literal": "忠实翻译原文，尽量保留原文概念、逻辑顺序和术语。",
    "readable": "忠实翻译原文，但使用自然、顺畅的中文表达。拆开过长句子，减少翻译腔。",
    "academic": "以学术中文翻译。术语稳定，论证关系清楚，句子可读但不口语化。",
    "polished": "先忠实翻译，再做轻度润色，使中文流畅、清楚、有出版物质感。",
}

QUALITY_INSTRUCTIONS = {
    "fast": "快速水准：优先完成速度和基本准确性，保持结构，不做过度润色。",
    "standard": "标准水准：兼顾准确、流畅和术语一致性，适合一般阅读。",
    "high": "高质量水准：逐句处理复杂逻辑，主动消除翻译腔，保持术语一致和论证清楚。",
    "publishable": "出版级水准：在忠实原文的基础上进行细致中文化表达，追求可发表或可归档的译文质感。",
}

MARKDOWN_STRUCTURAL_RE = re.compile(
    r"^\s*(#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s+|```|~~~|\|.*\||<!--)\S?"
)
PAGE_MARKER_RE = re.compile(r"^\s*<!--\s*(?:Page|第)\s*\d+\s*(?:页)?\s*-->\s*$", re.I)


@dataclass
class Config:
    provider: str
    model: str
    source_lang: str
    target_lang: str
    style: str
    quality: str
    glossary: str
    auto_glossaries: bool
    max_chars: int
    context_chars: int
    pdf_engine: str
    pdf_quality: str
    keep_page_markers: bool
    glossary_limit: int
    retries: int
    sleep: float
    cache_dir: Path
    dry_run: bool


@dataclass
class PdfExtraction:
    engine: str
    raw_text: str
    cleaned_text: str
    page_count: int
    page_char_counts: list[int]
    plain_chars: int
    score: int = 0
    similarity: float | None = None
    warnings: list[str] | None = None


def die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def normalize_extracted_text(text: str) -> str:
    replacements = {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u00ad": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text


def repair_punctuation_spacing(text: str) -> str:
    text = re.sub(r"\b([A-Z])\.\s+,", r"\1.,", text)
    text = re.sub(r"\bi\.\s*e\.\s*,", "i.e.,", text, flags=re.I)
    text = re.sub(r"\be\.\s*g\.\s*,", "e.g.,", text, flags=re.I)
    text = re.sub(r"\s+([,;:])", r"\1", text)
    return text


def clean_pdf_text(text: str) -> str:
    """Make extracted PDF text more suitable for translation."""
    text = normalize_extracted_text(text)
    blocks = re.split(r"\n\s*\n", text)
    cleaned: list[str] = []
    for block in blocks:
        lines = []
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.fullmatch(r"\d{1,5}", line):
                continue
            line = re.sub(r"^\d{1,5}\s{1,}", "", line).strip()
            if re.fullmatch(r"\d{1,5}", line):
                continue
            if lines and lines[-1].endswith("-") and re.match(r"^[a-z]", line):
                lines[-1] = lines[-1][:-1] + line
            else:
                lines.append(line)
        if not lines:
            continue
        if len(lines) == 1 and lines[0].startswith("<!-- Page "):
            cleaned.append(lines[0])
            continue
        joined = " ".join(lines)
        joined = re.sub(r"\s+", " ", joined).strip()
        joined = re.sub(r"([a-z0-9\)][.!?])(?=[A-Z])", r"\1 ", joined)
        joined = re.sub(r"\b(pp|p)\.(?=\d)", r"\1. ", joined)
        if joined:
            cleaned.extend(split_readable_paragraph(joined, max_chars=1400))
    return repair_punctuation_spacing("\n\n".join(cleaned)).strip() + "\n"


def split_readable_paragraph(paragraph: str, max_chars: int = 900) -> list[str]:
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if len(paragraph) <= max_chars:
        return [paragraph] if paragraph else []
    sentences = re.split(r"(?<=[。！？；;.!?])\s*", paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if current and len(current) + len(sentence) > max_chars:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        pieces.append(current.strip())
    return pieces or [paragraph]


def polish_output_for_reading(text: str, keep_page_markers: bool) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if PAGE_MARKER_RE.match(line) and not keep_page_markers:
            continue
        lines.append(line.rstrip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    polished_blocks: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if MARKDOWN_STRUCTURAL_RE.match(block) or block.startswith("|"):
            polished_blocks.append(block)
        else:
            polished_blocks.extend(split_readable_paragraph(block, max_chars=850))
    return repair_punctuation_spacing("\n\n".join(polished_blocks)).strip() + "\n"


def page_plain_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", re.sub(r"<!-- Page \d+ -->", "", text)))


def extract_pdf_with_pdfplumber(path: Path, keep_page_markers: bool) -> tuple[str, int, list[int]]:
    import pdfplumber  # type: ignore

    pages_text: list[str] = []
    page_char_counts: list[int] = []
    with pdfplumber.open(str(path)) as pdf:
        page_count = len(pdf.pages)
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            page_char_counts.append(page_plain_chars(text))
            if keep_page_markers:
                pages_text.append(f"<!-- Page {index} -->\n\n{text}")
            else:
                pages_text.append(text)
    return "\n\n".join(pages_text), page_count, page_char_counts


def extract_pdf_with_pypdf(path: Path, keep_page_markers: bool) -> tuple[str, int, list[int]]:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(path))
    pages_text: list[str] = []
    page_char_counts: list[int] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_char_counts.append(page_plain_chars(text))
        if keep_page_markers:
            pages_text.append(f"<!-- Page {index} -->\n\n{text}")
        else:
            pages_text.append(text)
    return "\n\n".join(pages_text), len(reader.pages), page_char_counts


def extract_pdf_with_pdftotext(path: Path, keep_page_markers: bool) -> tuple[str, int, list[int]]:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext executable was not found")
    result = subprocess.run(
        [exe, "-layout", "-enc", "UTF-8", str(path), "-"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    text = result.stdout.decode("utf-8", errors="replace")
    pages = text.split("\f")
    page_count = len([page for page in pages if page.strip()])
    page_char_counts = [page_plain_chars(page) for page in pages if page.strip()]
    if keep_page_markers:
        marked = []
        for index, page in enumerate(pages, start=1):
            if page.strip():
                marked.append(f"<!-- Page {index} -->\n\n{page.strip()}")
        text = "\n\n".join(marked)
    return text, page_count, page_char_counts


def extract_pdf_with_pdftotext_raw(path: Path, keep_page_markers: bool) -> tuple[str, int, list[int]]:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext executable was not found")
    result = subprocess.run(
        [exe, "-raw", "-enc", "UTF-8", str(path), "-"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    text = result.stdout.decode("utf-8", errors="replace")
    pages = text.split("\f")
    page_count = len([page for page in pages if page.strip()])
    page_char_counts = [page_plain_chars(page) for page in pages if page.strip()]
    if keep_page_markers:
        marked = []
        for index, page in enumerate(pages, start=1):
            if page.strip():
                marked.append(f"<!-- Page {index} -->\n\n{page.strip()}")
        text = "\n\n".join(marked)
    return text, page_count, page_char_counts


def get_pdf_page_count(path: Path) -> int:
    try:
        from pypdf import PdfReader  # type: ignore

        return len(PdfReader(str(path)).pages)
    except Exception:
        return 0


def extract_pdf_with_docling(path: Path, _keep_page_markers: bool) -> tuple[str, int, list[int]]:
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Docling is not installed. Install it with: pip install docling") from exc

    converter = DocumentConverter()
    result = converter.convert(str(path))
    text = result.document.export_to_markdown()
    page_count = get_pdf_page_count(path)
    return text, page_count, [page_plain_chars(text)]


def extract_pdf_with_marker(path: Path, _keep_page_markers: bool) -> tuple[str, int, list[int]]:
    exe = shutil.which("marker_single")
    if not exe:
        raise RuntimeError("Marker is not installed. Install it with: pip install marker-pdf")
    with tempfile.TemporaryDirectory(prefix="marker_pdf_") as tmp:
        out_dir = Path(tmp)
        commands = [
            [exe, str(path), "--output_format", "markdown", "--output_dir", str(out_dir)],
            [exe, str(path), str(out_dir)],
        ]
        last_error = ""
        for command in commands:
            try:
                subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                markdown_files = sorted(out_dir.rglob("*.md"), key=lambda item: item.stat().st_size, reverse=True)
                if markdown_files:
                    text = read_text(markdown_files[0])
                    page_count = get_pdf_page_count(path)
                    return text, page_count, [page_plain_chars(text)]
                last_error = "Marker finished but did not write a Markdown file"
            except subprocess.CalledProcessError as exc:
                last_error = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(last_error or "Marker conversion failed")


def ocr_page_text(result: list[Any]) -> str:
    if not result:
        return ""
    entries: list[tuple[float, float, float, str, float]] = []
    for item in result:
        box, text, score = item
        if not text:
            continue
        ys = [float(point[1]) for point in box]
        xs = [float(point[0]) for point in box]
        entries.append((min(ys), min(xs), max(ys) - min(ys), str(text).strip(), float(score)))
    if not entries:
        return ""

    entries.sort(key=lambda row: (row[0], row[1]))
    heights = sorted(height for _, _, height, _, _ in entries if height > 0)
    median_height = heights[len(heights) // 2] if heights else 18.0

    lines: list[str] = []
    last_bottom: float | None = None
    for top, _left, height, text, _score in entries:
        if last_bottom is not None and top - last_bottom > median_height * 1.25:
            lines.append("")
        lines.append(text)
        last_bottom = max(last_bottom or 0.0, top + height)
    return "\n".join(lines)


def extract_pdf_with_rapidocr(path: Path, keep_page_markers: bool) -> tuple[str, int, list[int]]:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        from PIL import Image  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "RapidOCR is not installed. Install it with: pip install rapidocr-onnxruntime pillow"
        ) from exc

    exe = shutil.which("pdftoppm")
    if not exe:
        raise RuntimeError("pdftoppm executable was not found; install Poppler first")

    page_count = get_pdf_page_count(path)
    pages_text: list[str] = []
    page_char_counts: list[int] = []
    ocr = RapidOCR()

    with tempfile.TemporaryDirectory(prefix="translator_ocr_") as tmp:
        prefix = Path(tmp) / "page"
        subprocess.run(
            [exe, "-png", "-r", "220", str(path), str(prefix)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        images = sorted(Path(tmp).glob("page-*.png"))
        if not images:
            raise RuntimeError("PDF rendering for OCR did not produce page images")
        if page_count <= 0:
            page_count = len(images)

        for index, image_path in enumerate(images, start=1):
            print(f"OCR: rapidocr page {index}/{len(images)}")
            image = Image.open(image_path).convert("RGB")
            result, _elapsed = ocr(np.array(image))
            page_text = ocr_page_text(result or [])
            page_char_counts.append(page_plain_chars(page_text))
            if keep_page_markers:
                pages_text.append(f"<!-- Page {index} -->\n\n{page_text}")
            else:
                pages_text.append(page_text)

    return "\n\n".join(pages_text), page_count, page_char_counts


def normalize_for_pdf_compare(text: str, limit: int = 50000) -> str:
    text = re.sub(r"<!-- Page \d+ -->", " ", text)
    text = text.lower()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def pdf_compare_units(text: str) -> set[str]:
    normalized = normalize_for_pdf_compare(text)
    return set(re.findall(r"[0-9a-z]{2,}|[\u4e00-\u9fff]", normalized))


def pdf_text_similarity(left: str, right: str) -> float:
    left_units = pdf_compare_units(left)
    right_units = pdf_compare_units(right)
    if not left_units or not right_units:
        return 0.0
    return len(left_units & right_units) / min(len(left_units), len(right_units))


def weird_control_ratio(text: str) -> float:
    if not text:
        return 1.0
    bad = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t\f")
    return bad / max(len(text), 1)


def count_mojibake(text: str) -> int:
    patterns = ["\ufffd", "锟", "â€™", "â€œ", "â€", "Ã", "Â"]
    return sum(text.count(pattern) for pattern in patterns)


def count_text_layer_noise(text: str) -> tuple[int, list[str]]:
    warnings: list[str] = []
    score_penalty = 0

    lines = text.splitlines()
    if lines:
        numeric_lines = sum(1 for line in lines if re.fullmatch(r"\s*\d{1,5}\s*", line))
        numbered_lines = sum(1 for line in lines if re.match(r"^\s*\d{1,5}\s+\S", line))
        numeric_ratio = (numeric_lines + numbered_lines) / max(len(lines), 1)
        if numeric_ratio > 0.18:
            score_penalty += 8
            warnings.append("many page-edge or hidden line numbers detected")

    isolated_letters = len(re.findall(r"\b[a-z]{2,}\s+[a-z]\s+[a-z]{2,}\b", text, re.I))
    split_suffixes = len(
        re.findall(
            r"\b[a-z]{2,}\s+(?:tion|sion|ment|ity|al|ed|ing|ly|ic|ive|ous|ate|able|ible|ance|ence)\b",
            text,
            re.I,
        )
    )
    if isolated_letters > 220 or split_suffixes > 15:
        score_penalty += 18
        warnings.append("many words appear split by stray spaces")
    elif isolated_letters > 160 or split_suffixes > 8:
        score_penalty += 8
        warnings.append("some words appear split by stray spaces")

    spaced_caps = len(re.findall(r"\b(?:[A-Z]\s+){4,}[A-Z]\b", text))
    if spaced_caps > 0:
        score_penalty += 6
        warnings.append("spaced capital headings detected")

    return score_penalty, warnings


def language_family(value: str) -> str:
    value = (value or "").lower()
    if any(token in value for token in ["英文", "english", " en", "en-", "en_"]):
        return "en"
    if any(token in value for token in ["中文", "简体", "繁体", "chinese", "zh"]):
        return "zh"
    return "auto"


def dominant_text_language(text: str) -> str:
    sample = text[:20000]
    latin = sum(1 for char in sample if "a" <= char.lower() <= "z")
    cjk = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
    if cjk > latin * 0.6:
        return "zh"
    if latin > cjk * 2:
        return "en"
    return "auto"


def score_pdf_extraction(extraction: PdfExtraction, peers: list[PdfExtraction]) -> None:
    warnings: list[str] = []
    score = 100

    if extraction.page_count <= 0:
        score -= 40
        warnings.append("page count could not be determined")

    chars_per_page = extraction.plain_chars / max(extraction.page_count, 1)
    if chars_per_page < 80:
        score -= 45
        warnings.append("very little text extracted; this may be a scanned/OCR-needed PDF")
    elif chars_per_page < 350:
        score -= 18
        warnings.append("low text density for an academic PDF")

    if extraction.page_char_counts:
        empty_pages = sum(1 for count in extraction.page_char_counts if count < 40)
        empty_ratio = empty_pages / len(extraction.page_char_counts)
        if empty_ratio > 0.25:
            score -= 20
            warnings.append(f"{empty_pages} pages have almost no extractable text")

    mojibake = count_mojibake(extraction.raw_text)
    if mojibake:
        score -= min(30, mojibake * 3)
        warnings.append(f"possible mojibake/replacement characters detected: {mojibake}")

    control_ratio = weird_control_ratio(extraction.raw_text)
    if control_ratio > 0.002:
        score -= 12
        warnings.append("unusual control characters detected")

    long_tokens = re.findall(r"\S{80,}", extraction.cleaned_text)
    if len(long_tokens) >= 5:
        score -= 10
        warnings.append("many extremely long tokens; spacing may be broken")

    noise_penalty, noise_warnings = count_text_layer_noise(extraction.cleaned_text)
    score -= noise_penalty
    warnings.extend(noise_warnings)

    if peers:
        base = normalize_for_pdf_compare(extraction.cleaned_text)
        similarities = [
            pdf_text_similarity(base, peer.cleaned_text)
            for peer in peers
            if peer.cleaned_text.strip()
        ]
        if similarities:
            extraction.similarity = max(similarities)
            if extraction.similarity < 0.45:
                score -= 25
                warnings.append("other PDF engines disagree strongly with this extraction")
            elif extraction.similarity < 0.60:
                score -= 12
                warnings.append("other PDF engines only partly agree with this extraction")

    extraction.score = max(0, min(100, score))
    extraction.warnings = warnings


def build_pdf_quality_report(extractions: list[PdfExtraction], selected: PdfExtraction, mode: str) -> str:
    lines = [
        "# PDF Text Quality Report",
        "",
        f"Mode: {mode}",
        f"Selected engine: {selected.engine}",
        f"Selected score: {selected.score}/100",
        "",
        "## Candidates",
        "",
    ]
    for item in sorted(extractions, key=lambda ext: ext.score, reverse=True):
        similarity = "n/a" if item.similarity is None else f"{item.similarity:.2f}"
        chars_per_page = item.plain_chars / max(item.page_count, 1)
        lines.extend(
            [
                f"### {item.engine}",
                f"- Pages: {item.page_count}",
                f"- Extracted characters: {item.plain_chars}",
                f"- Characters per page: {chars_per_page:.1f}",
                f"- Cross-engine similarity: {similarity}",
                f"- Score: {item.score}/100",
            ]
        )
        if item.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in item.warnings)
        else:
            lines.append("- Warnings: none")
        lines.append("")
    lines.extend(
        [
            "## How To Read This",
            "",
            "- 80-100: usually safe for translation.",
            "- 60-79: usable, but spot-check several pages against the PDF.",
            "- below 60: risky; OCR or manual cleanup is recommended before translation.",
            "",
        ]
    )
    return "\n".join(lines)


def choose_pdf_extraction(extractions: list[PdfExtraction], mode: str) -> tuple[PdfExtraction, str]:
    for extraction in extractions:
        peers = [peer for peer in extractions if peer.engine != extraction.engine]
        score_pdf_extraction(extraction, peers)
    selected = max(extractions, key=lambda ext: (ext.score, ext.plain_chars))
    report = build_pdf_quality_report(extractions, selected, mode)
    print(report)

    if mode == "strict" and selected.score < 80:
        die("PDF text quality check failed in strict mode. See the PDF quality report and OCR or clean the PDF first.")
    if mode == "balanced" and selected.score < 60:
        die("PDF text quality check failed. The extracted text looks unreliable; OCR or clean the PDF first.")
    if selected.score < 80:
        print("Warning: PDF text quality is not ideal. Please spot-check the quality report before trusting the translation.")
    return selected, report


def looks_like_ocr_needed(extractions: list[PdfExtraction]) -> bool:
    if not extractions:
        return False
    best_chars = max(extraction.plain_chars for extraction in extractions)
    best_score = max(extraction.score for extraction in extractions)
    return best_chars < 500 or best_score < 50


def extract_pdf_text(path: Path, engine: str, keep_page_markers: bool, quality_mode: str) -> tuple[str, str]:
    engines = ["pdftotext-raw", "pdfplumber", "pdftotext", "pypdf"] if engine == "auto" else [engine]
    errors: list[str] = []
    extractions: list[PdfExtraction] = []
    for candidate in engines:
        try:
            if candidate == "pdfplumber":
                text, page_count, page_char_counts = extract_pdf_with_pdfplumber(path, keep_page_markers)
            elif candidate == "pypdf":
                text, page_count, page_char_counts = extract_pdf_with_pypdf(path, keep_page_markers)
            elif candidate == "pdftotext":
                text, page_count, page_char_counts = extract_pdf_with_pdftotext(path, keep_page_markers)
            elif candidate == "pdftotext-raw":
                text, page_count, page_char_counts = extract_pdf_with_pdftotext_raw(path, keep_page_markers)
            elif candidate == "docling":
                text, page_count, page_char_counts = extract_pdf_with_docling(path, keep_page_markers)
            elif candidate == "marker":
                text, page_count, page_char_counts = extract_pdf_with_marker(path, keep_page_markers)
            elif candidate == "rapidocr":
                text, page_count, page_char_counts = extract_pdf_with_rapidocr(path, keep_page_markers)
            else:
                raise RuntimeError(f"unknown PDF engine: {candidate}")
            cleaned = clean_pdf_text(text)
            plain_chars = len(re.sub(r"\s+", "", cleaned))
            print(f"PDF extraction: {candidate}, pages={page_count}, chars={plain_chars}")
            extractions.append(
                PdfExtraction(
                    engine=candidate,
                    raw_text=text,
                    cleaned_text=cleaned,
                    page_count=page_count,
                    page_char_counts=page_char_counts,
                    plain_chars=plain_chars,
                )
            )
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
    if extractions:
        if quality_mode == "off":
            selected = max(extractions, key=lambda ext: ext.plain_chars)
            report = build_pdf_quality_report(extractions, selected, quality_mode)
            print(report)
            return selected.cleaned_text, report
        for extraction in extractions:
            peers = [peer for peer in extractions if peer.engine != extraction.engine]
            score_pdf_extraction(extraction, peers)
        if engine == "auto" and looks_like_ocr_needed(extractions):
            print("PDF appears to be scanned/image-based; trying RapidOCR fallback.")
            try:
                text, page_count, page_char_counts = extract_pdf_with_rapidocr(path, keep_page_markers)
                cleaned = clean_pdf_text(text)
                plain_chars = len(re.sub(r"\s+", "", cleaned))
                ocr_extraction = PdfExtraction(
                    engine="rapidocr",
                    raw_text=text,
                    cleaned_text=cleaned,
                    page_count=page_count,
                    page_char_counts=page_char_counts,
                    plain_chars=plain_chars,
                )
                extractions.append(ocr_extraction)
            except Exception as exc:
                errors.append(f"rapidocr: {exc}")
        selected, report = choose_pdf_extraction(extractions, quality_mode)
        return selected.cleaned_text, report
    die(
        "PDF text extraction failed. Tried: "
        + "; ".join(errors)
        + ". Install pdfplumber/pypdf or Poppler pdftotext, or OCR the PDF first."
    )


def read_input_text(path: Path, cfg: Config) -> tuple[str, str]:
    if path.suffix.lower() == ".pdf":
        return extract_pdf_text(path, cfg.pdf_engine, cfg.keep_page_markers, cfg.pdf_quality)
    return read_text(path), ""


def build_document_context(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    title_lines = [
        line
        for line in lines[:20]
        if not line.startswith("<!-- Page ") and len(line) <= 180
    ][:4]
    headings = [
        line
        for line in lines
        if re.match(r"^(#{1,6}\s+|[0-9]+(\.[0-9]+)*\s+|Abstract\b|Introduction\b|Conclusion\b|References\b)", line, re.I)
    ][:40]
    abstract = ""
    match = re.search(
        r"(?is)\babstract\b[:.\s-]*(.{200,2500}?)(?:\n\s*\n|(?:\bkeywords\b)|(?:\bintroduction\b))",
        text,
    )
    if match:
        abstract = re.sub(r"\s+", " ", match.group(1)).strip()
    parts = ["文档上下文，仅供术语和语境参考，不要翻译这一部分："]
    if title_lines:
        parts.append("题名/开头：\n" + "\n".join(title_lines))
    else:
        first_meaningful = next(
            (line for line in lines if not line.startswith("<!-- Page ")),
            "",
        )
        if first_meaningful:
            parts.append("开头片段：\n" + first_meaningful[:800])
    if abstract:
        parts.append("摘要片段：\n" + abstract)
    if headings:
        parts.append("章节/标题线索：\n" + "\n".join(headings))
    context = "\n\n".join(parts)
    return context[:max_chars]


def split_markdown(text: str, max_chars: int) -> list[str]:
    """Split on blank lines, preserving Markdown-ish blocks where practical."""
    raw_blocks = re.split(r"(\n\s*\n)", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0

    for block in raw_blocks:
        if not block:
            continue
        projected = current_len + len(block)
        if current and projected > max_chars:
            flush()
        if len(block) <= max_chars:
            current.append(block)
            current_len += len(block)
            continue

        flush()
        chunks.extend(split_long_block(block, max_chars))

    flush()
    return [chunk for chunk in chunks if chunk.strip()]


def split_long_block(block: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    sentences = re.split(r"(?<=[.!?。！？；;])\s+", block.strip())
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                pieces.append(current.strip())
                current = ""
            for i in range(0, len(sentence), max_chars):
                pieces.append(sentence[i : i + max_chars].strip())
            continue
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        pieces.append(current.strip())
    return pieces


def looks_structural_only(chunk: str) -> bool:
    lines = [line for line in chunk.splitlines() if line.strip()]
    return bool(lines) and all(MARKDOWN_STRUCTURAL_RE.match(line) for line in lines)


TECH_KEYWORDS = {
    "api",
    "software",
    "database",
    "server",
    "client",
    "cloud",
    "azure",
    "microsoft",
    "windows",
    "linux",
    "algorithm",
    "model",
    "network",
    "interface",
    "application",
    "system",
    "computer",
    "storage",
    "security",
}

SOCIAL_SCIENCE_KEYWORDS = {
    "bourdieu",
    "capital",
    "cultural capital",
    "social capital",
    "symbolic capital",
    "habitus",
    "field",
    "sociology",
    "education",
    "class",
    "social",
    "economic theory",
    "practice",
}


def dictionary_dir() -> Path:
    return Path(__file__).resolve().parent / "dictionaries"


def load_dictionary_registry() -> list[dict[str, Any]]:
    path = dictionary_dir() / "dictionary_registry.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def dictionary_direction_matches(entry: dict[str, Any], cfg: Config, document_text: str) -> bool:
    source = str(entry.get("source", "auto"))
    target = str(entry.get("target", "auto"))
    cfg_source = language_family(cfg.source_lang)
    cfg_target = language_family(cfg.target_lang)
    if cfg_source == "auto":
        cfg_source = dominant_text_language(document_text)
    if cfg_target == "auto":
        return True
    source_ok = source == "auto" or cfg_source == "auto" or source == cfg_source
    target_ok = target == "auto" or target == cfg_target
    return source_ok and target_ok


def dictionary_domain_score(entry: dict[str, Any], document_text: str) -> int:
    domain = str(entry.get("domain", "general"))
    lower = document_text[:50000].lower()
    if domain == "general":
        return 5
    if domain == "technology":
        tech_hits = sum(1 for keyword in TECH_KEYWORDS if keyword in lower)
        social_hits = sum(1 for keyword in SOCIAL_SCIENCE_KEYWORDS if keyword in lower)
        return tech_hits - social_hits * 2
    return 0


def load_auto_glossaries(document_text: str, cfg: Config) -> str:
    if not cfg.auto_glossaries:
        return ""
    selected: list[str] = []
    for entry in load_dictionary_registry():
        if not entry.get("enabled", True):
            continue
        file_name = str(entry.get("file", "")).strip()
        if not file_name:
            continue
        path = dictionary_dir() / file_name
        if not path.exists():
            continue
        if not dictionary_direction_matches(entry, cfg, document_text):
            continue
        score = dictionary_domain_score(entry, document_text)
        if str(entry.get("domain")) != "general" and score < 2:
            print(f"Auto glossary skipped: {entry.get('name', file_name)} (domain score {score})")
            continue
        print(f"Auto glossary enabled: {entry.get('name', file_name)}")
        selected.append(read_text(path))
    return "\n\n".join(selected)


def combine_glossaries(manual: str, automatic: str) -> str:
    parts = [part.strip() for part in [manual, automatic] if part and part.strip()]
    return "\n\n".join(parts)


def filter_manual_glossary(manual: str, document_text: str, cfg: Config) -> str:
    if not manual.strip() or not cfg.auto_glossaries:
        return manual
    if "Microsoft Terminology Collection" in manual:
        score = dictionary_domain_score({"domain": "technology"}, document_text)
        if score < 2:
            print("Manual Microsoft technology glossary skipped: document does not look like a technology/software text.")
            return ""
    return manual


@lru_cache(maxsize=8)
def parse_glossary_entries(glossary: str) -> tuple[list[str], tuple[tuple[str, str, str], ...]]:
    notes: list[str] = []
    entries: list[tuple[str, str, str]] = []
    for raw_line in glossary.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line and line.count("|") >= 2:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 2 and not set(cells[0]) <= {"-", ":"}:
                entries.append((cells[0], cells[1], " | ".join(cells[2:])))
                continue
        for sep in ("\t", ",", "=>", "->", "="):
            if sep in line:
                left, right = line.split(sep, 1)
                source = left.strip()
                target = right.strip()
                if source and target:
                    entries.append((source, target, ""))
                    break
        else:
            notes.append(line)
    return notes, tuple(entries)


def term_matches_chunk(term: str, chunk_lower: str) -> bool:
    normalized = term.strip().strip("`*_").lower()
    if not normalized:
        return False
    if normalized not in chunk_lower:
        return False
    if re.fullmatch(r"[a-z0-9_+-]+", normalized, flags=re.I) and len(normalized) <= 2:
        return False
    if re.search(r"[a-z0-9]", normalized, flags=re.I):
        pattern = r"(?<![a-z0-9_])" + re.escape(normalized) + r"(?![a-z0-9_])"
        return re.search(pattern, chunk_lower, flags=re.I) is not None
    return normalized in chunk_lower


def select_glossary(glossary: str, chunk: str, limit: int) -> str:
    if not glossary.strip():
        return ""
    if len(glossary) <= 4000:
        return glossary.strip()

    notes, entries = parse_glossary_entries(glossary)
    chunk_lower = chunk.lower()
    selected: list[str] = []
    for source, target, note in entries:
        if term_matches_chunk(source, chunk_lower):
            selected.append(f"{source} = {target}" + (f" # {note}" if note else ""))
        if len(selected) >= limit:
            break

    note_text = "\n".join(notes[:20])
    selected_text = "\n".join(selected)
    if note_text and selected_text:
        return note_text + "\n\n当前分块命中的术语：\n" + selected_text
    if selected_text:
        return "当前分块命中的术语：\n" + selected_text
    return note_text


def build_prompt(
    chunk: str,
    cfg: Config,
    document_context: str = "",
    chunk_index: int | None = None,
    chunk_total: int | None = None,
) -> str:
    selected_glossary = select_glossary(cfg.glossary, chunk, cfg.glossary_limit)
    glossary = f"\n术语表/偏好：\n{selected_glossary}\n" if selected_glossary.strip() else ""
    context = f"\n{document_context}\n" if document_context.strip() else ""
    chunk_label = (
        f"\n当前分块：第 {chunk_index} / {chunk_total} 块。请只输出当前分块的译文。\n"
        if chunk_index and chunk_total
        else ""
    )
    return f"""请把下面文本从{cfg.source_lang}翻译成{cfg.target_lang}。

要求：
1. {STYLE_INSTRUCTIONS[cfg.style]}
2. {QUALITY_INSTRUCTIONS[cfg.quality]}
3. 保留 Markdown 结构、标题层级、列表、脚注编号、引用、代码块围栏。
4. 不要添加解释、摘要、前言或“以下是翻译”等额外文字。
5. 人名、书名、机构名可保留原文；必要时在首次出现处给出自然译名。
6. 如果原文已有目标语言内容，不要无意义改写。
{glossary}
{context}
{chunk_label}
待翻译文本：
<TEXT_TO_TRANSLATE>
{chunk}
</TEXT_TO_TRANSLATE>"""


def clean_translated_output(text: str) -> str:
    text = re.sub(r"(?is)</?TEXT_TO_TRANSLATE>", "", text)
    text = re.sub(r"(?i)<<<\s*TEXT\s*", "", text)
    text = re.sub(r"(?im)^\s*<<<\s*TEXT\s*$", "", text)
    text = re.sub(r"(?im)^\s*TEXT\s*$", "", text)
    text = re.sub(r"(?im)^\s*待翻译文本：\s*$", "", text)
    return text.strip()


def request_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    retries: int,
    sleep: float,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {details[:1000]}"
            if exc.code not in {408, 409, 429, 500, 502, 503, 504}:
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)

        if attempt < retries:
            time.sleep(sleep * (2**attempt))

    die(f"request failed after {retries + 1} attempt(s): {last_error}")


def get_env(name: str, fallback: str | None = None) -> str:
    value = os.getenv(name) or fallback
    if not value:
        die(f"missing environment variable: {name}")
    return value


def translate_with_openai(prompt: str, cfg: Config) -> str:
    api_key = get_env("OPENAI_API_KEY")
    data = request_json(
        "https://api.openai.com/v1/responses",
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        {
            "model": cfg.model,
            "input": [
                {
                    "role": "system",
                    "content": "You are a careful professional translator.",
                },
                {"role": "user", "content": prompt},
            ],
        },
        cfg.retries,
        cfg.sleep,
    )
    if "output_text" in data:
        return str(data["output_text"]).strip()
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and "text" in content:
                parts.append(str(content["text"]))
    if parts:
        return "\n".join(parts).strip()
    die(f"OpenAI response did not contain output_text: {json.dumps(data)[:1000]}")


def translate_with_anthropic(prompt: str, cfg: Config) -> str:
    api_key = get_env("ANTHROPIC_API_KEY")
    data = request_json(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        {
            "model": cfg.model,
            "max_tokens": 4096,
            "system": "You are a careful professional translator.",
            "messages": [{"role": "user", "content": prompt}],
        },
        cfg.retries,
        cfg.sleep,
    )
    parts = [
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    if parts:
        return "\n".join(parts).strip()
    die(f"Anthropic response did not contain text content: {json.dumps(data)[:1000]}")


def translate_with_gemini(prompt: str, cfg: Config) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        die("missing environment variable: GEMINI_API_KEY or GOOGLE_API_KEY")
    model = urllib.parse.quote(cfg.model, safe="")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={urllib.parse.quote(api_key)}"
    )
    data = request_json(
        url,
        {"Content-Type": "application/json"},
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "You are a careful professional translator.\n\n" + prompt}],
                }
            ],
        },
        cfg.retries,
        cfg.sleep,
    )
    parts: list[str] = []
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                parts.append(str(part["text"]))
    if parts:
        return "\n".join(parts).strip()
    die(f"Gemini response did not contain text parts: {json.dumps(data)[:1000]}")


def translate_with_chat_completions(
    prompt: str,
    cfg: Config,
    base_url: str,
    api_key: str,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    data = request_json(
        url,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        {
            "model": cfg.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a careful professional translator.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
        cfg.retries,
        cfg.sleep,
    )
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        die(f"chat completions response did not contain message content: {json.dumps(data)[:1000]}")


def translate_chunk(
    chunk: str,
    cfg: Config,
    document_context: str = "",
    chunk_index: int | None = None,
    chunk_total: int | None = None,
) -> str:
    if looks_structural_only(chunk):
        return chunk
    prompt = build_prompt(chunk, cfg, document_context, chunk_index, chunk_total)
    if cfg.dry_run:
        return f"<!-- DRY RUN: {cfg.provider}/{cfg.model}, {len(chunk)} chars -->\n{chunk}"

    if cfg.provider == "openai":
        return clean_translated_output(translate_with_openai(prompt, cfg))
    if cfg.provider == "anthropic":
        return clean_translated_output(translate_with_anthropic(prompt, cfg))
    if cfg.provider == "gemini":
        return clean_translated_output(translate_with_gemini(prompt, cfg))
    if cfg.provider == "deepseek":
        api_key = get_env("DEEPSEEK_API_KEY")
        return clean_translated_output(translate_with_chat_completions(prompt, cfg, "https://api.deepseek.com", api_key))
    if cfg.provider == "openai-compatible":
        api_key = get_env("OPENAI_COMPATIBLE_API_KEY")
        base_url = get_env("OPENAI_COMPATIBLE_BASE_URL")
        return clean_translated_output(translate_with_chat_completions(prompt, cfg, base_url, api_key))

    die(f"unknown provider: {cfg.provider}")


def cache_key(chunk: str, cfg: Config, document_context: str) -> str:
    basis = json.dumps(
        {
            "provider": cfg.provider,
            "model": cfg.model,
            "source_lang": cfg.source_lang,
            "target_lang": cfg.target_lang,
            "style": cfg.style,
            "quality": cfg.quality,
            "document_context": document_context,
            "glossary": cfg.glossary,
            "glossary_limit": cfg.glossary_limit,
            "prompt_version": 2,
            "chunk": chunk,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def translate_file(input_path: Path, output_path: Path, cfg: Config) -> None:
    text, _pdf_report = read_input_text(input_path, cfg)
    manual_glossary = filter_manual_glossary(cfg.glossary, text, cfg)
    auto_glossary = load_auto_glossaries(text, cfg)
    cfg.glossary = combine_glossaries(manual_glossary, auto_glossary)
    document_context = build_document_context(text, cfg.context_chars)
    chunks = split_markdown(text, cfg.max_chars)
    if not chunks:
        die("input file is empty")

    if not cfg.dry_run:
        cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    results: list[str] = []
    print(f"Provider: {cfg.provider} | Model: {cfg.model}")
    print(f"Chunks: {len(chunks)} | Output: {output_path}")
    if document_context:
        print(f"Document context: {len(document_context)} chars sent with each chunk")

    for index, chunk in enumerate(chunks, start=1):
        key = cache_key(chunk, cfg, document_context)
        cache_path = cfg.cache_dir / f"{key}.txt"
        if cfg.dry_run:
            print(f"[{index}/{len(chunks)}] dry run ({len(chunk)} chars)")
            translated = translate_chunk(chunk, cfg, document_context, index, len(chunks))
        elif cache_path.exists():
            translated = read_text(cache_path)
            print(f"[{index}/{len(chunks)}] cache hit ({len(chunk)} chars)")
        else:
            print(f"[{index}/{len(chunks)}] translating ({len(chunk)} chars)")
            translated = translate_chunk(chunk, cfg, document_context, index, len(chunks))
            write_text(cache_path, translated)
            if cfg.sleep > 0:
                time.sleep(cfg.sleep)
        results.append(translated.strip())

    final_text = polish_output_for_reading("\n\n".join(results), cfg.keep_page_markers)
    write_text(output_path, final_text)
    print(f"Done: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate text/Markdown with OpenAI, Anthropic, Gemini, DeepSeek, or OpenAI-compatible APIs."
    )
    parser.add_argument("input", type=Path, help="Input .txt, .md, or .pdf file")
    parser.add_argument("-o", "--output", type=Path, help="Output file path")
    parser.add_argument(
        "-p",
        "--provider",
        choices=["openai", "anthropic", "gemini", "deepseek", "openai-compatible"],
        default="openai",
    )
    parser.add_argument("-m", "--model", help="Model name. Defaults depend on provider.")
    parser.add_argument("--source-lang", default="英文")
    parser.add_argument("--target-lang", default="中文")
    parser.add_argument(
        "--style",
        choices=sorted(STYLE_INSTRUCTIONS),
        default="readable",
        help="Translation style",
    )
    parser.add_argument(
        "--quality",
        choices=sorted(QUALITY_INSTRUCTIONS),
        default="standard",
        help="Translation quality level",
    )
    parser.add_argument("--glossary-file", type=Path, help="Optional glossary or style notes file")
    parser.add_argument(
        "--no-auto-glossaries",
        action="store_true",
        help="Disable automatic built-in dictionary selection",
    )
    parser.add_argument("--max-chars", type=int, default=5000, help="Max characters per chunk")
    parser.add_argument(
        "--context-chars",
        type=int,
        default=3000,
        help="Document context characters sent with every chunk; use 0 to disable",
    )
    parser.add_argument(
        "--pdf-engine",
        choices=["auto", "pdfplumber", "pypdf", "pdftotext", "pdftotext-raw", "rapidocr", "docling", "marker"],
        default="auto",
        help="PDF text extraction engine",
    )
    parser.add_argument(
        "--pdf-quality",
        choices=["balanced", "strict", "off"],
        default="balanced",
        help="PDF text quality gate before translation",
    )
    parser.add_argument(
        "--no-page-markers",
        action="store_true",
        help="Do not insert HTML page markers when extracting PDF text",
    )
    parser.add_argument(
        "--glossary-limit",
        type=int,
        default=80,
        help="Max matched glossary entries injected per chunk for large glossaries",
    )
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds between requests; also retry base delay")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".translate_cache"),
        help="Directory for translated chunk cache",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not call APIs; write chunk markers")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        die(f"input file not found: {args.input}")
    provider = args.provider
    model = args.model or DEFAULT_MODELS[provider]
    output = args.output
    if output is None:
        output = args.input.with_name(args.input.stem + f".{provider}.zh.md")
    glossary = read_text(args.glossary_file) if args.glossary_file else ""
    cfg = Config(
        provider=provider,
        model=model,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        style=args.style,
        quality=args.quality,
        glossary=glossary,
        auto_glossaries=not args.no_auto_glossaries,
        max_chars=args.max_chars,
        context_chars=args.context_chars,
        pdf_engine=args.pdf_engine,
        pdf_quality=args.pdf_quality,
        keep_page_markers=not args.no_page_markers,
        glossary_limit=args.glossary_limit,
        retries=args.retries,
        sleep=args.sleep,
        cache_dir=args.cache_dir,
        dry_run=args.dry_run,
    )
    translate_file(args.input, output, cfg)


if __name__ == "__main__":
    main()
