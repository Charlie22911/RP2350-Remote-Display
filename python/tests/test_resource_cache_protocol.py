from __future__ import annotations

import struct
import unittest

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay
from rp2350_remote_display.protocol import (
    CAP_RESOURCE_CACHE,
    CODEC_RLE,
    MSG_ACK,
    MSG_RESOURCE_BEGIN,
    MSG_RESOURCE_CHUNK,
    MSG_RESOURCE_END,
    PACKET_FLAG_TILE_CONTENT_CRC32,
    PIXEL_RGB565,
    PROTOCOL_VERSION,
    Packet,
    RESOURCE_BEGIN_STRUCT,
    RESOURCE_CHUNK_PREFIX_STRUCT,
    rle_encode_rgb565,
)


class ResourceCacheProtocolTests(unittest.TestCase):
    def make_display(self, *, strict_packet_crc: bool = False, strict_tile_crc: bool = False) -> RemoteDisplay:
        display = object.__new__(RemoteDisplay)
        display.info = DisplayInfo(
            PROTOCOL_VERSION,
            450,
            600,
            18,
            24,
            30,
            40,
            45,
            60,
            4096,
            CAP_RESOURCE_CACHE,
        )
        display._active_frame_id = None
        display._strict_packet_crc = strict_packet_crc
        display._strict_tile_crc = strict_tile_crc
        display.timeout_ms = 1000
        display._writes = []

        def write(message_type: int, payload: bytes = b"", flags: int = 0) -> int:
            display._writes.append((message_type, payload, flags))
            return len(display._writes)

        def wait_for(sequence: int, expected_type: int, timeout_ms: int | None = None) -> Packet:
            self.assertEqual(expected_type, MSG_ACK)
            return Packet(MSG_ACK, 0, sequence, b"\x00")

        display._write = write
        display._wait_for = wait_for
        return display

    def test_segmented_rle_resource_upload(self) -> None:
        display = self.make_display(strict_tile_crc=True)
        raw = bytearray()
        for index in range(45 * 60):
            raw.extend(struct.pack("<H", 0xF800 if index % 2 else 0x07FF))
        encoded = rle_encode_rgb565(bytes(raw))
        self.assertGreater(len(encoded), 4096)

        stats = display.cache_rgb565(7, 45, 60, bytes(raw), compression="rle")
        self.assertEqual(stats.resource_id, 7)
        self.assertEqual(stats.encoded_bytes, len(encoded))
        self.assertEqual(stats.codec, CODEC_RLE)
        self.assertEqual(display._writes[0][0], MSG_RESOURCE_BEGIN)
        self.assertEqual(display._writes[-1][0], MSG_RESOURCE_END)
        self.assertEqual(display._writes[0][2], PACKET_FLAG_TILE_CONTENT_CRC32)
        self.assertEqual(len(display._writes), stats.packet_count)

        resource_id, width, height, pixel_format, codec, length = RESOURCE_BEGIN_STRUCT.unpack_from(display._writes[0][1])
        self.assertEqual((resource_id, width, height, pixel_format, codec, length), (7, 45, 60, PIXEL_RGB565, CODEC_RLE, len(encoded)))
        for message_type, payload, _ in display._writes[1:-1]:
            self.assertEqual(message_type, MSG_RESOURCE_CHUNK)
            self.assertGreaterEqual(len(payload), RESOURCE_CHUNK_PREFIX_STRUCT.size + 1)

    def test_protocol_version(self) -> None:
        self.assertEqual(PROTOCOL_VERSION, 16)


if __name__ == "__main__":
    unittest.main()
