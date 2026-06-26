from __future__ import annotations

import unittest

from rp2350_remote_display.layout import CoordinateSpace, DebugOverlay, Layout, Rect


class FakeDisplay:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def fill_rect(self, *args, **kwargs):
        self.calls.append(("fill_rect", args, kwargs))

    def stroke_rect(self, *args, **kwargs):
        self.calls.append(("stroke_rect", args, kwargs))

    def line(self, *args, **kwargs):
        self.calls.append(("line", args, kwargs))

    def polyline(self, *args, **kwargs):
        self.calls.append(("polyline", args, kwargs))

    def draw_text(self, *args, **kwargs):
        self.calls.append(("draw_text", args, kwargs))
        return (10, 10)

    def line_chart(self, *args, **kwargs):
        self.calls.append(("line_chart", args, kwargs))

    def bar_chart(self, *args, **kwargs):
        self.calls.append(("bar_chart", args, kwargs))

    def pie_chart(self, *args, **kwargs):
        self.calls.append(("pie_chart", args, kwargs))


class RectTests(unittest.TestCase):
    def test_half_open_geometry(self) -> None:
        rect = Rect(10, 20, 30, 40)
        self.assertEqual(rect.right, 40)
        self.assertEqual(rect.bottom, 60)
        self.assertTrue(rect.contains(10, 20))
        self.assertTrue(rect.contains(39, 59))
        self.assertFalse(rect.contains(40, 59))
        self.assertFalse(rect.contains(39, 60))

    def test_split_columns_covers_region_without_overlap(self) -> None:
        rect = Rect(0, 0, 410, 50)
        columns = rect.split_columns(3, gap=10)
        self.assertEqual([(part.x, part.width) for part in columns], [(0, 130), (140, 130), (280, 130)])
        self.assertEqual(columns[0].x, rect.x)
        self.assertEqual(columns[-1].right, rect.right)

    def test_split_rows_covers_region_without_overlap(self) -> None:
        rect = Rect(0, 0, 50, 101)
        rows = rect.split_rows(3, gap=2)
        self.assertEqual(sum(row.height for row in rows) + 4, 101)
        self.assertEqual(rows[0].y, 0)
        self.assertEqual(rows[-1].bottom, 101)


class CoordinateSpaceTests(unittest.TestCase):
    def test_pixel_space_is_identity(self) -> None:
        space = CoordinateSpace.pixels()
        self.assertEqual(space.point(0, 0), (0, 0))
        self.assertEqual(space.point(449, 599), (449, 599))
        self.assertEqual(space.rect(20, 30, 410, 540), Rect(20, 30, 410, 540))

    def test_design_space_maps_half_open_edges_exactly(self) -> None:
        space = CoordinateSpace.design(1000, 1000)
        self.assertEqual(space.rect(0, 0, 1000, 1000), Rect(0, 0, 450, 600))
        self.assertEqual(space.rect(250, 420, 500, 200), Rect(112, 252, 226, 120))
        self.assertEqual(space.point(0, 0), (0, 0))
        self.assertEqual(space.point(999, 999), (449, 599))

    def test_rejects_out_of_range_points_and_rectangles(self) -> None:
        space = CoordinateSpace.design(1000, 1000)
        with self.assertRaises(ValueError):
            space.point(1000, 10)
        with self.assertRaises(ValueError):
            space.rect(900, 0, 101, 10)


class LayoutTests(unittest.TestCase):
    def test_text_box_centers_inside_bounds(self) -> None:
        display = FakeDisplay()
        layout = Layout(display)
        layout.text_box(Rect(20, 30, 200, 40), "HELLO", 0xFFFF, align="center", valign="middle")
        calls = [call for call in display.calls if call[0] == "draw_text"]
        self.assertEqual(len(calls), 1)
        _, args, _ = calls[0]
        _, x, y, _ = args[:4]
        self.assertGreaterEqual(x, 20)
        self.assertGreaterEqual(y, 30)
        self.assertLess(x, 220)
        self.assertLess(y, 70)

    def test_text_box_rejects_overflow(self) -> None:
        display = FakeDisplay()
        layout = Layout(display)
        with self.assertRaises(ValueError):
            layout.text_box(Rect(0, 0, 4, 4), "TOO LONG", 0xFFFF)

    def test_debug_overlay_draws_grid_and_bounds(self) -> None:
        display = FakeDisplay()
        layout = Layout(display, debug=DebugOverlay(enabled=True, minor_grid=100, major_grid=200, show_labels=False))
        layout.begin_debug_overlay()
        layout.region("card", Rect(20, 20, 100, 80))
        layout.end_debug_overlay()
        names = [name for name, _, _ in display.calls]
        self.assertIn("line", names)
        self.assertIn("stroke_rect", names)


if __name__ == "__main__":
    unittest.main()
