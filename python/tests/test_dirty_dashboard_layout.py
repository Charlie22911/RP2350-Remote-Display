"""Geometry and incremental-renderer checks for the dirty dashboard example."""

from __future__ import annotations

from collections import deque
import importlib.util
import inspect
from pathlib import Path
import sys
import unittest


PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT / "src"))
EXAMPLE = PYTHON_ROOT / "examples" / "dirty_dashboard.py"
SPEC = importlib.util.spec_from_file_location("dirty_dashboard", EXAMPLE)
assert SPEC is not None and SPEC.loader is not None
DASHBOARD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DASHBOARD
SPEC.loader.exec_module(DASHBOARD)


def contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    outer_x, outer_y, outer_width, outer_height = outer
    inner_x, inner_y, inner_width, inner_height = inner
    return (
        outer_x <= inner_x
        and outer_y <= inner_y
        and inner_x + inner_width <= outer_x + outer_width
        and inner_y + inner_height <= outer_y + outer_height
    )


def sample_model() -> object:
    snapshot = DASHBOARD.Snapshot(
        timestamp=DASHBOARD.datetime.now().astimezone(),
        uptime_s=1.0,
        cpu_usage_percent=36.0,
        cpu_temp_c=42.0,
        cpu_freq_mhz=2400.0,
        cpu_max_freq_mhz=3000.0,
        ram_used_percent=48.0,
        ram_available_percent=52.0,
        swap_used_percent=0.0,
        ram_used_gib=7.7,
        ram_total_gib=16.0,
        disk_name="nvme0n1",
        disk_mountpoint="/",
        disk_used_percent=61.0,
        disk_used_gib=200.0,
        disk_total_gib=500.0,
        disk_activity_bps=None,
        disk_temp_c=None,
        net_iface="eth0",
        net_ip="192.0.2.1",
        net_rx_bps=12_000.0,
        net_tx_bps=12_000.0,
    )
    model = DASHBOARD.DashboardModel.__new__(DASHBOARD.DashboardModel)
    model.config = DASHBOARD.MonitorConfig(
        None,
        DASHBOARD.DiskTarget("nvme0n1", "/dev/nvme0n1", "", 0, "/"),
        15.0,
        60.0,
    )
    model.snapshot = snapshot
    model.history = {
        "cpu_usage": deque([36.0]),
        "cpu_temp": deque([42.0]),
        "cpu_freq": deque([2400.0]),
        "ram_used_percent": deque([48.0]),
        "ram_available_percent": deque([52.0]),
        "swap_used_percent": deque([0.0]),
        "disk_used_percent": deque([61.0]),
        "disk_activity_bps": deque(),
        "disk_temp": deque(),
        "net_rx": deque([12_000.0]),
        "net_tx": deque([12_000.0]),
    }
    model._seen_optional = {"disk_activity_bps": False, "disk_temp": False}
    model._scale_ceilings = {}
    model.selected_category = None
    model.sample_id = 0
    return model


