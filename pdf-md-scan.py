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
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = round(span.get("size", 0), 1)
                    size_counts[size] = size_counts.get(size, 0) + len(span.get("text", ""))
    if not size_counts:
        return None, []
    base_size = max(size_counts, key=size_counts.get)
    headings = sorted([sz for sz in size_counts if sz > base_size * 1.1], reverse=True)
    return base_size, headings


def save_image(img_data, page_num, img_idx, prefix):
    """Save image bytes to file and return the filename for markdown."""
    ext = img_data.get("ext", "png")
    data = img_data.get("image")
    if not data:
        return None
    fname = f"{prefix}_page{page_num+1}_img{img_idx+1}.{ext}"
    try:
        with open(fname, 'wb') as f:
            f.write(data)
    except Exception as e:
        print(f"Failed to save image: {e}", file=sys.stderr)
        return None
    return fname


def ocr_image_to_text(image_bytes):
    """Extract text from image if OCR is enabled."""
    if not OCR_ENABLED or not USE_OCR:
        return ""
    try:
        img = Image.open(BytesIO(image_bytes))
        return pytesseract.image_to_string(img).strip()
    except Exception:
        return ""


def extract_pdf_to_markdown(pdf_path, password=None, output_file="output.md"):  # noqa: C901
    # Open & authenticate
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF: {e}", file=sys.stderr)
        return False
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            print("Invalid or missing PDF password.", file=sys.stderr)
            return False

    # Determine heading/font sizes
    base_size, heading_sizes = detect_headings_style(doc)
    level = {}
    if len(heading_sizes) > 0:
        level[heading_sizes[0]] = 3  # H3
    if len(heading_sizes) > 1:
        level[heading_sizes[1]] = 4  # H4

    md = []          # markdown lines
    collected = []   # textual content for link/tag analysis
    tags = set()
    in_code = False

    # Process each page
    for pnum, page in enumerate(doc):
        for block in page.get_text("dict").get("blocks", []):
            btype = block.get("type")
            # Text blocks
            if btype == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = ''.join(s.get('text','') for s in spans)
                    hdr = spans[0]
                    fsize = round(hdr.get('size',0),1)
                    fname = hdr.get('font','')
                    fcol = hdr.get('color',0)
                    bold = 'Bold' in fname

                    # Headings
                    if fsize in level:
                        if in_code:
                            md.append('```')
                            in_code = False
                        md.append(f"{'#'*level[fsize]} {text.strip()}")
                        collected.append(text.strip())
                        continue
                    if fsize == base_size and (bold or fcol != 0):
                        if in_code:
                            md.append('```')
                            in_code = False
                        md.append(f"#### {text.strip()}")
                        collected.append(text.strip())
                        continue

                    # Lists
                    stripped = text.strip()
                    indent = int(hdr.get('bbox',[0])[0] // 20)
                    marker = None
                    if re.match(r'^[*\-•◦▪]', stripped):
                        marker='-'
                    elif re.match(r'^\d+[\.|\)]\s+', stripped):
                        marker=re.match(r'^(\d+)[\.|\)]', stripped).group(1)+'.'
                    if marker:
                        if in_code:
                            md.append('```')
                            in_code=False
                        content = re.sub(r'^([*\-•◦▪]|\d+[\.|\)])\s*','', stripped)
                        md.append(' '*(4*indent)+f"{marker} {content}")
                        collected.append(content)
                        continue

                    # Code detection (monospace font)
                    if any(m in fname for m in ('Courier','Mono','Consolas')):
                        if not in_code:
                            md.append('```')
                            in_code=True
                        md.append(text.rstrip())
                        continue
                    if in_code:
                        md.append('```')
                        in_code=False

                    # Normal text
                    md.append(text.rstrip())
                    collected.append(text.rstrip())

            # Image blocks
            elif btype == 1:
                img = save_image(block, pnum, block.get('number',0), 'img')
                if img:
                    if in_code:
                        md.append('```'); in_code=False
                    md.append(f"![]({img})")
                    ocrtxt = ocr_image_to_text(block.get('image'))
                    if ocrtxt:
                        md.append(f"> OCR: {ocrtxt}")
                        collected.append(ocrtxt)

    if in_code:
        md.append('```')

    # Prepare wikilinks & tags
    text_blob = ' '.join(collected)
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9]+\b", text_blob)
    stop = set(["the","and","or","of","to","a","in","is","for","on","with","this","that","by","are"])
    freq = {}
    for w in words:
        lw = w.lower()
        if len(w)<4 or lw in stop: continue
        freq[w] = freq.get(w,0)+1
    bigrams = re.findall(r"\b(\w+) (\w+)\b", text_blob)
    for a,b in bigrams:
        if len(a)>=4 and len(b)>=4 and a.lower() not in stop and b.lower() not in stop:
            phrase=f"{a} {b}"
            freq[phrase]=freq.get(phrase,0)+1
    terms=[t for t,c in freq.items() if c>=2][:20]
    patterns=[re.compile(r"\b"+re.escape(t)+r"\b") for t in terms]

    for i,line in enumerate(md):
        if line.startswith('```') or line.startswith('> OCR'): continue
        for pat in patterns:
            if pat.search(line):
                md[i]=pat.sub(lambda m: f"[[{m.group(0)}]]", line)
                break

    # Tags based on keywords
    low=text_blob.lower()
    tagmap={"security":"#security","assessment":"#assessment","compliance":"#compliance","network":"#network","vulnerability":"#vulnerability","methodology":"#methodology"}
    for k,tag in tagmap.items():
        if k in low:
            tags.add(tag)
    if tags:
        md.append('\n'+ ' '.join(sorted(tags)))

    # Write output
    try:
        with open(output_file,'w',encoding='utf-8') as f:
            f.write('\n'.join(md))
    except Exception as e:
        print(f"Failed writing output: {e}",file=sys.stderr)
        return False

    print(f"Generated: {output_file}")
    return True


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('input_pdf')
    p.add_argument('-p','--password',default=None)
    p.add_argument('-o','--output',default='output.md')
    p.add_argument('--ocr',action='store_true')
    args=p.parse_args()
    USE_OCR=args.ocr
    if args.ocr and not OCR_ENABLED:
        print("OCR dependencies missing; skipping OCR.",file=sys.stderr)
    extract_pdf_to_markdown(args.input_pdf, password=args.password, output_file=args.output)
