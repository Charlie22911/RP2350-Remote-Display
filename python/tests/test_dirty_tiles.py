from __future__ import annotations

from contextlib import contextmanager
import unittest

from rp2350_remote_display.dirty_tiles import DirtyTilePresenter
from rp2350_remote_display.display import DisplayInfo, TileTransferStats
from rp2350_remote_display.protocol import CAP_DIRTY_TILE_PRESENT, SCREEN_HEIGHT, SCREEN_WIDTH, TILE_PROFILES


class FakeDisplay:
    def __init__(self) -> None:
        self.info = DisplayInfo(
            6,
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            18,
            24,
            30,
            40,
            45,
            60,
            4096,
            CAP_DIRTY_TILE_PRESENT,
        )
        self._stats = TileTransferStats()
        self.frames = 0
        self.tiles: list[tuple[int, int, int, int, bytes]] = []

    def _resolve_tile_profile(self, profile):
        return TILE_PROFILES[profile]

    @property
    def tile_transfer_stats(self) -> TileTransferStats:
        return self._stats

    @contextmanager
    def frame(self, timeout_ms=None):
        self.frames += 1
        yield self

    def blit_rgb565(self, x, y, width, height, pixels, compression="auto"):
        self.tiles.append((x, y, width, height, pixels))
        payload = len(pixels) + 12
        self._stats = TileTransferStats(
            direct_tiles=self._stats.direct_tiles + 1,
            encoded_bytes=self._stats.encoded_bytes + len(pixels),
            transfer_payload_bytes=self._stats.transfer_payload_bytes + payload,
            packet_count=self._stats.packet_count + 1,
            packet_header_bytes=self._stats.packet_header_bytes + 12,
            wire_bytes=self._stats.wire_bytes + payload + 12,
        )


class DirtyTileTests(unittest.TestCase):
    def test_initial_present_sends_full_grid_then_only_changed_tile(self) -> None:
        display = FakeDisplay()
        presenter = DirtyTilePresenter(display, tile_profile="medium")
        blank = bytes(SCREEN_WIDTH * SCREEN_HEIGHT * 2)

        initial = presenter.present(blank)
        self.assertEqual(initial.changed_tiles, 225)
        self.assertEqual(len(display.tiles), 225)

        unchanged = presenter.present(blank)
        self.assertFalse(unchanged.frame_sent)
        self.assertEqual(unchanged.changed_tiles, 0)
        self.assertEqual(len(display.tiles), 225)

        changed = bytearray(blank)
        changed[(17 * SCREEN_WIDTH + 31) * 2:(17 * SCREEN_WIDTH + 31) * 2 + 2] = b"\xff\xff"
        delta = presenter.present(changed)
        self.assertEqual(delta.changed_tiles, 1)
        self.assertEqual(len(display.tiles), 226)
        x, y, width, height, _ = display.tiles[-1]
        self.assertEqual((x, y, width, height), (30, 0, 30, 40))


    def test_rect_mode_sends_only_the_changed_bounds_inside_a_tile(self) -> None:
        display = FakeDisplay()
        presenter = DirtyTilePresenter(display, tile_profile="medium", region_mode="rect", compression="raw")
        blank = bytes(SCREEN_WIDTH * SCREEN_HEIGHT * 2)
        presenter.present(blank)

        changed = bytearray(blank)
        pixel_offset = (17 * SCREEN_WIDTH + 31) * 2
        changed[pixel_offset:pixel_offset + 2] = b"\xff\xff"
        result = presenter.present(changed)

        self.assertEqual(result.changed_tiles, 1)
        self.assertEqual(result.changed_regions, 1)
        self.assertEqual(result.raw_changed_bytes, 2)
        x, y, width, height, pixels = display.tiles[-1]
        self.assertEqual((x, y, width, height, pixels), (31, 17, 1, 1, b"\xff\xff"))

    def test_force_frame_exercises_empty_transaction(self) -> None:
        display = FakeDisplay()
        presenter = DirtyTilePresenter(display, tile_profile="small")
        blank = bytes(SCREEN_WIDTH * SCREEN_HEIGHT * 2)
        presenter.present(blank)
        result = presenter.present(blank, force_frame=True)
        self.assertTrue(result.frame_sent)
        self.assertEqual(result.changed_tiles, 0)
        self.assertEqual(result.transfer.packet_count, 0)


if __name__ == "__main__":
    unittest.main()
