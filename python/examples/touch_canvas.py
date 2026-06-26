"""Render current touch feedback without overwriting the underlying UI."""

from __future__ import annotations

import time

from rp2350_remote_display import Canvas, DirtyTilePresenter, RemoteDisplay, rgb565

BLACK = rgb565(5, 7, 13)
PANEL = rgb565(20, 29, 48)
BORDER = rgb565(65, 89, 128)
WHITE = rgb565(243, 247, 255)
MUTED = rgb565(150, 168, 194)
MARKER = rgb565(255, 194, 66)


def make_base() -> Canvas:
    canvas = Canvas(background=BLACK)
    canvas.fill_rect(18, 18, 414, 564, PANEL)
    canvas.stroke_rect(18, 18, 414, 564, BORDER, 2)
    canvas.text("Touch monitor", 36, 40, WHITE, size=18)
    canvas.text("The marker is composed over a fresh host canvas each update.", 36, 68, MUTED, size=12)
    canvas.fill_rect(36, 118, 378, 390, rgb565(8, 12, 22))
    canvas.stroke_rect(36, 118, 378, 390, BORDER, 1)
    canvas.text("Drag a finger inside the panel", 36, 530, MUTED, size=12)
    return canvas


base = make_base()
with RemoteDisplay.open(timeout_ms=2000) as display:
    presenter = DirtyTilePresenter(display, tile_profile="small", compression="auto")
    presenter.present(base.rgb565_bytes())
    latest = None
    next_present = 0.0
    deadline = time.monotonic() + 20.0

    while time.monotonic() < deadline:
        event = display.poll_latest_touch(timeout_ms=2)
        if event is not None:
            latest = event
        now = time.monotonic()
        if latest is None or now < next_present:
            continue
        next_present = now + 1 / 60
        canvas = base.copy()
        if latest.pressed:
            x = max(44, min(405, latest.x))
            y = max(126, min(499, latest.y))
            canvas.stroke_rect(x - 10, y - 10, 21, 21, MARKER, 2)
            canvas.line(x - 15, y, x + 15, y, MARKER, 1)
            canvas.line(x, y - 15, x, y + 15, MARKER, 1)
            canvas.text(f"X {latest.x:03d}  Y {latest.y:03d}", 36, 92, WHITE, size=14)
        else:
            canvas.text("Touch released", 36, 92, WHITE, size=14)
        presenter.present(canvas.rgb565_bytes())

print("Touch monitor completed.")
