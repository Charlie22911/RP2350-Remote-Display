from __future__ import annotations

import struct
import unittest

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay, TileTransferStats
from rp2350_remote_display.protocol import (
    CAP_SEGMENTED_TILES,
    CAP_TILE_PROFILES,
    MSG_BLIT_TILE,
    MSG_TILE_BEGIN,
    MSG_TILE_CHUNK,
    MSG_TILE_END,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_PROFILES,
)


class TileProfileTests(unittest.TestCase):
    def test_profiles_divide_canvas_exactly(self) -> None:
        self.assertEqual((TILE_PROFILES["small"].columns, TILE_PROFILES["small"].rows), (25, 25))
        self.assertEqual((TILE_PROFILES["medium"].columns, TILE_PROFILES["medium"].rows), (15, 15))
        self.assertEqual((TILE_PROFILES["large"].columns, TILE_PROFILES["large"].rows), (10, 10))
        for profile in TILE_PROFILES.values():
            self.assertEqual(SCREEN_WIDTH % profile.width, 0)
            self.assertEqual(SCREEN_HEIGHT % profile.height, 0)

    def _display(self) -> tuple[RemoteDisplay, list[tuple[int, bytes]]]:
        display = RemoteDisplay.__new__(RemoteDisplay)
        display.info = DisplayInfo(
            6,
            450,
            600,
            18,
            24,
            30,
            40,
            45,
            60,
            4096,
            CAP_TILE_PROFILES | CAP_SEGMENTED_TILES,
        )
        display._active_frame_id = 1
        display._tile_id = 1
        display._tile_transfer_stats = TileTransferStats()
        sent: list[tuple[int, bytes]] = []

        def write(message_type: int, payload: bytes = b"") -> int:
            sent.append((message_type, payload))
            return len(sent)

        display._write = write
        return display, sent

    def test_medium_raw_tile_uses_one_packet(self) -> None:
        display, sent = self._display()
        display.blit_rgb565(0, 0, 30, 40, bytes(30 * 40 * 2), compression="raw")
        self.assertEqual([message for message, _ in sent], [MSG_BLIT_TILE])
        self.assertEqual(display.tile_transfer_stats.direct_tiles, 1)
        self.assertEqual(display.tile_transfer_stats.segmented_tiles, 0)

    def test_large_raw_tile_uses_transactional_segments(self) -> None:
        display, sent = self._display()
        pixels = struct.pack("<H", 0x1357) * (45 * 60)
        display.blit_rgb565(0, 0, 45, 60, pixels, compression="raw")
        self.assertEqual([message for message, _ in sent], [MSG_TILE_BEGIN, MSG_TILE_CHUNK, MSG_TILE_CHUNK, MSG_TILE_END])
        self.assertEqual(display.tile_transfer_stats.direct_tiles, 0)
        self.assertEqual(display.tile_transfer_stats.segmented_tiles, 1)
        self.assertEqual(display.tile_transfer_stats.encoded_bytes, 5400)


if __name__ == "__main__":
    unittest.main()
