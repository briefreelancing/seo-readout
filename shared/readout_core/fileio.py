"""Low-level file reading: encodings, delimiters, zip bundles, table blocks.

Exports from Google tools are messy: byte order marks, UTF-16 "Excel CSV"
variants, metadata lines starting with '#', title lines above the header,
and several tables in one file. This module turns any of that into a list of
TableBlock objects without guessing what the columns mean.
"""

from __future__ import annotations

import codecs
import csv
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RawFile:
    """One logical file. Files inside a zip keep the zip name as their bundle."""

    name: str
    text: str
    bundle: str | None = None  # zip file name, or folder name, if grouped


@dataclass
class TableBlock:
    """A contiguous block of non-empty rows, plus any metadata seen above it."""

    rows: list[list[str]]
    meta: dict[str, str] = field(default_factory=dict)  # from '# Key: value' lines
    preamble: list[str] = field(default_factory=list)  # free text lines above the table


def decode_bytes(data: bytes) -> str:
    """Decode export bytes, handling the encodings Google tools are known to use."""
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16", errors="replace")
    # UTF-16 without a BOM shows up as many NUL bytes.
    sample = data[:2000]
    if sample and sample.count(b"\x00") > len(sample) // 4:
        try:
            return data.decode("utf-16-le", errors="replace")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def sniff_delimiter(text: str) -> str:
    """Pick tab or comma by counting them on the first real lines."""
    lines = [ln for ln in text.splitlines()[:60] if ln.strip() and not ln.lstrip().startswith("#")]
    tabs = sum(ln.count("\t") for ln in lines)
    commas = sum(ln.count(",") for ln in lines)
    semis = sum(ln.count(";") for ln in lines)
    if tabs >= commas and tabs >= semis and tabs > 0:
        return "\t"
    if semis > commas:
        return ";"
    return ","


def load_paths(paths: list[str | Path]) -> list[RawFile]:
    """Read files, folders and zip archives into RawFile objects."""
    out: list[RawFile] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix.lower() in {".csv", ".tsv", ".txt", ".zip"}:
                    out.extend(_load_one(child, bundle=p.name))
        elif p.is_file():
            out.extend(_load_one(p, bundle=None))
        else:
            raise FileNotFoundError(f"Not found: {p}")
    return out


def _load_one(path: Path, bundle: str | None) -> list[RawFile]:
    if path.suffix.lower() == ".zip":
        files: list[RawFile] = []
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.lower().endswith((".csv", ".tsv", ".txt")):
                    continue
                files.append(
                    RawFile(name=Path(info.filename).name, text=decode_bytes(zf.read(info)), bundle=path.name)
                )
        return files
    return [RawFile(name=path.name, text=decode_bytes(path.read_bytes()), bundle=bundle)]


def split_blocks(text: str) -> list[TableBlock]:
    """Split a file into table blocks separated by blank or '#' comment lines."""
    delim = sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    blocks: list[TableBlock] = []
    meta: dict[str, str] = {}
    current: list[list[str]] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append(TableBlock(rows=current, meta=dict(meta)))
            current = []

    for row in reader:
        cells = [c.strip().strip("﻿") for c in row]
        if not any(cells):
            flush()
            continue
        if cells[0].startswith("#"):
            flush()
            line = ",".join(c for c in cells if c).lstrip("#").strip()
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
            continue
        current.append(cells)
    flush()
    return blocks
