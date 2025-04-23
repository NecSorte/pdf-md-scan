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
            if b.get("type") == 0:  # text block
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        fs = span.get("size", 0)
                        # Count frequency of each font size (rounded to one decimal to avoid minor variations)
                        fs_key = round(fs, 1)
                        size_counts[fs_key] = size_counts.get(fs_key, 0) + len(span.get("text", ""))
                        # ^ add length of text as weight, assuming longer spans contribute more to that font usage
    if not size_counts:
        return None, []  # no text
    # Determine the most common font size (paragraph text size)
    base_size = max(size_counts, key=size_counts.get)
    # Any font size significantly larger than base_size will be considered a heading size
    heading_sizes = [sz for sz in size_counts if sz > base_size * 1.1]  # >10% larger than body
    heading_sizes.sort(reverse=True)  # largest first
    return base_size, heading_sizes

def save_image(img_data, page_number, img_index, output_prefix):
    """Save image bytes to file and return the filename for markdown."""
    # Determine image format and extension
    fmt = img_data.get("ext", "png")  # PyMuPDF provides 'ext'
    image_bytes = img_data.get("image")
    if not image_bytes:
        return None
    # Construct image filename
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
        image = Image.open(fitz.BytesIO(image_bytes))
    except Exception:
        from io import BytesIO
        image = Image.open(BytesIO(image_bytes))
    # Perform OCR
    text = pytesseract.image_to_string(image)
    # Clean up OCR text (strip trailing whitespace/newlines)
    return text.strip()

