"""Create synthetic PDF review pages only, without reading any database.

Run with the locked test environment: python -m scripts.verify_pdf --output data/pdf-review-NEW
The destination must not exist, so no previous files are overwritten.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image, ImageDraw

from app.pdf_export import generate_project_pdf
from tests.pdf_audit import audit_pdf
from tests.pdf_fixtures import pdf_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--poppler", action="store_true", help="Also render every page with independent Poppler")
    args = parser.parse_args()
    poppler = shutil.which("pdftoppm") if args.poppler else None
    if args.poppler and not poppler:
        parser.error("pdftoppm is required for --poppler")
    args.output.mkdir(parents=True, exist_ok=False)
    results = {}
    for kind in ["empty", "mixed", "long-row", "long-title", "sensitive"]:
        folder = args.output / kind
        folder.mkdir()
        data = pdf_fixture("empty" if kind == "sensitive" else kind)
        if kind == "sensitive":
            data.access_accounts.append(pdf_fixture().access_accounts[0])
        content = generate_project_pdf(*data.renderer_args(), include_secrets=kind == "sensitive")
        target = folder / "fixture.pdf"
        target.write_bytes(content)
        text, pages = audit_pdf(content, folder)
        (folder / "text.txt").write_text(text, encoding="utf-8")
        if poppler:
            subprocess.run([poppler, "-r", "100", "-png", str(target), str(folder / "poppler")],
                           check=True, capture_output=True, timeout=60)
        images = sorted(folder.glob("poppler-*.png" if poppler else "page-*.png"))
        for start in range(0, len(images), 4):
            sheet = Image.new("RGB", (1040, 1520), "#d9dce3")
            draw = ImageDraw.Draw(sheet)
            for cell, filename in enumerate(images[start:start+4]):
                with Image.open(filename) as original:
                    thumbnail = original.convert("RGB")
                    thumbnail.thumbnail((500, 710))
                    x, y = 10 + (cell % 2) * 520, 35 + (cell // 2) * 760
                    sheet.paste(thumbnail, (x, y))
                    draw.text((x, y-23), f"{kind}: page {start+cell+1}", fill="black")
            sheet.save(folder / f"contact-{start//4+1:02}.png")
        results[kind] = {"pages": len(pages), "bytes": len(content)}
    (args.output / "summary.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
