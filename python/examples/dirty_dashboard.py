"""Present a host-composed dashboard using changed small tiles only."""

from __future__ import annotations

import math
import time

from rp2350_remote_display import Canvas, DirtyTilePresenter, RemoteDisplay, rgb565

BLACK = rgb565(5, 7, 13)
PANEL = rgb565(20, 29, 48)
BORDER = rgb565(65, 89, 128)
WHITE = rgb565(243, 247, 255)
MUTED = rgb565(150, 168, 194)
CYAN = rgb565(84, 217, 255)
GREEN = rgb565(84, 216, 156)
ORANGE = rgb565(255, 170, 76)


def static_canvas() -> Canvas:
    canvas = Canvas(background=BLACK)
    canvas.fill_rect(18, 18, 414, 64, PANEL)
    canvas.stroke_rect(18, 18, 414, 64, BORDER, 2)
    canvas.text("Host-composed dashboard", 34, 38, WHITE, size=18)
    canvas.text("Dirty small tiles", 34, 60, MUTED, size=12)
    for x in (18, 226):
        canvas.fill_rect(x, 98, 206, 220, PANEL)
        canvas.stroke_rect(x, 98, 206, 220, BORDER, 2)
    canvas.fill_rect(18, 336, 414, 246, PANEL)
    canvas.stroke_rect(18, 336, 414, 246, BORDER, 2)
    return canvas


base = static_canvas()
with RemoteDisplay.open(timeout_ms=2000) as display:
    display.set_brightness(65)
    presenter = DirtyTilePresenter(display, tile_profile="small", compression="auto")

    for frame in range(180):
        canvas = base.copy()
        phase = frame / 18.0
        cpu = 48 + 36 * math.sin(phase)
        memory = 62 + 19 * math.sin(phase * 0.63 + 1.1)
        values = [50 + 28 * math.sin((frame - index) / 11.0) for index in range(32)]
        bars = [12 + 50 * abs(math.sin((frame + index) / 14.0)) for index in range(8)]

        canvas.text(f"CPU {cpu:04.1f}%", 34, 116, WHITE, size=16)
        canvas.fill_rect(34, 152, 164, 14, rgb565(10, 16, 28))
        canvas.fill_rect(34, 152, round(164 * cpu / 100), 14, CYAN)
        canvas.text(f"MEM {memory:04.1f}%", 242, 116, WHITE, size=16)
        canvas.fill_rect(242, 152, 164, 14, rgb565(10, 16, 28))
        canvas.fill_rect(242, 152, round(164 * memory / 100), 14, GREEN)
        canvas.line_chart(34, 194, 164, 104, values, line_color=CYAN, grid_color=BORDER, background=PANEL, min_value=0, max_value=100)
        canvas.bar_chart(242, 194, 164, 104, bars, bar_color=ORANGE, grid_color=BORDER, background=PANEL)
        canvas.text("Activity", 34, 354, WHITE, size=16)
        canvas.line_chart(34, 384, 372, 170, values + values[-8:], line_color=GREEN, grid_color=BORDER, background=PANEL, min_value=0, max_value=100)

        stats = presenter.present(canvas.rgb565_bytes())
        if frame % 30 == 0:
            print(f"frame={frame:03d} changed={stats.changed_tiles:02d} wire={stats.transfer.wire_bytes / 1024:.1f} KiB")
        time.sleep(1 / 30)

print("Dashboard completed.")