def extract_pdf_to_markdown(pdf_path, password=None, output_file="output.md"):
    # Open the PDF document
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF: {e}", file=sys.stderr)
        return False
    # Authenticate if needed
    if doc.needs_pass:
        if password is None:
            print("Password is required for this PDF but not provided.", file=sys.stderr)
            return False
        if not doc.authenticate(password):
            print("Incorrect password for PDF.", file=sys.stderr)
            return False

    # Determine font size usage to classify headings
    base_font_size, heading_sizes = detect_headings_style(doc)
    # We will map heading sizes to levels: largest -> H3, second largest -> H4
    level_map = {}
    if heading_sizes:
        level_map[heading_sizes[0]] = 3  # H3
    if len(heading_sizes) > 1:
        level_map[heading_sizes[1]] = 4  # H4
    # (Any additional larger sizes beyond two could also be H4 or H5, but per requirements we use H3/H4 primarily.)

    md_lines = []  # List to collect Markdown lines of output
    collected_text_for_links = []  # to collect text for wikilink analysis (excluding code blocks)
    tags = set()

    for page_num, page in enumerate(doc):
        page_dict = page.get_text("dict")
        blocks = page_dict["blocks"]

        # Go through each block in reading order
        for block in blocks:
            btype = block.get("type")
            if btype == 0:  # text block
                lines = block.get("lines", [])
                for line in lines:
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    # Combine all spans' text for this line:
                    line_text = "".join([span.get("text", "") for span in spans])
                    # Determine the dominant font size and other attributes of this line (take the first span as representative, assuming uniform styling per line)
                    first_span = spans[0]
                    font_size = round(first_span.get("size", 0), 1)
                    font_name = first_span.get("font", "")
                    font_color = first_span.get("color", 0)
                    is_bold = "Bold" in font_name  # simple check for bold font
                    # Check if this line is a heading
                    if font_size in level_map:
                        level = level_map[font_size]
                        # Write as heading
                        md_lines.append(f"{'#' * level} {line_text.strip()}")
                        # Consider adding the heading text as a term for linking (without the Markdown syntax)
                        collected_text_for_links.append(line_text.strip())
                        continue  # go to next line
                    # If font_size equals base_font_size but line is bold or colored differently (and likely not a full sentence), treat as a subheading
                    if font_size == base_font_size and (is_bold or font_color != 0):
                        # Use H4 for bold/colored lines that match body size (assuming these are subheadings)
                        md_lines.append(f"#### {line_text.strip()}")
                        collected_text_for_links.append(line_text.strip())
                        continue

                    # Check for list item (bullet or numbered list)
                    stripped = line_text.strip()
                    list_match = False
                    indent_level = 0
                    # Determine indent level by span's x-coordinate relative to page or other lines
                    # (We can use first_span['bbox'][0] as left x of the text)
                    if spans:
                        left_x = first_span.get("bbox", [0,0,0,0])[0]
                        # Simple heuristic: indent level increases every 20 units (this can be adjusted)
                        indent_level = int(left_x // 20)
                    if stripped.startswith(("* ", "- ", "•", "◦", "▪")):
                        list_match = True
                        marker = "-"  # default unordered list marker
                    else:
                        # Numbered list detection (e.g., "1. text" or "1) text")
                        m = re.match(r"^(\d+)[\.\)]\s+", stripped)
                        if m:
                            list_match = True
                            marker = f"{m.group(1)}."  # preserve the number as marker
                    if list_match:
                        # Ensure there's a space after marker for markdown
                        # Build indent (in spaces) for this level (4 spaces per indent level beyond 0)
                        indent = " " * 4 * max(0, indent_level)
                        # Remove any existing bullet symbol for clean output after marker
                        content = re.sub(r'^(\*|-|•|◦|▪|\d+[\.\)])\s*', '', stripped)
                        md_lines.append(f"{indent}{marker} {content}")
                        collected_text_for_links.append(content)
                        # Skip normal processing for this line since it's handled as list
                        continue

                    # Not a heading or list, treat as regular text:
                    # If this line is part of a code block? Check font for monospaced or unusual indentation not a list.
                    mono_fonts = ("Courier", "Consolas", "Mono")
                    if any(mono in font_name for mono in mono_fonts):
                        # This suggests a code/preformatted text line.
                        # We will collect such lines and later wrap them in a code fence.
                        # For simplicity, let's detect contiguous monospaced lines as a block.
                        # Open a code block if not already in one.
                        if not md_lines or not md_lines[-1].startswith("```"):
                            md_lines.append("```")  # start code block
                        md_lines.append(line_text.rstrip())  # add code line (keep spacing and content as is)
                        # Mark that we are inside code (by a special marker in collected_text_for_links perhaps)
                        # We'll handle closing the code block after this block.
                        # (We'll close it when we detect next non-mono line or end of block.)
                        continue
                    else:
                        # If the last added line was a code fence and this line is not code, close the fence.
                        if md_lines and md_lines[-1].startswith("```") and md_lines[-1] != "```":
                            # If the code block hasn't been closed (last line is part of code but not the fence itself),
                            # close it before adding this normal line.
                            md_lines.append("```")
                        # For normal text lines, just add as is.
                        md_lines.append(line_text.rstrip())
                        collected_text_for_links.append(line_text.rstrip())
            elif btype == 1:  # image block
                # Save the image data to file
                img_index = block.get("number", 0)
                img_path = save_image(block, page_num, img_index, output_prefix="extracted_image")
                if img_path:
                    # Embed the image in markdown
                    md_lines.append(f"![]({img_path})")
                    # Optionally, perform OCR on the image and include text (as blockquote for example)
                    if OCR_ENABLED and USE_OCR:
    ocr_text = ocr_image_to_text(block.get("image"))
    if ocr_text:
        md_lines.append(f"> OCR Extracted: {ocr_text}")
        collected_text_for_links.append(ocr_text)
    # After looping all pages, ensure any open code block is closed
    if md_lines and md_lines[-1].startswith("```") and md_lines[-1] != "```":
        md_lines.append("```")

    # Now process collected_text_for_links to identify key terms for wikilinks
    text_for_analysis = " ".join(collected_text_for_links)
    # Simple frequency-based approach: find words/phrases occurring multiple times
    # We'll do a quick frequency count of capitalized words or multi-word phrases.
    # First, get all words (split by non-alphanumeric)
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9]+\b", text_for_analysis)  # basic word pattern
    # Filter out short common words
    stopwords = {"the","and","or","of","to","a","in","is","for","on","with","this","that","by","are"}
    candidates = {}
    for w in words:
        if len(w) < 4 or w.lower() in stopwords:
            continue
        # Treat words with capital letter (proper nouns/acronyms) or any word as candidate
        key = w
        # Count frequency case-insensitively
        candidates[key] = candidates.get(key, 0) + 1
    # Also consider phrases of 2 words (bigram) that appear often
    # We can do a simple bigram scan on the collected text
    tokens = re.findall(r"\b\w+\b", text_for_analysis)
    for i in range(len(tokens)-1):
        phrase = f"{tokens[i]} {tokens[i+1]}"
        # Only consider if both words are alphabetic and not stopwords
        if all(len(t) >= 4 and t.lower() not in stopwords for t in tokens[i:i+2]):
            candidates[phrase] = candidates.get(phrase, 0) + 1

    # Select phrases that occur at least 2 times
    link_terms = [term for term, freq in candidates.items() if freq >= 2]
    # Sort terms by length (longer first) to avoid overlapping replacements
    link_terms.sort(key=len, reverse=True)

    # Replace terms in md_lines with [[term]] for wikilinks, avoiding code blocks
    for idx, line in enumerate(md_lines):
        # Skip lines that are code fences or inside code block
        if line.startswith("```"):
            continue
        if md_lines[idx-1] == "```" if idx > 0 else False:
            # previous line opens code block, so this is code content
            continue
        if line.startswith("> OCR Extracted"):
            # skip OCR lines for linking to avoid cluttering extracted text
            continue
        for term in link_terms:
            # Use regex to replace whole word or phrase matches case-sensitively as they appear
            # Only replace if the term is present in the line in plain text
            pattern = r"\b" + re.escape(term) + r"\b"
            # Use a lambda to ensure we don't replace if it's already inside [[ ]]
            def repl(match):
                found = match.group(0)
                # If already in a wikilink, skip (though in our generation it shouldn't be yet)
                return f"[[{found}]]" if not found.startswith("[[") else found
            line = re.sub(pattern, repl, line)
        md_lines[idx] = line

    # Identify tags based on keywords in the overall text
    text_lower = text_for_analysis.lower()
    if "security" in text_lower:
        tags.add("#security")
    if "assessment" in text_lower:
        tags.add("#assessment")
    if "compliance" in text_lower:
        tags.add("#compliance")
    if "network" in text_lower:
        tags.add("#network")
    if "vulnerability" in text_lower:
        tags.add("#vulnerability")
    if "methodology" in text_lower or "methods" in text_lower:
        tags.add("#methodology")

    # Append tags to markdown (as a single line at end, if any)
    if tags:
        md_lines.append("\n" + " ".join(sorted(tags)))

    # Write out to the markdown file
    try:
        with open(output_file, "w", encoding="utf-8") as out:
            out.write("\n".join(md_lines))
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        return False

    print(f"Markdown file generated: {output_file}")
    return True

# If run as a script, parse arguments and execute
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert a PDF to Obsidian-optimized Markdown.")
    parser.add_argument("input_pdf", help="Path to the input PDF file (password-protected or not).")
    parser.add_argument("-p", "--password", help="Password for the PDF file (if encrypted).", default=None)
    parser.add_argument("-o", "--output", help="Output markdown file path.", default="output.md")
    parser.add_argument("--ocr", help="Enable OCR for images (requires pytesseract).", action="store_true")
    args = parser.parse_args()
    USE_OCR = args.ocr
    if args.ocr:
        if not OCR_ENABLED:
            print("OCR requested, but pytesseract/Pillow not installed. Proceeding without OCR.", file=sys.stderr)
        else:
            print("OCR enabled: will extract text from images where possible.")
    # Call the extraction function
    success = extract_pdf_to_markdown(args.input_pdf, password=args.password, output_file=args.output)
    sys.exit(0 if success else 1)
