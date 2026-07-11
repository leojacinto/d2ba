#!/usr/bin/env python3
"""
convert.py — deterministic .docx -> Build Agent upload package converter.

No AI/LLM calls of any kind. Pure structural extraction:
  - Word body text/headings/tables -> one Markdown file (via pandoc, verbatim conversion)
  - Real embedded images (screenshots, diagrams, logos) -> standalone image files,
    converted to a Build-Agent-supported format if needed
  - Embedded OLE spreadsheets (Excel objects pasted/linked into the Word doc, which
    Word normally shows only as a small icon) -> one CSV per worksheet, so the actual
    field lists / report layouts aren't silently lost behind an icon image

Requires: pandoc (brew install pandoc), openpyxl (pip install openpyxl).
Optional: LibreOffice (soffice) or ImageMagick (magick/convert) on PATH to
auto-convert legacy vector formats (.wmf/.emf) that Pillow cannot rasterize.
"""
from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

BUILD_AGENT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
BUILD_AGENT_SIZE_LIMIT_MB = 10


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_pandoc():
    if shutil.which("pandoc") is None:
        die("pandoc is required (brew install pandoc / apt install pandoc) and was not found on PATH.")


def parse_rels(extract_dir: Path):
    rels_path = extract_dir / "word" / "_rels" / "document.xml.rels"
    rid_to_target = {}
    if rels_path.exists():
        tree = ET.parse(rels_path)
        for rel in tree.getroot():
            rid_to_target[rel.get("Id")] = rel.get("Target")
    return rid_to_target


def find_ole_icon_map(extract_dir: Path, rid_to_target: dict):
    """Return {embedded_file_relative_path: icon_file_relative_path or None}."""
    doc_xml = extract_dir / "word" / "document.xml"
    if not doc_xml.exists():
        return {}
    xml_text = doc_xml.read_text(encoding="utf-8", errors="ignore")

    shape_to_package_rid = {}
    for m in re.finditer(r'<o:OLEObject\b[^>]*ShapeID="([^"]+)"[^>]*r:id="([^"]+)"', xml_text):
        shape_to_package_rid[m.group(1)] = m.group(2)
    for m in re.finditer(r'<o:OLEObject\b[^>]*r:id="([^"]+)"[^>]*ShapeID="([^"]+)"', xml_text):
        shape_to_package_rid.setdefault(m.group(2), m.group(1))

    shape_to_icon_rid = {}
    for m in re.finditer(
        r'<v:shape\b[^>]*\bid="(ole_[^"]+)"[^>]*>.*?<v:imagedata\b[^>]*r:id="([^"]+)"',
        xml_text,
        re.DOTALL,
    ):
        shape_to_icon_rid[m.group(1)] = m.group(2)

    embedded_to_icon = {}
    for shape_id, package_rid in shape_to_package_rid.items():
        package_target = rid_to_target.get(package_rid)
        icon_rid = shape_to_icon_rid.get(shape_id)
        icon_target = rid_to_target.get(icon_rid) if icon_rid else None
        if package_target:
            embedded_to_icon[package_target] = icon_target
    return embedded_to_icon


def xlsx_to_csvs(xlsx_path: Path, out_dir: Path, base_label: str):
    import openpyxl

    written = []
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not any(any(cell is not None for cell in row) for row in rows):
            continue
        sheet_slug = re.sub(r"[^A-Za-z0-9]+", "-", ws.title).strip("-").lower()
        out_path = out_dir / f"{base_label}__{sheet_slug}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in rows:
                writer.writerow(["" if c is None else c for c in row])
        written.append(out_path)
    return written


def convert_image_to_png(src: Path, dest: Path) -> bool:
    """Try, in order: Pillow, LibreOffice, ImageMagick. Return True on success."""
    try:
        from PIL import Image

        im = Image.open(src)
        im.load()
        im.convert("RGB").save(dest, "PNG")
        return True
    except Exception:
        pass

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "png", "--outdir", str(dest.parent), str(src)],
                check=True, capture_output=True, timeout=60,
            )
            produced = dest.parent / (src.stem + ".png")
            if produced.exists():
                produced.rename(dest)
                return True
        except Exception:
            pass

    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        try:
            subprocess.run([magick, str(src), str(dest)], check=True, capture_output=True, timeout=60)
            return dest.exists()
        except Exception:
            pass

    return False


