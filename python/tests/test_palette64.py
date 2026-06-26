from __future__ import annotations

import struct
import unittest

from PIL import Image

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay, TileTransferStats
from rp2350_remote_display.protocol import (
    BLIT_TILE_STRUCT,
    CAP_PALETTE64_TILES,
    CODEC_PALETTE64,
    MSG_BLIT_TILE,
    PIXEL_INDEX6,
    TILE_PROFILES,
)


def expand_palette64_tiles(width: int, height: int, tiles) -> bytes:
    output = bytearray(width * height * 2)
    for tile_x, tile_y, tile_width, tile_height, palette, indices in tiles:
        for row in range(tile_height):
            for column in range(tile_width):
                color = palette[indices[row * tile_width + column]]
                destination = ((tile_y + row) * width + tile_x + column) * 2
                output[destination] = color & 0xFF
                output[destination + 1] = color >> 8
    return bytes(output)


def unpack_index6(data: bytes, pixel_count: int) -> bytes:
    values = bytearray()
    for pixel in range(pixel_count):
        bit_offset = pixel * 6
        byte_offset = bit_offset // 8
        shift = bit_offset & 7
        packed = data[byte_offset]
        if shift > 2:
            packed |= data[byte_offset + 1] << 8
        values.append((packed >> shift) & 0x3F)
    return bytes(values)


class Palette64Tests(unittest.TestCase):
    def test_palette64_tiles_cover_canvas_and_use_at_most_64_colours(self) -> None:
        image = Image.new("RGB", (450, 600))
        pixels = image.load()
        for y in range(600):
            for x in range(450):
                pixels[x, y] = ((x * 7) & 255, (y * 5) & 255, ((x + y) * 3) & 255)

        parts = list(RemoteDisplay._palette64_image_tiles(None, image, TILE_PROFILES["medium"], dither="none"))
        self.assertEqual(len(parts), 225)
        palette_entries: set[int] = set()
        for _, _, width, height, palette, indices in parts:
            self.assertGreaterEqual(len(palette), 1)
            self.assertLessEqual(len(palette), 64)
            self.assertEqual(len(indices), width * height)
            self.assertTrue(all(index < len(palette) for index in indices))
            palette_entries.update(palette)
        self.assertLessEqual(len(palette_entries), 64)

    def test_floyd_steinberg_changes_the_rendered_palette64_output(self) -> None:
        image = Image.new("RGB", (96, 96))
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                pixels[x, y] = (
                    (x * 255) // (image.width - 1),
                    (y * 255) // (image.height - 1),
                    ((x + y) * 255) // (image.width + image.height - 2),
                )
        none_tiles = list(RemoteDisplay._palette64_image_tiles(None, image, TILE_PROFILES["medium"], dither="none"))
        dithered_tiles = list(RemoteDisplay._palette64_image_tiles(None, image, TILE_PROFILES["medium"], dither="floyd-steinberg"))
        none_rgb565 = expand_palette64_tiles(image.width, image.height, none_tiles)
        dithered_rgb565 = expand_palette64_tiles(image.width, image.height, dithered_tiles)
        changed_pixels = sum(
            none_rgb565[offset:offset + 2] != dithered_rgb565[offset:offset + 2]
            for offset in range(0, len(none_rgb565), 2)
        )
        self.assertGreater(changed_pixels, 100)

    def test_blit_palette64_packs_lsb_first_six_bit_indices(self) -> None:
        display = RemoteDisplay.__new__(RemoteDisplay)
        display.info = DisplayInfo(12, 450, 600, 18, 24, 30, 40, 45, 60, 4096, CAP_PALETTE64_TILES)
        display._active_frame_id = 1
        display._tile_id = 1
        display._tile_transfer_stats = TileTransferStats()
        sent: list[tuple[int, bytes]] = []

        def write(message_type: int, payload: bytes = b"", flags: int = 0) -> int:
            self.assertEqual(flags, 0)
            sent.append((message_type, payload))
            return len(sent)

        display._write = write
        palette = (0x0000, 0x1234, 0xABCD)
        indices = bytes((0, 1, 2, 2, 1, 0))
        display.blit_palette64(0, 0, 3, 2, palette, indices)
        self.assertEqual([message for message, _ in sent], [MSG_BLIT_TILE])
        header = sent[0][1][:BLIT_TILE_STRUCT.size]
        x, y, width, height, color, pixel_format, codec = BLIT_TILE_STRUCT.unpack(header)
        self.assertEqual((x, y, width, height, color, pixel_format, codec), (0, 0, 3, 2, 0, PIXEL_INDEX6, CODEC_PALETTE64))
        encoded = sent[0][1][BLIT_TILE_STRUCT.size:]
        self.assertEqual(encoded[0], 3)
        self.assertEqual(struct.unpack_from("<HHH", encoded, 1), palette)
        self.assertEqual(unpack_index6(encoded[7:], 6), indices)

    def test_palette64_validates_palette_and_index_bounds(self) -> None:
        display = RemoteDisplay.__new__(RemoteDisplay)
        display.info = DisplayInfo(12, 450, 600, 18, 24, 30, 40, 45, 60, 4096, CAP_PALETTE64_TILES)
        display._active_frame_id = 1
        display._tile_id = 1
        display._tile_transfer_stats = TileTransferStats()
        display._write = lambda *args, **kwargs: 1
        with self.assertRaises(ValueError):
            display.blit_palette64(0, 0, 1, 1, tuple(range(65)), b"\x00")
        with self.assertRaises(ValueError):
            display.blit_palette64(0, 0, 1, 1, (0x0000,), b"\x01")


if __name__ == "__main__":
    unittest.main()
