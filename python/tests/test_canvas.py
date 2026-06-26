from __future__ import annotations

import unittest

from rp2350_remote_display import Canvas, rgb565, rgb565_to_rgb888


class CanvasTests(unittest.TestCase):
    def test_rgb565_round_trip_for_primary_colours(self) -> None:
        self.assertEqual(rgb565_to_rgb888(rgb565(255, 0, 0)), (255, 0, 0))
        self.assertEqual(rgb565_to_rgb888(rgb565(0, 255, 0)), (0, 255, 0))
        self.assertEqual(rgb565_to_rgb888(rgb565(0, 0, 255)), (0, 0, 255))

    def test_canvas_rgb565_output_is_panel_native_little_endian(self) -> None:
        canvas = Canvas(2, 1, background=rgb565(255, 0, 0))
        canvas.fill_rect(1, 0, 1, 1, rgb565(0, 255, 0))
        self.assertEqual(canvas.rgb565_bytes(), bytes((0x00, 0xF8, 0xE0, 0x07)))

    def test_half_open_fill_rectangle(self) -> None:
        black = rgb565(0, 0, 0)
        white = rgb565(255, 255, 255)
        canvas = Canvas(4, 4, background=black)
        canvas.fill_rect(1, 1, 2, 2, white)
        raw = canvas.rgb565_bytes()
        white_pixel = bytes((white & 0xFF, white >> 8))
        for y in range(4):
            for x in range(4):
                pixel = raw[(y * 4 + x) * 2:(y * 4 + x) * 2 + 2]
                self.assertEqual(pixel == white_pixel, 1 <= x < 3 and 1 <= y < 3)

    def test_copy_is_independent(self) -> None:
        black = rgb565(0, 0, 0)
        white = rgb565(255, 255, 255)
        original = Canvas(3, 3, background=black)
        copy = original.copy()
        copy.fill_rect(0, 0, 1, 1, white)
        self.assertNotEqual(original.rgb565_bytes(), copy.rgb565_bytes())

    def test_bounds_are_checked(self) -> None:
        canvas = Canvas(10, 10)
        with self.assertRaises(ValueError):
            canvas.fill_rect(9, 9, 2, 2, 0)
        with self.assertRaises(ValueError):
            canvas.text("x", 10, 0, 0)


if __name__ == "__main__":
    unittest.main()
