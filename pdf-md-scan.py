#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf-md-scan.py: Convert a password-protected PDF into structured Markdown (Obsidian-ready).
Extracts text (with headings, lists, etc.), tables, images, and augments with wikilinks and tags.
"""
import sys
import re
import fitz  # PyMuPDF
import argparse
from io import BytesIO

# Optional OCR
try:
    from PIL import Image
    import pytesseract
    OCR_ENABLED = True
except ImportError:
    OCR_ENABLED = False

# Will be set from the CLI --ocr flag
USE_OCR = False


def detect_headings_style(doc):
    """Scan the document to determine base font size (paragraph text) and heading sizes."""
    size_counts = {}
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if b.get("type") == 0:
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        fs = span.get("size", 0)
                        key = round(fs, 1)
                        size_counts[key] = size_counts.get(key, 0) + len(span.get("text", ""))
    if not size_counts:
        return None, []
    base_size = max(size_counts, key=size_counts.get)
    heading_sizes = [sz for sz in size_counts if sz > base_size * 1.1]
    heading_sizes.sort(reverse=True)
    return base_size, heading_sizes


def save_image(img_data, page_number, img_index, output_prefix):
    """Save image bytes to file and return the filename for markdown."""
    fmt = img_data.get("ext", "png")
    image_bytes = img_data.get("image")
    if not image_bytes:
        return None
    filename = f"{output_prefix}_page{page_number+1}_image{img_index+1}.{fmt}"
    try:
        with open(filename, "wb") as img_file:
            img_file.write(image_bytes)
    except Exception as e:
        print(f"Error saving image for page {page_number+1}: {e}", file=sys.stderr)
        return None
    return filename


def ocr_image_to_text(image_bytes):
    """Use pytesseract to extract text from an image (if OCR is enabled)."""
    if not OCR_ENABLED:
        return ""
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception:
        return ""
    text = pytesseract.image_to_string(img)
    return text.strip()


def extract_pdf_to_markdown(pdf_path, password=None, output_file="output.md"):  # noqa: C901
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF: {e}", file=sys.stderr)
        return False
    if doc.needs_pass:
        if not password:
            print("Password required but not provided.", file=sys.stderr)
            return False
        if not doc.authenticate(password):
            print("Incorrect PDF password.", file=sys.stderr)
            return False

    base_size, heading_sizes = detect_headings_style(doc)
    level_map = {}
    if heading_sizes:
        level_map[heading_sizes[0]] = 3
    if len(heading_sizes) > 1:
        level_map[heading_sizes[1]] = 4

    md_lines = []
    collected = []
    tags = set()
    inside_code = False

    for page_num, page in enumerate(doc):
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = "".join(span.get("text", "") for span in spans)
                    first = spans[0]
                    fsize = round(first.get("size", 0), 1)
                    fname = first.get("font", "")
                    fcolor = first.get("color", 0)
                    bold = "Bold" in fname

                    # Headings
                    if fsize in level_map:
                        if inside_code:
                            md_lines.append("```")
                            inside_code = False
                        md_lines.append(f"{'#'*level_map[fsize]} {text.strip()}")
                        collected.append(text.strip())
                        continue
                    if fsize == base_size and (bold or fcolor != 0):
                        if inside_code:
                            md_lines.append("```")
                            inside_code = False
                        md_lines.append(f"#### {text.strip()}")
                        collected.append(text.strip())
                        continue

                    # Lists
                    stripped = text.strip()
                    indent = int(first.get("bbox", [0])[0] // 20)
                    marker = None
                    if stripped.startswith(('* ', '- ', '•', '◦', '▪')):
                        marker = '-'
                    else:
                        m = re.match(r"^(\d+)[\.|\)]\s+", stripped)
                        if m:
                            marker = f"{m.group(1)}."
                    if marker:
                        if inside_code:
                            md_lines.append("```")
                            inside_code = False
                        indent_spaces = ' ' * 4 * indent
                        content = re.sub(r'^[*\-•◦▪\d+[\.|\)]\s*', '', stripped)
                        md_lines.append(f"{indent_spaces}{marker} {content}")
                        collected.append(content)
                        continue

                    # Code blocks
                    mono = any(m in fname for m in ("Courier", "Consolas", "Mono"))
                    if mono:
                        if not inside_code:
                            md_lines.append("```")
                            inside_code = True
                        md_lines.append(text.rstrip())
                        continue
                    else:
                        if inside_code:
                            md_lines.append("```")
                            inside_code = False
                        md_lines.append(text.rstrip())
                        collected.append(text.rstrip())
            elif block.get("type") == 1:
                img_index = block.get("number", 0)
                path = save_image(block, page_num, img_index, output_prefix="extracted_image")
                if path:
                    if inside_code:
                        md_lines.append("```")
                        inside_code = False
                    md_lines.append(f"![]({path})")
                    if OCR_ENABLED and USE_OCR:
                        ocr = ocr_image_to_text(block.get("image"))
                        if ocr:
                            md_lines.append(f"> OCR Extracted: {ocr}")
                            collected.append(ocr)
    if inside_code:
        md_lines.append("```")

    # Wikilinks
    full_text = " ".join(collected)
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9]+\b", full_text)
    stopwords = {"the","and","or","of","to","a","in","is","for","on","with","this","that","by","are"}
    freq = {}
    for w in words:
        lw = w.lower()
        if len(w) < 4 or lw in stopwords:
            continue
        freq[w] = freq.get(w, 0) + 1
    bigrams = re.findall(r"\b(\w+) (\w+)\b", full_text)
    for a, b in bigrams:
        phrase = f"{a} {b}"
        if all(len(x) >= 4 and x.lower() not in stopwords for x in (a, b)):
            freq[phrase] = freq.get(phrase, 0) + 1
    terms = [t for t, c in freq.items() if c >= 2]
    terms.sort(key=len, reverse=True)
    for i, line in enumerate(md_lines):
        if line.startswith("```") or line.startswith("> OCR"):
            continue
        for term in terms:
            pattern = r"\b" + re.escape(term) + r"\b"
            md_lines[i] = re.sub(pattern, lambda m: f"[[{m.group(0)}]]" if not m.group(0).startswith("[[") else m.group(0), md_lines[i])

    # Tags
    tl = full_text.lower()
    for kw, tag in [("security", "#security"), ("assessment", "#assessment"), ("compliance", "#compliance"), ("network", "#network"), ("vulnerability", "#vulnerability"), (("methodology", "methods"), "#methodology")]:
        if isinstance(kw, tuple):
            if any(k in tl for k in kw):
                tags.add(tag)
        else:
            if kw in tl:
                tags.add(tag)
    if tags:
        md_lines.append("\n" + " ".join(sorted(tags)))

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        return False

    print(f"Markdown generated: {output_file}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert a PDF to Obsidian-optimized Markdown.")
    parser.add_argument("input_pdf", help="Path to the input PDF file.")
    parser.add_argument("-p", "--password", help="PDF password (if encrypted)", default=None)
    parser.add_argument("-o", "--output", help="Output markdown file", default="output.md")
    parser.add_argument("--ocr", help="Enable OCR for images", action="store_true")
    args = parser.parse_args()
    USE_OCR = args.ocr
    if args.ocr and not OCR_ENABLED:
        print("OCR requested but dependencies missing; skipping OCR.", file=sys.stderr)
    extract_pdf_to_markdown(args.input_pdf, password=args.password, output_file=args.output)
