# PDF → Obsidian-Ready Markdown Converter

A Python utility to decrypt and parse a password-protected PDF into an Obsidian-friendly Markdown file with:

- **Headings** detected by font size/color → `###` / `####`  
- **Lists** preserved (`-`, `1.`) with indentation  
- **Tables** reconstructed or fenced code fallback  
- **Code blocks** for monospaced text  
- **Images** extracted and embedded  
- **Wiki‐links** (`[[Terms]]`) auto-wrapped around key concepts  
- **Tags** (`#security`, `#assessment`, etc.) appended based on content

---

## Installation

1. Clone or download this repo (alongside `pdf-md-scan.py`).  
2. Create a virtual environment and activate it:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
Install dependencies:

bash
Copy
Edit
pip install -r requirements.txt
(Optional) Install Tesseract OCR if you want image→text OCR:

bash
Copy
Edit
sudo apt install tesseract-ocr    # Debian/Ubuntu
brew install tesseract            # macOS
Usage
bash
Copy
Edit
python3 pdf-md-scan.py <input.pdf> -p <password> -o <output.md> [--ocr]
<input.pdf>: your (possibly encrypted) PDF

-p, --password: PDF password (if encrypted)

-o, --output: target Markdown filename (default: output.md)

--ocr: enable image‐based OCR (requires pytesseract + Tesseract)

Example
bash
Copy
Edit
python3 pdf-md-scan.py report.pdf \
  -p "MySecurePass" \
  -o "report.md" \
  --ocr
How it Works
Decrypts the PDF with the provided password.

Analyzes font sizes/colors to distinguish headings vs. body text.

Extracts text blocks, lists, tables, and images (saving each image locally).

Formats everything into Markdown:

### for major sections, #### for subsections

- or 1. for lists, with preserved indentation

Fenced code blocks for monospaced text

![](image.png) for images

Post-processes the Markdown to:

Wrap frequently used terms in [[wikilinks]]

Append #tags based on keyword scanning

Notes & Tips
If your PDF is purely scanned pages, OCR is highly recommended (--ocr).

You can tweak heading thresholds or list-indent heuristics by editing the font-size or indent constants in the script.

Obsidian will automatically resolve [[wikilinks]]—click to create new notes for each concept.

Feel free to adjust the tag set in the script to match your personal taxonomy.

