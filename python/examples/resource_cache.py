"""Cache and repeatedly draw a small RGB565 icon resource."""

from __future__ import annotations

from rp2350_remote_display import RemoteDisplay, rgb565

BLACK = rgb565(5, 7, 13)
WHITE = rgb565(243, 247, 255)
CYAN = rgb565(84, 217, 255)


def icon() -> bytes:
    width = height = 30
    pixels = bytearray(width * height * 2)
    for y in range(height):
        for x in range(width):
            inside = (x - 15) ** 2 + (y - 15) ** 2 < 12 ** 2
            color = CYAN if inside else BLACK
            offset = (y * width + x) * 2
            pixels[offset] = color & 0xFF
            pixels[offset + 1] = color >> 8
    return bytes(pixels)


with RemoteDisplay.open(timeout_ms=2000) as display:
    display.clear_cached()
    stats = display.cache_rgb565(1, 30, 30, icon(), compression="rle")
    print(f"Uploaded cached icon: {stats.encoded_bytes} encoded bytes")
    with display.frame():
        display.clear(BLACK)
        display.draw_text("Cached resource replay", 32, 32, WHITE, size=18)
        for y in range(4):
            for x in range(8):
                display.draw_cached(1, 48 + x * 44, 96 + y * 44)
    print(display.resource_cache_info())
    display.release_cached(1)