def convert(docx_path: Path, out_dir: Path) -> Path:
    """Convert a .docx into a Build Agent upload package. Returns out_dir."""
    check_pandoc()
    if not docx_path.exists():
        die(f"Input file not found: {docx_path}")

    base = docx_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    data_dir = out_dir / "embedded-data"
    manual_dir = out_dir / "manual-conversion-needed"
    raw_dir = out_dir / "_raw_media"
    for d in (images_dir, data_dir, manual_dir, raw_dir):
        d.mkdir(parents=True, exist_ok=True)

    work = out_dir / "_docx_extract"
    if work.exists():
        shutil.rmtree(work)
    with zipfile.ZipFile(docx_path) as z:
        z.extractall(work)

    rid_to_target = parse_rels(work)
    embedded_to_icon = find_ole_icon_map(work, rid_to_target)

    csv_queue_by_icon = {}
    for embedded_rel, icon_rel in embedded_to_icon.items():
        xlsx_path = work / "word" / embedded_rel
        if not xlsx_path.exists():
            continue
        label = re.sub(r"[^A-Za-z0-9]+", "-", xlsx_path.stem).strip("-").lower()
        csvs = xlsx_to_csvs(xlsx_path, data_dir, label)
        if icon_rel:
            icon_key = Path(icon_rel).name
            csv_queue_by_icon.setdefault(icon_key, []).append(csvs)

    raw_md = out_dir / "_raw.md"
    subprocess.run(
        ["pandoc", str(docx_path), "-f", "docx", "-t", "gfm",
         f"--extract-media={raw_dir}", "-o", str(raw_md), "--wrap=preserve"],
        check=True,
    )
    md_text = raw_md.read_text(encoding="utf-8")
    pandoc_media_dir = raw_dir / "media"

    manual_notes = []
    seen_images = set()
    icon_occurrence_index = {}

    def replace_img(match):
        src = match.group(1)
        fname = Path(src).name
        src_path = pandoc_media_dir / fname

        if fname in csv_queue_by_icon:
            idx = icon_occurrence_index.get(fname, 0)
            queue = csv_queue_by_icon[fname]
            if idx < len(queue):
                csvs = queue[idx]
                icon_occurrence_index[fname] = idx + 1
            else:
                csvs = queue[-1]
            names = ", ".join(f"`embedded-data/{c.name}`" for c in csvs)
            return (f"\n> **[Embedded spreadsheet extracted to CSV — see {names}]**\n"
                    f"> (Original Word doc showed this as an icon, not visible text; "
                    f"the actual field list/table is in the CSV file(s) above.)\n")

        if not src_path.exists():
            return match.group(0)

        ext = src_path.suffix.lower()
        if ext in BUILD_AGENT_IMAGE_EXTS:
            dest = images_dir / fname
            if fname not in seen_images:
                shutil.copy2(src_path, dest)
                seen_images.add(fname)
            return f"\n![{fname}](images/{fname})\n"

        png_name = src_path.stem + ".png"
        dest = images_dir / png_name
        if convert_image_to_png(src_path, dest):
            seen_images.add(png_name)
            return f"\n![{png_name}](images/{png_name})\n"
        else:
            manual_copy = manual_dir / fname
            shutil.copy2(src_path, manual_copy)
            manual_notes.append(fname)
            return (f"\n> **[Image `{fname}` could not be auto-converted from {ext} — "
                    f"copied to `manual-conversion-needed/{fname}` for manual conversion; "
                    f"not included inline.]**\n")

    md_text = re.sub(r'<img src="[^"]*media/([^"]+)"[^>]*/?>', replace_img, md_text)
    md_text = re.sub(r'</?figure>\s*', '', md_text)
    md_text = re.sub(r'</?figcaption>\s*', '', md_text)

    final_md = out_dir / f"{base}.md"
    final_md.write_text(md_text, encoding="utf-8")

    raw_md.unlink(missing_ok=True)
    shutil.rmtree(raw_dir, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    if not any(data_dir.iterdir()):
        data_dir.rmdir()
    if not any(manual_dir.iterdir()):
        manual_dir.rmdir()

    all_files = [final_md] + list(images_dir.glob("*")) + (list(data_dir.glob("*")) if data_dir.exists() else [])
    total_bytes = sum(f.stat().st_size for f in all_files)

    manifest_lines = [
        f"Spec file: {final_md.name} ({final_md.stat().st_size/1024:.1f} KB)",
        f"Images: {len(list(images_dir.glob('*')))} file(s) in images/",
    ]
    if data_dir.exists():
        manifest_lines.append(f"Embedded spreadsheets extracted: {len(list(data_dir.glob('*.csv')))} CSV file(s) in embedded-data/")
    if manual_notes:
        manifest_lines.append(f"Could not auto-convert {len(manual_notes)} image(s): {', '.join(manual_notes)} — see manual-conversion-needed/")
    manifest_lines.append(
        f"Total package size: {total_bytes/1024:.1f} KB "
        f"({'OK' if total_bytes < BUILD_AGENT_SIZE_LIMIT_MB*1024*1024 else 'EXCEEDS'} "
        f"Build Agent's {BUILD_AGENT_SIZE_LIMIT_MB} MB per-file limit — check individual files too)"
    )
    for line in manifest_lines:
        print(line)

    return out_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        die("Usage: python3 convert.py <input.docx> [output_dir]")
    docx_arg = Path(sys.argv[1]).expanduser().resolve()
    out_arg = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else Path.cwd() / f"{docx_arg.stem}_build_agent_package"
    convert(docx_arg, out_arg)
