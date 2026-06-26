"""Host-side RGB565 canvas helpers.

``Canvas`` is optional.  It is useful when an application wants to compose a
complete scene on the PC and send only changed tiles with
:class:`~rp2350_remote_display.DirtyTilePresenter`.

The device protocol remains immediate-mode.  This class does not add firmware
commands or change the wire format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from .protocol import SCREEN_HEIGHT, SCREEN_WIDTH, rgb565


def rgb565_to_rgb888(color: int) -> tuple[int, int, int]:
    """Convert a packed RGB565 colour to an RGB888 tuple."""
    if not 0 <= color <= 0xFFFF:
        raise ValueError("RGB565 colors must be in the range 0x0000..0xffff")
    return (
        ((color >> 11) & 0x1F) * 255 // 31,
        ((color >> 5) & 0x3F) * 255 // 63,
        (color & 0x1F) * 255 // 31,
    )


def _rgb888(color: int | tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(color, int):
        return rgb565_to_rgb888(color)
    if len(color) != 3 or any(not 0 <= component <= 255 for component in color):
        raise ValueError("RGB colors must be RGB565 integers or RGB888 tuples")
    return color


class Canvas:
    """A Pillow-backed RGB canvas with helpers matching the display API.

    The default size matches the remote panel.  All rectangle methods use the
    same half-open geometry as the protocol: ``x, y, width, height``.  The
    right and bottom edges are exclusive.
    """

    def __init__(
        self,
        width: int = SCREEN_WIDTH,
        height: int = SCREEN_HEIGHT,
        background: int | tuple[int, int, int] = 0x0000,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("canvas dimensions must be positive")
        from PIL import Image

        self._image = Image.new("RGB", (width, height), _rgb888(background))

    @classmethod
    def from_image(
        cls,
        image,
        *,
        width: int = SCREEN_WIDTH,
        height: int = SCREEN_HEIGHT,
        background: int | tuple[int, int, int] = 0x0000,
    ) -> "Canvas":
        """Create a canvas from a Pillow image or image path.

        Images smaller than the canvas remain at the top-left.  Images larger
        than the canvas are rejected instead of being silently cropped.
        """
        from PIL import Image

        if isinstance(image, (str, Path)):
            image = Image.open(image)
        if image.width > width or image.height > height:
            raise ValueError("source image does not fit within the canvas")
        canvas = cls(width, height, background)
        canvas.paste_image(image, 0, 0)
        return canvas

    @property
    def width(self) -> int:
        return self._image.width

    @property
    def height(self) -> int:
        return self._image.height

    @property
    def image(self):
        """Return the underlying Pillow RGB image.

        Mutating it directly is supported.  Call :meth:`rgb565_bytes` after
        making changes when presenting the result.
        """
        return self._image

    def copy(self) -> "Canvas":
        clone = object.__new__(Canvas)
        clone._image = self._image.copy()
        return clone

    def clear(self, color: int | tuple[int, int, int] = 0x0000) -> None:
        self.fill_rect(0, 0, self.width, self.height, color)

    def fill_rect(self, x: int, y: int, width: int, height: int, color: int | tuple[int, int, int]) -> None:
        self._validate_rect(x, y, width, height)
        if width == 0 or height == 0:
            return
        from PIL import ImageDraw

        ImageDraw.Draw(self._image).rectangle(
            (x, y, x + width - 1, y + height - 1),
            fill=_rgb888(color),
        )

    def stroke_rect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: int | tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        self._validate_rect(x, y, width, height)
        if thickness <= 0:
            raise ValueError("stroke thickness must be positive")
        if width == 0 or height == 0:
            return
        thickness = min(thickness, max(1, min(width, height)))
        self.fill_rect(x, y, width, min(thickness, height), color)
        self.fill_rect(x, y + max(0, height - thickness), width, min(thickness, height), color)
        inner_height = height - 2 * thickness
        if inner_height > 0:
            self.fill_rect(x, y + thickness, min(thickness, width), inner_height, color)
            self.fill_rect(x + max(0, width - thickness), y + thickness, min(thickness, width), inner_height, color)

    def line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: int | tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        self._validate_point(x0, y0)
        self._validate_point(x1, y1)
        if thickness <= 0:
            raise ValueError("line thickness must be positive")
        from PIL import ImageDraw

        ImageDraw.Draw(self._image).line((x0, y0, x1, y1), fill=_rgb888(color), width=thickness)

    def polyline(
        self,
        points: Sequence[tuple[int, int]],
        color: int | tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        if len(points) < 2:
            raise ValueError("polyline needs at least two points")
        for x, y in points:
            self._validate_point(x, y)
        if thickness <= 0:
            raise ValueError("line thickness must be positive")
        from PIL import ImageDraw

        ImageDraw.Draw(self._image).line(points, fill=_rgb888(color), width=thickness, joint="curve")

    @classmethod
    def measure_text(cls, text: str, *, font=None, size: int = 18) -> tuple[int, int, int, int, int, int]:
        """Return mask and visible-ink bounds for host-composed text.

        The tuple is ``(mask_width, mask_height, ink_x, ink_y, ink_width,
        ink_height)``.
        """
        from PIL import Image, ImageDraw

        if not text:
            raise ValueError("text must not be empty")
        font_object = cls._font(font, size)
        bounds = font_object.getbbox(text)
        mask_width = max(1, bounds[2] - bounds[0])
        mask_height = max(1, bounds[3] - bounds[1])
        mask = Image.new("L", (mask_width, mask_height), 0)
        ImageDraw.Draw(mask).text((-bounds[0], -bounds[1]), text, fill=255, font=font_object)
        ink = mask.getbbox()
        if ink is None:
            raise ValueError("text produced an empty alpha mask")
        ink_x, ink_y, ink_right, ink_bottom = ink
        return mask_width, mask_height, ink_x, ink_y, ink_right - ink_x, ink_bottom - ink_y

    def text(
        self,
        text: str,
        x: int,
        y: int,
        color: int | tuple[int, int, int],
        *,
        font=None,
        size: int = 18,
        require_fit: bool = True,
    ) -> tuple[int, int]:
        """Draw text with a top-left bounding-box origin and return its size."""
        from PIL import ImageDraw, ImageFont

        font_object = self._font(font, size)
        bounds = font_object.getbbox(text)
        width, height, _, _, _, _ = self.measure_text(text, font=font_object, size=size)
        if require_fit:
            self._validate_rect(x, y, width, height)
        elif x < 0 or y < 0 or x >= self.width or y >= self.height:
            raise ValueError("text origin must be inside the canvas")
        ImageDraw.Draw(self._image).text((x - bounds[0], y - bounds[1]), text, fill=_rgb888(color), font=font_object)
        return width, height

    def text_box(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str,
        color: int | tuple[int, int, int],
        *,
        font=None,
        size: int = 18,
        align: str = "left",
        valign: str = "top",
    ) -> tuple[int, int, int, int]:
        """Draw text in a box with visible glyph ink aligned to the box."""
        self._validate_rect(x, y, width, height)
        mask_width, mask_height, ink_x, ink_y, ink_width, ink_height = self.measure_text(text, font=font, size=size)
        if ink_width > width or ink_height > height:
            raise ValueError("visible text does not fit within the text box")
        if align == "left":
            visible_x = x
        elif align == "center":
            visible_x = x + (width - ink_width) // 2
        elif align == "right":
            visible_x = x + width - ink_width
        else:
            raise ValueError("align must be left, center, or right")
        if valign == "top":
            visible_y = y
        elif valign == "middle":
            visible_y = y + (height - ink_height) // 2
        elif valign == "bottom":
            visible_y = y + height - ink_height
        else:
            raise ValueError("valign must be top, middle, or bottom")
        mask_x = visible_x - ink_x
        mask_y = visible_y - ink_y
        self._validate_rect(mask_x, mask_y, mask_width, mask_height)
        self.text(text, mask_x, mask_y, color, font=font, size=size)
        return visible_x, visible_y, ink_width, ink_height

    def copy_rect(
        self,
        source_x: int,
        source_y: int,
        width: int,
        height: int,
        destination_x: int,
        destination_y: int,
    ) -> None:
        """Mirror the device COPY_RECT command using overlap-safe source pixels."""
        self._validate_rect(source_x, source_y, width, height)
        self._validate_rect(destination_x, destination_y, width, height)
        copied = self._image.crop((source_x, source_y, source_x + width, source_y + height))
        self._image.paste(copied, (destination_x, destination_y))

    def scroll_rect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        delta_x: int,
        delta_y: int,
        fill: int | tuple[int, int, int] = 0x0000,
    ) -> None:
        """Mirror the lossless device SCROLL_RECT command.

        Positive deltas move existing pixels right and down. Pixels exposed by
        the move are filled with ``fill``. Deltas that move the complete region
        outside itself fill the whole region.
        """
        self._validate_rect(x, y, width, height)
        if not isinstance(delta_x, int) or not isinstance(delta_y, int):
            raise TypeError("scroll deltas must be integers")
        if delta_x == 0 and delta_y == 0:
            return
        source = self._image.crop((x, y, x + width, y + height))
        self.fill_rect(x, y, width, height, fill)
        destination_left = max(0, delta_x)
        destination_top = max(0, delta_y)
        source_left = max(0, -delta_x)
        source_top = max(0, -delta_y)
        copied_width = width - abs(delta_x)
        copied_height = height - abs(delta_y)
        if copied_width <= 0 or copied_height <= 0:
            return
        moved = source.crop((source_left, source_top, source_left + copied_width, source_top + copied_height))
        self._image.paste(moved, (x + destination_left, y + destination_top))

    def paste_image(
        self,
        image,
        x: int,
        y: int,
        *,
        background: int | tuple[int, int, int] = 0x0000,
    ) -> None:
        """Composite a Pillow image or image file at ``x, y``."""
        from PIL import Image

        if isinstance(image, (str, Path)):
            image = Image.open(image)
        if image.mode == "RGBA":
            base = Image.new("RGBA", image.size, (*_rgb888(background), 255))
            image = Image.alpha_composite(base, image).convert("RGB")
        else:
            image = image.convert("RGB")
        self._validate_rect(x, y, image.width, image.height)
        self._image.paste(image, (x, y))

    def button(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str,
        *,
        background: int | tuple[int, int, int],
        border: int | tuple[int, int, int],
        text_color: int | tuple[int, int, int],
        font=None,
        font_size: int = 18,
    ) -> None:
        self._validate_rect(x, y, width, height)
        self.fill_rect(x, y, width, height, background)
        self.stroke_rect(x, y, width, height, border, 2)
        self.text_box(x + 6, y + 4, max(1, width - 12), max(1, height - 8), text, text_color, font=font, size=font_size, align="center", valign="middle")

    def checkbox(
        self,
        x: int,
        y: int,
        checked: bool,
        label: str,
        *,
        foreground: int | tuple[int, int, int],
        background: int | tuple[int, int, int],
        font=None,
        font_size: int = 17,
    ) -> None:
        self._validate_rect(x, y, 24, 24)
        self.fill_rect(x, y, 24, 24, background)
        self.stroke_rect(x, y, 24, 24, foreground, 2)
        if checked:
            self.line(x + 5, y + 12, x + 10, y + 18, foreground, 3)
            self.line(x + 10, y + 18, x + 20, y + 5, foreground, 3)
        self.text_box(x + 33, y, self.width - (x + 33), 24, label, foreground, font=font, size=font_size, align="left", valign="middle")

    def line_chart(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        values: Sequence[float],
        *,
        line_color: int | tuple[int, int, int],
        grid_color: int | tuple[int, int, int],
        background: int | tuple[int, int, int],
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> None:
        import math

        self._validate_rect(x, y, width, height)
        if width < 3 or height < 3:
            raise ValueError("line chart needs an area at least 3x3 pixels")
        self.fill_rect(x, y, width, height, background)
        self.stroke_rect(x, y, width, height, grid_color, 1)
        for division in range(1, 4):
            grid_y = y + (height * division) // 4
            self.line(x + 1, grid_y, x + width - 2, grid_y, grid_color, 1)
        if len(values) < 2:
            return
        lower = min(values) if min_value is None else min_value
        upper = max(values) if max_value is None else max_value
        if math.isclose(lower, upper):
            lower -= 0.5
            upper += 0.5
        points = []
        for index, value in enumerate(values):
            px = x + 1 + ((width - 3) * index) // (len(values) - 1)
            normalized = (value - lower) / (upper - lower)
            py = y + height - 2 - round(normalized * (height - 3))
            points.append((px, max(y + 1, min(y + height - 2, py))))
        self.polyline(points, line_color, 2)

    def bar_chart(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        values: Sequence[float],
        *,
        bar_color: int | tuple[int, int, int],
        grid_color: int | tuple[int, int, int],
        background: int | tuple[int, int, int],
    ) -> None:
        self._validate_rect(x, y, width, height)
        if width < 3 or height < 3:
            raise ValueError("bar chart needs an area at least 3x3 pixels")
        self.fill_rect(x, y, width, height, background)
        self.stroke_rect(x, y, width, height, grid_color, 1)
        if not values:
            return
        maximum = max(max(values), 1e-9)
        gap = max(2, width // (len(values) * 8))
        bar_width = max(1, (width - gap * (len(values) + 1)) // len(values))
        for index, value in enumerate(values):
            bar_height = max(0, min(height - 2, round((value / maximum) * (height - 2))))
            bar_x = x + gap + index * (bar_width + gap)
            if bar_x >= x + width - 1:
                break
            bar_width_here = min(bar_width, x + width - 1 - bar_x)
            self.fill_rect(bar_x, y + height - 1 - bar_height, bar_width_here, bar_height, bar_color)

    def pie_chart(
        self,
        x: int,
        y: int,
        diameter: int,
        values: Sequence[float],
        colors: Sequence[int | tuple[int, int, int]],
        *,
        background: int | tuple[int, int, int] = 0x0000,
    ) -> None:
        if diameter <= 0 or len(values) != len(colors) or not values:
            raise ValueError("pie chart needs positive diameter and matching non-empty values/colors")
        self._validate_rect(x, y, diameter, diameter)
        total = sum(max(value, 0) for value in values)
        if total <= 0:
            raise ValueError("pie chart values must contain a positive value")
        from PIL import ImageDraw

        draw = ImageDraw.Draw(self._image)
        draw.ellipse((x, y, x + diameter - 1, y + diameter - 1), fill=_rgb888(background))
        start = -90.0
        for value, color in zip(values, colors):
            angle = 360.0 * max(value, 0) / total
            draw.pieslice(
                (x, y, x + diameter - 1, y + diameter - 1),
                start,
                start + angle,
                fill=_rgb888(color),
            )
            start += angle

    def rgb565_bytes(self) -> bytes:
        """Return the canvas in protocol-native little-endian RGB565 order."""
        output = bytearray(self.width * self.height * 2)
        pixels: Iterable[tuple[int, int, int]]
        pixels = self._image.get_flattened_data() if hasattr(self._image, "get_flattened_data") else self._image.getdata()
        for index, (red, green, blue) in enumerate(pixels):
            value = rgb565(red, green, blue)
            output[index * 2] = value & 0xFF
            output[index * 2 + 1] = value >> 8
        return bytes(output)

    def text_metrics(self, text: str, *, font=None, size: int = 18) -> tuple[int, int]:
        mask_width, mask_height, _, _, _, _ = self.measure_text(text, font=font, size=size)
        return mask_width, mask_height

    @staticmethod
    def _font(font, size: int):
        from PIL import ImageFont

        if size <= 0:
            raise ValueError("font size must be positive")
        if font is None:
            return ImageFont.load_default()
        if isinstance(font, (str, Path)):
            return ImageFont.truetype(str(font), size=size)
        return font

    def _validate_point(self, x: int, y: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f"point {x},{y} is outside the {self.width}x{self.height} canvas")

    def _validate_rect(self, x: int, y: int, width: int, height: int) -> None:
        if width < 0 or height < 0:
            raise ValueError("rectangle width and height must be non-negative")
        if x < 0 or y < 0 or x + width > self.width or y + height > self.height:
            raise ValueError(f"rectangle {x},{y} {width}x{height} exceeds the {self.width}x{self.height} canvas")


__all__ = ["Canvas", "rgb565_to_rgb888"]
