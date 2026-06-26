#!/usr/bin/env python3
"""Verify the committed GNU Unifont source and flash asset agree."""
from __future__ import annotations

import gzip
import hashlib
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "firmware" / "assets" / "unifont_all-17.0.04.hex.gz"
ASSET = ROOT / "firmware" / "assets" / "unifont_all-17.0.04.bin"
HEADER = struct.Struct("<4sBBBBIIII")
ENTRY = struct.Struct("<IIB")
EXPECTED_SOURCE_SHA256 = "c31d210962408a00de8e2ebe2f2fc26824d7a4939d4eb15d347761fb2a0b39a6"
EXPECTED_GLYPHS = 127011
EXPECTED_ASSET_BYTES = 4873523


def source_records() -> list[tuple[int, int, bytes]]:
    records: list[tuple[int, int, bytes]] = []
    with gzip.open(SOURCE, "rt", encoding="ascii") as stream:
        for line_number, line in enumerate(stream, 1):
            codepoint_text, bitmap_text = line.strip().split(":", 1)
            bitmap = bytes.fromhex(bitmap_text)
            if len(bitmap) not in (16, 32):
                raise AssertionError(f"line {line_number}: unsupported glyph byte count {len(bitmap)}")
            records.append((int(codepoint_text, 16), len(bitmap) // 16, bitmap))
    return records


def main() -> int:
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED_SOURCE_SHA256
    records = source_records()
    assert len(records) == EXPECTED_GLYPHS
    assert [codepoint for codepoint, _, _ in records] == sorted(codepoint for codepoint, _, _ in records)

    data = ASSET.read_bytes()
    assert len(data) == EXPECTED_ASSET_BYTES
    magic, version, cell_width, cell_height, reserved, count, map_offset, bitmap_offset, total_size = HEADER.unpack_from(data)
    assert (magic, version, cell_width, cell_height, reserved) == (b"RUF1", 1, 8, 16, 0)
    assert count == EXPECTED_GLYPHS
    assert map_offset == HEADER.size
    assert bitmap_offset == HEADER.size + count * ENTRY.size
    assert total_size == len(data)

    bitmap = memoryview(data)[bitmap_offset:]
    previous = -1
    for index, (expected_codepoint, expected_columns, expected_rows) in enumerate(records):
        codepoint, offset, columns = ENTRY.unpack_from(data, map_offset + index * ENTRY.size)
        assert codepoint == expected_codepoint and codepoint > previous
        assert columns == expected_columns
        assert bitmap[offset:offset + 16 * columns].tobytes() == expected_rows
        previous = codepoint

    entries = {codepoint: columns for codepoint, columns, _ in records}
    assert entries[0x003F] == 1
    assert entries[0x2500] == 1
    assert entries[0x6F22] == 2
    assert entries[0x1F434] == 2
    assert 0x10FFFF not in entries
    print(f"GNU Unifont asset verified: {count} glyphs, {len(data)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
