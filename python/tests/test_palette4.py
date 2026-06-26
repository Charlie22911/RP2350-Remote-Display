from __future__ import annotations

import unittest

from PIL import Image

from rp2350_remote_display.display import RemoteDisplay
from rp2350_remote_display.protocol import TILE_PROFILES


def expand_palette4_tiles(width: int, height: int, tiles) -> bytes:
    """Expand generated Palette4 tiles into their rendered RGB565 canvas."""
    output = bytearray(width * height * 2)
    for tile_x, tile_y, tile_width, tile_height, palette, indices in tiles:
        for row in range(tile_height):
            for column in range(tile_width):
                color = palette[indices[row * tile_width + column]]
                destination = ((tile_y + row) * width + tile_x + column) * 2
                output[destination] = color & 0xFF
                output[destination + 1] = color >> 8
    return bytes(output)


class Palette4Tests(unittest.TestCase):
    def test_palette4_tiles_cover_canvas_and_use_at_most_16_colours(self) -> None:
        image = Image.new("RGB", (450, 600))
        pixels = image.load()
        for y in range(600):
            for x in range(450):
                pixels[x, y] = ((x * 7) & 255, (y * 5) & 255, ((x + y) * 3) & 255)

        parts = list(RemoteDisplay._palette4_image_tiles(None, image, TILE_PROFILES["medium"], dither="none"))
        self.assertEqual(len(parts), 225)
        palette_entries: set[int] = set()
        for _, _, width, height, palette, indices in parts:
            self.assertGreaterEqual(len(palette), 1)
            self.assertLessEqual(len(palette), 16)
            self.assertEqual(len(indices), width * height)
            self.assertTrue(all(index < len(palette) for index in indices))
            palette_entries.update(palette)
        self.assertLessEqual(len(palette_entries), 16)

    def test_floyd_steinberg_changes_the_rendered_palette4_output(self) -> None:
        image = Image.new("RGB", (96, 96))
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                pixels[x, y] = (
                    (x * 255) // (image.width - 1),
                    (y * 255) // (image.height - 1),
                    ((x + y) * 255) // (image.width + image.height - 2),
                )

        none_tiles = list(
            RemoteDisplay._palette4_image_tiles(
                None,
                image,
                TILE_PROFILES["medium"],
                dither="none",
            )
        )
        dithered_tiles = list(
            RemoteDisplay._palette4_image_tiles(
                None,
                image,
                TILE_PROFILES["medium"],
                dither="floyd-steinberg",
            )
        )
        self.assertEqual(len(none_tiles), 12)
        self.assertEqual(len(dithered_tiles), 12)
        for _, _, width, height, palette, indices in dithered_tiles:
            self.assertGreaterEqual(len(palette), 1)
            self.assertLessEqual(len(palette), 16)
            self.assertEqual(len(indices), width * height)
            self.assertTrue(all(index < len(palette) for index in indices))

        none_rgb565 = expand_palette4_tiles(image.width, image.height, none_tiles)
        dithered_rgb565 = expand_palette4_tiles(image.width, image.height, dithered_tiles)
        changed_pixels = sum(
            none_rgb565[offset:offset + 2] != dithered_rgb565[offset:offset + 2]
            for offset in range(0, len(none_rgb565), 2)
        )
        self.assertGreater(changed_pixels, 500)

    def test_palette4_dither_name_is_validated(self) -> None:
        image = Image.new("RGB", (18, 24), "navy")
        with self.assertRaises(ValueError):
            list(RemoteDisplay._palette4_image_tiles(None, image, TILE_PROFILES["small"], dither="unknown"))


if __name__ == "__main__":
    unittest.main()
