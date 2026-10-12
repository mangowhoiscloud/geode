"""Rasterize the existing public report, without modifying its PDFs.

Authoring only: requires Poppler and Pillow. CI verifies the committed output
with verify-report-pages.mjs; it does not install or invoke a PDF renderer.
Run from any directory with an interpreter that already provides Pillow.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

SITE = Path(__file__).resolve().parents[1]
ASSETS = SITE / "public/research/geode-report"
DATA = SITE / "src/data/geode/report-pages.json"
WIDTH = 1600
SOURCE_HASHES = {
    "ko": "af5dfb59a511714bb2b152e2a06f3e5d1db8af6afa598aec4734c24d0036d3f0",
    "en": "bd5332dbb0b35094c934ab803c63cc47ab6c27e217ac0c22367cdc73212284c0",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_title(transcript: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in transcript.splitlines() if line.strip()]
    if re.fullmatch(r"ACT \d+", lines[0]):
        return lines[2][:150]  # Chapter artwork: eyebrow, number, then heading.
    if lines[0].startswith("ACT "):
        return lines[1][:150]
    return " ".join(lines[:2])[:150]


def main() -> None:
    pdftotext = shutil.which("pdftotext")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftotext or not pdftoppm:
        raise RuntimeError("Install Poppler before running this authoring-only exporter")
    records = []
    editions = {}
    ASSETS.mkdir(parents=True, exist_ok=True)
    for language, filename in (("ko", "report.pdf"), ("en", "report-en.pdf")):
        source = SITE / "public" / filename
        source_hash = digest(source)
        assert source_hash == SOURCE_HASHES[language], (
            "Review and pin a new PDF edition before exporting"
        )
        # Resolved local Poppler tool; all arguments are fixed repository paths.
        text = subprocess.check_output([pdftotext, "-layout", str(source), "-"], text=True).split(  # noqa: S603
            "\f"
        )
        if not text[-1].strip():
            text.pop()
        assert len(text) == 92, "Review a changed source edition before exporting"
        destination = ASSETS / language
        destination.mkdir(exist_ok=True)
        pages = []
        with tempfile.TemporaryDirectory(prefix="geode-report-pages-") as temporary:
            prefix = Path(temporary) / "page"
            subprocess.run(  # noqa: S603 — resolved local tool and fixed repository inputs
                [pdftoppm, "-scale-to", str(WIDTH), "-png", str(source), str(prefix)],
                check=True,
            )
            images = sorted(Path(temporary).glob("page-*.png"))
            assert len(images) == len(text)
            for number, (image, transcript) in enumerate(zip(images, text, strict=True), 1):
                name = f"{number:02}.webp"
                target = destination / name
                with Image.open(image) as original:
                    original.convert("RGB").save(target, "WEBP", lossless=True, method=4)
                    width, height = original.size
                pages.append(
                    {
                        "number": number,
                        "image": name,
                        "title": page_title(transcript),
                        "text": transcript.strip(),
                    }
                )
                records.append(
                    {
                        "path": f"{language}/{name}",
                        "sha256": digest(target),
                        "bytes": target.stat().st_size,
                        "width": width,
                        "height": height,
                    }
                )
        assert digest(source) == source_hash, "Source PDF changed during export"
        editions[language] = {"pdf": f"/geode/{filename}", "sha256": source_hash, "pages": pages}
        print(f"{language}: {len(pages)} pages exported", flush=True)
    DATA.write_text(json.dumps(editions, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "schema": "geode-report-pages-v1",
        "renderer": "Poppler pdftoppm, 1600px long edge; Pillow lossless WebP",
        "source_commit": "737416726cf68bde2ad7e7838133715a0a4e89c4",
        "text_sha256": digest(DATA),
        "sources": {
            lang: {"pdf": data["pdf"], "sha256": data["sha256"], "pages": len(data["pages"])}
            for lang, data in editions.items()
        },
        "images": records,
    }
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(records)} lossless images; {sum(row['bytes'] for row in records):,} bytes")


if __name__ == "__main__":
    main()
