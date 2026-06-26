#!/usr/bin/env python3
"""Scroll firmware-rendered log lines without retransmitting the panel contents."""

from __future__ import annotations

import time

from rp2350_remote_display import RemoteDisplay, rgb565

INK = rgb565(5, 9, 18)
PANEL = rgb565(17, 29, 50)
GRID = rgb565(58, 92, 143)
WHITE = rgb565(244, 248, 255)
CYAN = rgb565(45, 219, 255)
MUTED = rgb565(161, 185, 219)

PANE_X = 34
PANE_Y = 126
PANE_WIDTH = 382
PANE_HEIGHT = 384
LINE_HEIGHT = 16


def main() -> None:
    with RemoteDisplay.open(timeout_ms=1800) as display:
        display.device_font_info()
        with display.frame(timeout_ms=4000):
            display.clear(INK)
            display.fill_rect(18, 18, 414, 564, PANEL)
            display.stroke_rect(18, 18, 414, 564, CYAN, 2)
            display.draw_device_text("SCROLL_RECT LOG DEMO", 34, 48, WHITE, scale=2)
            display.draw_device_text("Existing RGB565 pixels move inside the Pico.", 34, 88, MUTED)
            display.fill_rect(PANE_X, PANE_Y, PANE_WIDTH, PANE_HEIGHT, INK)
            display.stroke_rect(PANE_X, PANE_Y, PANE_WIDTH, PANE_HEIGHT, GRID, 1)
            for row in range(PANE_HEIGHT // LINE_HEIGHT):
                display.draw_device_text(f"{row:04d}  INITIAL LOG LINE", PANE_X + 12, PANE_Y + 8 + row * LINE_HEIGHT, CYAN)

        for index in range(80):
            line_y = PANE_Y + PANE_HEIGHT - LINE_HEIGHT
            with display.frame(timeout_ms=1800):
                display.scroll_rect(PANE_X + 1, PANE_Y + 1, PANE_WIDTH - 2, PANE_HEIGHT - 2, 0, -LINE_HEIGHT, INK)
                display.draw_device_text(f"{index + 24:04d}  USB DISPLAY EVENT {index:03d}", PANE_X + 12, line_y - 8, WHITE)
            time.sleep(0.12)


if __name__ == "__main__":
    main()