class DirtyDashboardLayoutTests(unittest.TestCase):
    def test_dashboard_regions_fit_and_share_declared_walls(self) -> None:
        panel = DASHBOARD.PANEL_FRAME_RECT
        for rect in (
            DASHBOARD.HEADER_RECT,
            DASHBOARD.GRID_RECT,
            DASHBOARD.FOOTER_RECT,
            *DASHBOARD.CARD_RECTS.values(),
            *DASHBOARD.CARD_PLOT_RECTS.values(),
            *DASHBOARD.CARD_TITLE_RECTS.values(),
            *[item for pair in DASHBOARD.CARD_TEXT_RECTS.values() for item in pair],
        ):
            self.assertTrue(contains(panel, rect), rect)

        self.assertEqual(DASHBOARD.HEADER_RECT[1] + DASHBOARD.HEADER_RECT[3], DASHBOARD.GRID_RECT[1])
        self.assertEqual(DASHBOARD.GRID_RECT[1] + DASHBOARD.GRID_RECT[3], DASHBOARD.FOOTER_RECT[1])
        self.assertEqual(DASHBOARD.CARD_RECTS["cpu"][0] + DASHBOARD.CARD_RECTS["cpu"][2], DASHBOARD.VERTICAL_DIVIDER_X)
        self.assertEqual(DASHBOARD.CARD_RECTS["memory"][0], DASHBOARD.VERTICAL_DIVIDER_X + 1)
        self.assertEqual(DASHBOARD.CARD_RECTS["cpu"][1] + DASHBOARD.CARD_RECTS["cpu"][3], DASHBOARD.HORIZONTAL_DIVIDER_Y)
        self.assertEqual(DASHBOARD.CARD_RECTS["disk"][1], DASHBOARD.HORIZONTAL_DIVIDER_Y + 1)

    def test_title_text_and_plot_regions_remain_inside_each_card(self) -> None:
        for key, card in DASHBOARD.CARD_RECTS.items():
            self.assertTrue(contains(card, DASHBOARD.CARD_TITLE_RECTS[key]), key)
            for text_rect in DASHBOARD.CARD_TEXT_RECTS[key]:
                self.assertTrue(contains(card, text_rect), key)
            self.assertTrue(contains(card, DASHBOARD.CARD_PLOT_RECTS[key]), key)

    def test_network_scale_and_dashboard_metric_contracts(self) -> None:
        self.assertEqual(DASHBOARD.NETWORK_FULL_SCALE_BPS, 24_000.0)
        self.assertEqual(DASHBOARD.network_load_percent(12_000.0, 12_000.0), 100.0)
        self.assertEqual(DASHBOARD.network_load_percent(6_000.0, 6_000.0), 50.0)
        self.assertEqual(DASHBOARD.MAX_REFRESH_HZ, 15.0)

        categories = {category.key: category for category in sample_model().categories()}
        self.assertEqual(categories["cpu"].title, "CPU: 36%")
        self.assertEqual(categories["memory"].title, "MEMORY: 48%")
        self.assertEqual(categories["disk"].title, "DISK: nvme0n1")
        self.assertEqual(categories["network"].title, "NETWORK: 100%")
        self.assertEqual([spec.max_value for spec in categories["network"].series], [24_000.0, 24_000.0])
        self.assertNotIn("disk_latency_ms", DASHBOARD.Snapshot.__dataclass_fields__)
        self.assertNotIn("Latency", [spec.label for spec in categories["disk"].series])

    def test_fullscreen_header_footer_plot_and_back_button_share_declared_boundaries(self) -> None:
        panel = DASHBOARD.PANEL_FRAME_RECT
        self.assertTrue(contains(panel, DASHBOARD.FULLSCREEN_HEADER_RECT))
        self.assertTrue(contains(panel, DASHBOARD.BACK_BUTTON_RECT))
        self.assertTrue(contains(panel, DASHBOARD.FULLSCREEN_PLOT_RECT))
        self.assertTrue(contains(panel, DASHBOARD.FULLSCREEN_LEGEND_RECT))
        self.assertEqual(DASHBOARD.FULLSCREEN_HEADER_RECT[1] + DASHBOARD.FULLSCREEN_HEADER_RECT[3], DASHBOARD.FULLSCREEN_PLOT_RECT[1])
        self.assertEqual(DASHBOARD.FULLSCREEN_PLOT_RECT[1] + DASHBOARD.FULLSCREEN_PLOT_RECT[3], DASHBOARD.FULLSCREEN_LEGEND_RECT[1])
        self.assertEqual(DASHBOARD.FULLSCREEN_LEGEND_RECT[1] + DASHBOARD.FULLSCREEN_LEGEND_RECT[3], panel[1] + panel[3])

        header_x, header_y, header_width, header_height = DASHBOARD.FULLSCREEN_HEADER_RECT
        button_x, button_y, button_width, button_height = DASHBOARD.BACK_BUTTON_RECT
        self.assertEqual(button_x + button_width, panel[0] + panel[2] - 16)
        self.assertEqual(button_y - header_y, 8)
        self.assertEqual(header_y + header_height - (button_y + button_height), 8)
        self.assertEqual(button_height, 80)
        self.assertGreaterEqual(button_x, header_x)
        self.assertLessEqual(button_x + button_width, header_x + header_width)

    def test_plot_data_excludes_top_and_bottom_guard_rows(self) -> None:
        for rect in (*DASHBOARD.CARD_PLOT_RECTS.values(), DASHBOARD.FULLSCREEN_PLOT_RECT):
            inner = DASHBOARD.plot_inner_rect(rect)
            data = DASHBOARD.plot_data_rect(rect)
            top = DASHBOARD.plot_top_guard_rect(rect)
            bottom = DASHBOARD.plot_bottom_guard_rect(rect)
            self.assertTrue(contains(inner, data))
            self.assertTrue(contains(inner, top))
            self.assertTrue(contains(inner, bottom))
            self.assertEqual(data[1], top[1] + top[3])
            self.assertEqual(data[1] + data[3], bottom[1])

    def test_incremental_plot_clears_both_guard_rows(self) -> None:
        class FakeDisplay:
            def __init__(self) -> None:
                self.fill_calls: list[tuple[int, int, int, int, int]] = []

            def scroll_rect(self, *args: object) -> None:
                pass

            def fill_rect(self, x: int, y: int, width: int, height: int, color: int) -> None:
                self.fill_calls.append((x, y, width, height, color))

            def line(self, *args: object) -> None:
                pass

            def polyline(self, *args: object) -> None:
                pass

        model = sample_model()
        model.history["metric"] = deque([10.0, 90.0])
        spec = DASHBOARD.SeriesSpec("metric", "Metric", 1, 0.0, 100.0, lambda value: str(value))
        display = FakeDisplay()
        rect = DASHBOARD.FULLSCREEN_PLOT_RECT
        DASHBOARD.draw_plot_incremental(display, rect, (spec,), model, 1)
        self.assertIn((*DASHBOARD.plot_top_guard_rect(rect), DASHBOARD.SURFACE), display.fill_calls)
        self.assertIn((*DASHBOARD.plot_bottom_guard_rect(rect), DASHBOARD.SURFACE), display.fill_calls)

    def test_fixed_fullscreen_legend_columns_hold_tx_position(self) -> None:
        class FakeDisplay:
            def __init__(self) -> None:
                self.text_calls: list[tuple[str, int, int, int]] = []

            def fill_rect(self, *args: object) -> None:
                pass

            def draw_device_text(self, text: str, x: int, y: int, color: int) -> None:
                self.text_calls.append((text, x, y, color))

        model = sample_model()
        series = (
            DASHBOARD.SeriesSpec("net_rx", "RX", 1, 0.0, 1.0, lambda value: "999.9kbps"),
            DASHBOARD.SeriesSpec("net_tx", "TX", 2, 0.0, 1.0, lambda value: "0.1bps"),
        )
        display = FakeDisplay()
        DASHBOARD.draw_fullscreen_legend(display, model, series)
        self.assertEqual([call[1] for call in display.text_calls], [24, 152])

    def test_lines_only_renderer_has_no_graph_style_configuration_or_residual_renderers(self) -> None:
        source = EXAMPLE.read_text(encoding="utf-8")
        self.assertNotIn("graph_type", source)
        self.assertNotIn("smoothed", source)
        self.assertNotIn("draw_plot_ring", source)
        self.assertNotIn("ring_geometry", source)
        self.assertNotIn("draw_ring", source)
        self.assertNotIn("choose_graph", source)
        self.assertEqual(tuple(inspect.signature(DASHBOARD.MonitorConfig).parameters), ("network_iface", "disk", "refresh_hz", "history_seconds"))
        self.assertEqual(tuple(inspect.signature(DASHBOARD.draw_plot_full).parameters), ("display", "rect", "series", "model"))
        self.assertEqual(tuple(inspect.signature(DASHBOARD.draw_plot_incremental).parameters), ("display", "rect", "series", "model", "scroll"))

    def test_history_range_scales_with_selected_fps(self) -> None:
        disk = DASHBOARD.DiskTarget("disk", "/dev/disk", "", 0, "/")
        config = DASHBOARD.MonitorConfig(None, disk, 15.0, 60.0)
        self.assertEqual(config.history_sample_count(), 901)
        ten_second_config = DASHBOARD.MonitorConfig(None, disk, 15.0, 10.0)
        self.assertGreater(DASHBOARD.history_scroll_pixels(0, 1, DASHBOARD.CARD_PLOT_RECTS["cpu"], ten_second_config), 0)


if __name__ == "__main__":
    unittest.main()
