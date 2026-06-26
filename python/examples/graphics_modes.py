"""Exercise RAW, RLE, and Palette4 graphics using generated artwork."""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from rp2350_remote_display import RemoteDisplay, rgb565


BLACK = rgb565(0, 0, 0)
WHITE = rgb565(255, 255, 255)


def artwork() -> Image.Image:
    image = Image.new("RGB", (450, 600), (6, 10, 20))
    draw = ImageDraw.Draw(image)
    for y in range(600):
        for x in range(450):
            red = 18 + (x * 80) // 449
            green = 22 + (y * 110) // 599
            blue = 55 + ((x + y) * 140) // 1048
            image.putpixel((x, y), (red, green, blue))
    for radius in range(170, 20, -22):
        shade = 255 - radius
        draw.ellipse((225 - radius, 300 - radius, 225 + radius, 300 + radius), outline=(shade, 255 - shade // 2, 240), width=4)
    draw.rounded_rectangle((64, 80, 386, 160), radius=18, fill=(12, 20, 38), outline=(155, 210, 255), width=3)
    return image


def present(display: RemoteDisplay, image: Image.Image, title: str, *, compression: str, dither: str = "none") -> None:
    with display.frame(timeout_ms=5000):
        display.draw_image(image, 0, 0, compression=compression, dither=dither)
        display.fill_rect(24, 24, 402, 42, BLACK)
        display.draw_text(title, 38, 38, WHITE, size=16)


image = artwork()
with RemoteDisplay.open(timeout_ms=2000) as display:
    present(display, image, "RGB565 RAW", compression="raw")
    time.sleep(2)
    present(display, image, "RGB565 RLE", compression="rle")
    time.sleep(2)
    present(display, image, "Palette4, 16 colors", compression="palette4", dither="none")
    time.sleep(2)
    present(display, image, "Palette4, Floyd-Steinberg dither", compression="palette4", dither="floyd-steinberg")

print("Graphics-mode sequence completed.")
