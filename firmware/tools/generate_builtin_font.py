#!/usr/bin/env python3
"""Build the flash-resident GNU Unifont bitmap asset.

Normal firmware builds link the committed binary asset directly and do not need
Python or font-generation dependencies. This tool is only for deliberate font
asset regeneration.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import struct
from pathlib import Path

FORMAT_MAGIC = b"RUF1"
FORMAT_VERSION = 1
CELL_WIDTH = 8
CELL_HEIGHT = 16
HEADER = struct.Struct("<4sBBBBIIII")
MAP_ENTRY = struct.Struct("<IIB")


def parse_hex_source(source: Path) -> list[tuple[int, int, bytes]]:
    glyphs: list[tuple[int, int, bytes]] = []
    previous = -1
    with gzip.open(source, "rt", encoding="ascii", newline="") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                codepoint_text, bitmap_text = line.split(":", 1)
                codepoint = int(codepoint_text, 16)
                bitmap = bytes.fromhex(bitmap_text)
            except ValueError as exc:
                raise RuntimeError(f"invalid GNU Unifont record on line {line_number}") from exc
            if not 0 <= codepoint <= 0x10FFFF:
                raise RuntimeError(f"codepoint outside Unicode range on line {line_number}")
            if codepoint <= previous:
                raise RuntimeError(f"codepoints are not strictly sorted on line {line_number}")
            if len(bitmap) == CELL_HEIGHT:
                columns = 1
            elif len(bitmap) == CELL_HEIGHT * 2:
                columns = 2
            else:
                raise RuntimeError(
                    f"unsupported bitmap width on line {line_number}: expected 16 or 32 bytes, got {len(bitmap)}"
                )
            glyphs.append((codepoint, columns, bitmap))
            previous = codepoint
    if not glyphs:
        raise RuntimeError("the GNU Unifont source contains no glyphs")
    if not any(codepoint == 0x003F for codepoint, _, _ in glyphs):
        raise RuntimeError("the GNU Unifont source must include U+003F QUESTION MARK")
    return glyphs


def build_blob(glyphs: list[tuple[int, int, bytes]]) -> bytes:
    map_offset = HEADER.size
    bitmap_offset = map_offset + len(glyphs) * MAP_ENTRY.size
    bitmap_data = bytearray()
    entries = bytearray()

    for codepoint, columns, bitmap in glyphs:
        offset = len(bitmap_data)
        entries.extend(MAP_ENTRY.pack(codepoint, offset, columns))
        bitmap_data.extend(bitmap)

    total_size = bitmap_offset + len(bitmap_data)
    header = HEADER.pack(
        FORMAT_MAGIC,
        FORMAT_VERSION,
        CELL_WIDTH,
        CELL_HEIGHT,
        0,
        len(glyphs),
        map_offset,
        bitmap_offset,
        total_size,
    )
    return header + entries + bitmap_data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("firmware/assets/unifont_all-17.0.04.hex.gz"),
        help="GNU Unifont 17.0.04 .hex.gz source",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("firmware/assets/unifont_all-17.0.04.bin"),
        help="generated binary font asset",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"font source was not found: {args.input}")
    glyphs = parse_hex_source(args.input)
    blob = build_blob(glyphs)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_bytes(blob)
    temporary.replace(args.output)

    source_sha256 = hashlib.sha256(args.input.read_bytes()).hexdigest()
    print(
        f"Generated {args.output}: {len(glyphs)} glyphs, {len(blob)} bytes, "
        f"source SHA-256 {source_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
