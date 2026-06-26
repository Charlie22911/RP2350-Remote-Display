#!/usr/bin/env python3
"""Draw compact dashboard text with the firmware-resident bitmap font."""

from rp2350_remote_display import RemoteDisplay, rgb565

INK = rgb565(5, 9, 18)
PANEL = rgb565(17, 29, 50)
WHITE = rgb565(244, 248, 255)
CYAN = rgb565(45, 219, 255)
GREEN = rgb565(68, 232, 158)
MUTED = rgb565(161, 185, 219)


with RemoteDisplay.open() as display:
    font = display.device_font_info()
    title = display.measure_device_text("SYSTEM STATUS", scale=2)
    print(
        f"font={font.font_id} cell={font.cell_width}x{font.cell_height} "
        f"glyphs={font.glyph_count} title={title.width}x{title.height}"
    )

    with display.frame():
        display.clear(INK)
        display.fill_rect(18, 18, 414, 220, PANEL)
        display.stroke_rect(18, 18, 414, 220, CYAN, 2)
        display.draw_device_text("SYSTEM STATUS", 34, 38, WHITE, scale=2)
        display.draw_device_text("CPU 42%  │  TEMP 26°C  │  ✓ USB ONLINE", 34, 86, GREEN)
        display.draw_device_text("Glyphs are rendered on the Pico from flash.", 34, 118, MUTED)
        display.draw_device_text("┌──────────────┬──────────────┐", 34, 150, CYAN)
        display.draw_device_text("│ RX  1.2 MB/s │ TX  0.4 MB/s │", 34, 166, WHITE)
        display.draw_device_text("└──────────────┴──────────────┘", 34, 182, CYAN)
