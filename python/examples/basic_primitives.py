"""Draw a compact panel using direct primitive and Alpha8 text commands."""

from rp2350_remote_display import RemoteDisplay, rgb565

BLACK = rgb565(4, 6, 12)
PANEL = rgb565(22, 34, 58)
BORDER = rgb565(86, 128, 188)
ACCENT = rgb565(90, 215, 174)
WHITE = rgb565(245, 248, 255)
MUTED = rgb565(170, 184, 207)


with RemoteDisplay.open() as display:
    display.set_brightness(65)
    with display.frame():
        display.clear(BLACK)
        display.fill_rect(18, 18, 414, 158, PANEL)
        display.stroke_rect(18, 18, 414, 158, BORDER, thickness=2)
        display.fill_rect(36, 108, 250, 12, ACCENT)
        display.draw_text("RP2350 Remote Display", 36, 42, WHITE, size=18)
        display.draw_text("Direct primitives and Alpha8 text", 36, 72, MUTED, size=14)
        display.button(36, 132, 156, 30, "CONNECTED", background=ACCENT, border=WHITE, text_color=BLACK, font_size=14)

print("Frame presented.")
