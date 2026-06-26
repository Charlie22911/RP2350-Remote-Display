from __future__ import annotations

import unittest

from PIL import Image

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay, RemoteDisplayError, TileTransferStats
from rp2350_remote_display.protocol import (
    BLIT_TILE_STRUCT,
    CAP_RGB565_SCALE2,
    CAP_PALETTE4_SCALE2,
    CAP_PALETTE64_SCALE2,
    CODEC_RAW,
    CODEC_PALETTE4,
    CODEC_PALETTE64,
    MSG_BLIT_TILE,
    PIXEL_RGB565_SCALE2,
    PIXEL_INDEX4_SCALE2,
    PIXEL_INDEX6_SCALE2,
    PROTOCOL_VERSION,
)


class Scale2CommandTests(unittest.TestCase):
    def make_display(self) -> RemoteDisplay:
        display = object.__new__(RemoteDisplay)
        display.info = DisplayInfo(
            PROTOCOL_VERSION, 450, 600, 18, 24, 30, 40, 45, 60, 4096, CAP_RGB565_SCALE2 | CAP_PALETTE4_SCALE2 | CAP_PALETTE64_SCALE2
        )
        display._active_frame_id = 1
        display._tile_id = 1
        display._tile_transfer_stats = TileTransferStats()
        display._writes = []

        def write(message_type: int, payload: bytes = b"", flags: int = 0) -> int:
            display._writes.append((message_type, payload, flags))
            return len(display._writes)

        display._write = write
        return display

    def test_blit_rgb565_scale2_uses_source_dimensions(self) -> None:
        display = self.make_display()
        pixels = bytes((0x34, 0x12, 0x78, 0x56, 0xBC, 0x9A, 0xF0, 0xDE))
        display.blit_rgb565_scale2(10, 12, 2, 2, pixels, compression="raw")
        self.assertEqual(len(display._writes), 1)
        message_type, payload, flags = display._writes[0]
        self.assertEqual((message_type, flags), (MSG_BLIT_TILE, 0))
        x, y, width, height, color, pixel_format, codec = BLIT_TILE_STRUCT.unpack(payload[:BLIT_TILE_STRUCT.size])
        self.assertEqual((x, y, width, height, color, pixel_format, codec), (10, 12, 2, 2, 0, PIXEL_RGB565_SCALE2, CODEC_RAW))
        self.assertEqual(payload[BLIT_TILE_STRUCT.size:], pixels)

    def test_draw_image_scale2_tiles_and_doubles_dest_coordinates(self) -> None:
        display = self.make_display()
        image = Image.new("RGB", (16, 21))
        for y in range(image.height):
            for x in range(image.width):
                image.putpixel((x, y), ((x * 17) & 255, (y * 29) & 255, ((x + y) * 11) & 255))
        display.draw_image_scale2(image, 4, 6, compression="raw")
        self.assertEqual(len(display._writes), 4)
        positions = []
        sizes = []
        for message_type, payload, flags in display._writes:
            self.assertEqual((message_type, flags), (MSG_BLIT_TILE, 0))
            x, y, width, height, color, pixel_format, codec = BLIT_TILE_STRUCT.unpack(payload[:BLIT_TILE_STRUCT.size])
            self.assertEqual(pixel_format, PIXEL_RGB565_SCALE2)
            self.assertEqual(codec, CODEC_RAW)
            positions.append((x, y))
            sizes.append((width, height))
        self.assertEqual(positions, [(4, 6), (34, 6), (4, 46), (34, 46)])
        self.assertEqual(sizes, [(15, 20), (1, 20), (15, 1), (1, 1)])

    def test_scale2_validates_capability_and_bounds(self) -> None:
        display = self.make_display()
        display.info = DisplayInfo(
            PROTOCOL_VERSION, 450, 600, 18, 24, 30, 40, 45, 60, 4096, 0
        )
        with self.assertRaises(RemoteDisplayError):
            display.blit_rgb565_scale2(0, 0, 1, 1, b"\x00\x00", compression="raw")

        display = self.make_display()
        with self.assertRaises(ValueError):
            display.blit_rgb565_scale2(0, 0, 16, 20, b"\x00\x00" * (16 * 20), compression="raw")
        with self.assertRaises(ValueError):
            display.draw_image_scale2(Image.new("RGB", (226, 300)))

    def test_blit_palette4_scale2_packs_indices_and_palette(self) -> None:
        display = self.make_display()
        display.blit_palette4_scale2(8, 10, 3, 2, [0x1111, 0x2222, 0x3333], bytes([0, 1, 2, 1, 0, 2]))
        self.assertEqual(len(display._writes), 1)
        message_type, payload, flags = display._writes[0]
        self.assertEqual((message_type, flags), (MSG_BLIT_TILE, 0))
        x, y, width, height, color, pixel_format, codec = BLIT_TILE_STRUCT.unpack(payload[:BLIT_TILE_STRUCT.size])
        self.assertEqual((x, y, width, height, color, pixel_format, codec), (8, 10, 3, 2, 0, PIXEL_INDEX4_SCALE2, CODEC_PALETTE4))
        encoded = payload[BLIT_TILE_STRUCT.size:]
        self.assertEqual(encoded[0], 3)
        self.assertEqual(encoded[1:7], bytes([0x11,0x11,0x22,0x22,0x33,0x33]))
        self.assertEqual(encoded[7:], bytes([0x01, 0x21, 0x02]))

    def test_draw_image_scale2_palette4_creates_scale2_tiles(self) -> None:
        display = self.make_display()
        image = Image.new("RGB", (16, 21))
        for y in range(image.height):
            for x in range(image.width):
                image.putpixel((x, y), ((x * 17) & 255, (y * 29) & 255, ((x + y) * 11) & 255))
        display.draw_image_scale2(image, 4, 6, compression="palette4", dither="floyd-steinberg")
        self.assertEqual(len(display._writes), 4)
        positions = []
        for message_type, payload, flags in display._writes:
            self.assertEqual((message_type, flags), (MSG_BLIT_TILE, 0))
            x, y, width, height, color, pixel_format, codec = BLIT_TILE_STRUCT.unpack(payload[:BLIT_TILE_STRUCT.size])
            self.assertEqual(pixel_format, PIXEL_INDEX4_SCALE2)
            self.assertEqual(codec, CODEC_PALETTE4)
            positions.append((x, y, width, height))
        self.assertEqual(positions, [(4, 6, 15, 20), (34, 6, 1, 20), (4, 46, 15, 1), (34, 46, 1, 1)])

    def test_blit_palette64_scale2_packs_indices_and_palette(self) -> None:
        display = self.make_display()
        display.blit_palette64_scale2(12, 14, 4, 2, [0x1111, 0x2222, 0x3333, 0x4444], bytes([0, 1, 2, 3, 3, 2, 1, 0]))
        self.assertEqual(len(display._writes), 1)
        message_type, payload, flags = display._writes[0]
        self.assertEqual((message_type, flags), (MSG_BLIT_TILE, 0))
        x, y, width, height, color, pixel_format, codec = BLIT_TILE_STRUCT.unpack(payload[:BLIT_TILE_STRUCT.size])
        self.assertEqual((x, y, width, height, color, pixel_format, codec), (12, 14, 4, 2, 0, PIXEL_INDEX6_SCALE2, CODEC_PALETTE64))
        encoded = payload[BLIT_TILE_STRUCT.size:]
        self.assertEqual(encoded[0], 4)
        self.assertEqual(encoded[1:9], bytes([0x11,0x11,0x22,0x22,0x33,0x33,0x44,0x44]))
        self.assertEqual(len(encoded[9:]), (8 * 6 + 7) // 8)

    def test_draw_image_scale2_palette64_creates_scale2_tiles(self) -> None:
        display = self.make_display()
        image = Image.new("RGB", (16, 21))
        for y in range(image.height):
            for x in range(image.width):
                image.putpixel((x, y), ((x * 17) & 255, (y * 29) & 255, ((x + y) * 11) & 255))
        display.draw_image_scale2(image, 4, 6, compression="palette64", dither="floyd-steinberg")
        self.assertEqual(len(display._writes), 4)
        positions = []
        for message_type, payload, flags in display._writes:
            self.assertEqual((message_type, flags), (MSG_BLIT_TILE, 0))
            x, y, width, height, color, pixel_format, codec = BLIT_TILE_STRUCT.unpack(payload[:BLIT_TILE_STRUCT.size])
            self.assertEqual(pixel_format, PIXEL_INDEX6_SCALE2)
            self.assertEqual(codec, CODEC_PALETTE64)
            positions.append((x, y, width, height))
        self.assertEqual(positions, [(4, 6, 15, 20), (34, 6, 1, 20), (4, 46, 15, 1), (34, 46, 1, 1)])


if __name__ == "__main__":
    unittest.main()
