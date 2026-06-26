from __future__ import annotations

import unittest

from rp2350_remote_display.canvas import Canvas
from rp2350_remote_display.display import DisplayInfo, RemoteDisplay, RemoteDisplayError
from rp2350_remote_display.protocol import (
    CAP_COPY_RECT,
    CAP_SCROLL_RECT,
    COPY_RECT_STRUCT,
    MSG_COPY_RECT,
    MSG_SCROLL_RECT,
    PROTOCOL_VERSION,
    SCROLL_RECT_STRUCT,
)


class CopyScrollCommandTests(unittest.TestCase):
    def make_display(self, capabilities: int = CAP_COPY_RECT | CAP_SCROLL_RECT) -> RemoteDisplay:
        display = object.__new__(RemoteDisplay)
        display.info = DisplayInfo(
            PROTOCOL_VERSION, 450, 600, 18, 24, 30, 40, 45, 60, 4096, capabilities
        )
        display._active_frame_id = 7
        display._writes = []

        def write(message_type: int, payload: bytes = b"", flags: int = 0) -> int:
            display._writes.append((message_type, payload, flags))
            return len(display._writes)

        display._write = write
        return display

    def test_copy_rect_uses_compact_overlap_safe_command(self) -> None:
        display = self.make_display()
        display.copy_rect(4, 8, 120, 40, 12, 20)
        message_type, payload, flags = display._writes[0]
        self.assertEqual((message_type, flags), (MSG_COPY_RECT, 0))
        self.assertEqual(COPY_RECT_STRUCT.unpack(payload), (4, 8, 120, 40, 12, 20))

    def test_scroll_rect_uses_signed_deltas_and_fill_color(self) -> None:
        display = self.make_display()
        display.scroll_rect(20, 30, 200, 100, -8, 12, 0x1234)
        message_type, payload, flags = display._writes[0]
        self.assertEqual((message_type, flags), (MSG_SCROLL_RECT, 0))
        self.assertEqual(SCROLL_RECT_STRUCT.unpack(payload), (20, 30, 200, 100, -8, 12, 0x1234))

    def test_capability_and_bounds_rules_are_enforced(self) -> None:
        display = self.make_display(CAP_SCROLL_RECT)
        with self.assertRaises(RemoteDisplayError):
            display.copy_rect(0, 0, 1, 1, 1, 1)
        with self.assertRaises(ValueError):
            display.scroll_rect(440, 0, 20, 1, 0, 1)
        display._active_frame_id = None
        with self.assertRaises(RemoteDisplayError):
            display.scroll_rect(0, 0, 1, 1, 0, 1)


class CanvasCopyScrollTests(unittest.TestCase):
    @staticmethod
    def make_canvas() -> Canvas:
        canvas = Canvas(5, 4, (0, 0, 0))
        for y in range(canvas.height):
            for x in range(canvas.width):
                canvas.image.putpixel((x, y), (x * 30, y * 40, x + y))
        return canvas

    def test_copy_rect_uses_original_source_when_regions_overlap(self) -> None:
        canvas = self.make_canvas()
        before = canvas.image.copy()
        canvas.copy_rect(0, 1, 4, 2, 1, 1)
        for row in range(2):
            for column in range(4):
                self.assertEqual(canvas.image.getpixel((1 + column, 1 + row)), before.getpixel((column, 1 + row)))

    def test_scroll_rect_fills_exposed_pixels_and_moves_source(self) -> None:
        canvas = self.make_canvas()
        before = canvas.image.copy()
        fill = (9, 8, 7)
        canvas.scroll_rect(0, 0, 5, 4, -1, 1, fill)
        for x in range(5):
            self.assertEqual(canvas.image.getpixel((x, 0)), fill)
        for y in range(1, 4):
            self.assertEqual(canvas.image.getpixel((4, y)), fill)
        for y in range(1, 4):
            for x in range(4):
                self.assertEqual(canvas.image.getpixel((x, y)), before.getpixel((x + 1, y - 1)))

    def test_scroll_rect_matches_source_coordinates_in_all_directions(self) -> None:
        fill = (9, 8, 7)
        for delta_x, delta_y in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            with self.subTest(delta_x=delta_x, delta_y=delta_y):
                canvas = self.make_canvas()
                before = canvas.image.copy()
                canvas.scroll_rect(0, 0, 5, 4, delta_x, delta_y, fill)
                for y in range(4):
                    for x in range(5):
                        source_x = x - delta_x
                        source_y = y - delta_y
                        expected = (
                            before.getpixel((source_x, source_y))
                            if 0 <= source_x < 5 and 0 <= source_y < 4
                            else fill
                        )
                        self.assertEqual(canvas.image.getpixel((x, y)), expected)

    def test_scroll_rect_full_displacement_fills_the_rectangle(self) -> None:
        canvas = self.make_canvas()
        fill = (9, 8, 7)
        canvas.scroll_rect(0, 0, 5, 4, 5, 0, fill)
        for y in range(4):
            for x in range(5):
                self.assertEqual(canvas.image.getpixel((x, y)), fill)


if __name__ == "__main__":
    unittest.main()
