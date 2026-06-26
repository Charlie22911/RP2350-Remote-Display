"""Host-side layout, coordinate conversion, and visual diagnostics.

The remote-display protocol uses physical 450x600 pixels.  This module adds a
small optional host-side layout layer without changing firmware behavior or the
wire protocol.  Every layout operation resolves to explicit pixel coordinates
before it reaches the display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

from .display import RemoteDisplay
from .protocol import SCREEN_HEIGHT, SCREEN_WIDTH

HorizontalAlign = Literal["left", "center", "right"]
VerticalAlign = Literal["top", "middle", "bottom"]


@dataclass(frozen=True)
class Rect:
    """Half-open rectangle: [x, x + width) × [y, y + height)."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("rectangle width and height must be non-negative")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    def inset(self, amount: int | tuple[int, int, int, int]) -> "Rect":
        if isinstance(amount, int):
            left = top = right = bottom = amount
        else:
            left, top, right, bottom = amount
        return Rect(
            self.x + left,
            self.y + top,
            max(0, self.width - left - right),
            max(0, self.height - top - bottom),
        )

    def translated(self, dx: int = 0, dy: int = 0) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def split_columns(self, count: int, gap: int = 0) -> tuple["Rect", ...]:
        if count <= 0:
            raise ValueError("column count must be positive")
        available = self.width - gap * (count - 1)
        if available < 0:
            raise ValueError("gaps exceed rectangle width")
        base, remainder = divmod(available, count)
        output: list[Rect] = []
        cursor = self.x
        for index in range(count):
            width = base + (1 if index < remainder else 0)
            output.append(Rect(cursor, self.y, width, self.height))
            cursor += width + gap
        return tuple(output)

    def split_rows(self, count: int, gap: int = 0) -> tuple["Rect", ...]:
        if count <= 0:
            raise ValueError("row count must be positive")
        available = self.height - gap * (count - 1)
        if available < 0:
            raise ValueError("gaps exceed rectangle height")
        base, remainder = divmod(available, count)
        output: list[Rect] = []
        cursor = self.y
        for index in range(count):
            height = base + (1 if index < remainder else 0)
            output.append(Rect(self.x, cursor, self.width, height))
            cursor += height + gap
        return tuple(output)


@dataclass(frozen=True)
class CoordinateSpace:
    """Maps a logical design space onto a physical display canvas."""

    physical_width: int = SCREEN_WIDTH
    physical_height: int = SCREEN_HEIGHT
    logical_width: int = SCREEN_WIDTH
    logical_height: int = SCREEN_HEIGHT

    def __post_init__(self) -> None:
        if min(self.physical_width, self.physical_height, self.logical_width, self.logical_height) <= 0:
            raise ValueError("coordinate-space dimensions must be positive")

    @classmethod
    def pixels(cls, width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT) -> "CoordinateSpace":
        return cls(width, height, width, height)

    @classmethod
    def design(cls, logical_width: int, logical_height: int, *, physical_width: int = SCREEN_WIDTH, physical_height: int = SCREEN_HEIGHT) -> "CoordinateSpace":
        return cls(physical_width, physical_height, logical_width, logical_height)

    def point(self, x: float, y: float) -> tuple[int, int]:
        """Map a logical pixel center to a physical pixel center.

        Point coordinates use the inclusive range 0..logical_dimension-1.
        Rectangle edges use the separate half-open mapping in :meth:`rect`.
        """
        if not (0 <= x <= self.logical_width - 1 and 0 <= y <= self.logical_height - 1):
            raise ValueError("logical point is outside the coordinate space")
        x_scale = (self.physical_width - 1) / max(1, self.logical_width - 1)
        y_scale = (self.physical_height - 1) / max(1, self.logical_height - 1)
        return round(x * x_scale), round(y * y_scale)

    def rect(self, x: float, y: float, width: float, height: float) -> Rect:
        """Map a half-open logical rectangle to a half-open physical rectangle."""
        if width < 0 or height < 0:
            raise ValueError("logical rectangle width and height must be non-negative")
        if x < 0 or y < 0 or x + width > self.logical_width or y + height > self.logical_height:
            raise ValueError("logical rectangle is outside the coordinate space")
        left = round(x * self.physical_width / self.logical_width)
        top = round(y * self.physical_height / self.logical_height)
        right = round((x + width) * self.physical_width / self.logical_width)
        bottom = round((y + height) * self.physical_height / self.logical_height)
        return Rect(left, top, max(0, right - left), max(0, bottom - top))


@dataclass(frozen=True)
class DebugOverlay:
    enabled: bool = False
    minor_grid: int = 25
    major_grid: int = 50
    show_labels: bool = True
    show_bounds: bool = True
    show_baselines: bool = True
    show_tile_profile: str | None = None
    minor_color: int = 0x1082
    major_color: int = 0x2945
    bounds_color: int = 0xF81F
    baseline_color: int = 0xFFE0
    tile_color: int = 0x07FF
    label_color: int = 0xFFFF


@dataclass
class _Bound:
    name: str
    rect: Rect
    color: int


class Layout:
    """Host-side layout facade that resolves logical coordinates to pixels."""

    def __init__(
        self,
        display: RemoteDisplay,
        *,
        space: CoordinateSpace | None = None,
        debug: DebugOverlay | None = None,
    ) -> None:
        self.display = display
        self.space = space or CoordinateSpace.pixels()
        if (self.space.physical_width, self.space.physical_height) != (SCREEN_WIDTH, SCREEN_HEIGHT):
            raise ValueError("the connected display canvas must remain 450x600 pixels")
        self.debug = debug or DebugOverlay()
        self._bounds: list[_Bound] = []

    @property
    def canvas(self) -> Rect:
        return Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)

    def rect(self, x: float, y: float, width: float, height: float) -> Rect:
        rect = self.space.rect(x, y, width, height)
        self._require_on_canvas(rect)
        return rect

    def pixels(self, x: int, y: int, width: int, height: int) -> Rect:
        rect = Rect(x, y, width, height)
        self._require_on_canvas(rect)
        return rect

    def region(self, name: str, rect: Rect, *, color: int | None = None) -> Rect:
        self._require_on_canvas(rect)
        if self.debug.enabled and self.debug.show_bounds:
            self._bounds.append(_Bound(name, rect, self.debug.bounds_color if color is None else color))
        return rect

    def fill(self, rect: Rect, color: int) -> None:
        self._require_on_canvas(rect)
        if rect.width and rect.height:
            self.display.fill_rect(rect.x, rect.y, rect.width, rect.height, color)

    def stroke(self, rect: Rect, color: int, thickness: int = 1) -> None:
        self._require_on_canvas(rect)
        if rect.width and rect.height:
            self.display.stroke_rect(rect.x, rect.y, rect.width, rect.height, color, thickness)

    def line(self, x0: float, y0: float, x1: float, y1: float, color: int, thickness: int = 1) -> None:
        px0, py0 = self.space.point(x0, y0)
        px1, py1 = self.space.point(x1, y1)
        self._require_point(px0, py0)
        self._require_point(px1, py1)
        self.display.line(px0, py0, px1, py1, color, thickness)

    def polyline(self, points: Sequence[tuple[float, float]], color: int, thickness: int = 1) -> None:
        pixels = [self.space.point(x, y) for x, y in points]
        for x, y in pixels:
            self._require_point(x, y)
        self.display.polyline(pixels, color, thickness)

    @staticmethod
    def text_metrics(text: str, font=None, font_size: int = 18) -> tuple[int, int]:
        """Return alpha-mask dimensions for compatibility with earlier releases."""
        metrics = RemoteDisplay.measure_text(text, font, font_size)
        return metrics.mask_width, metrics.mask_height

    def text_box(
        self,
        rect: Rect,
        text: str,
        color: int,
        *,
        font=None,
        font_size: int = 18,
        align: HorizontalAlign = "left",
        valign: VerticalAlign = "top",
        compression: str = "auto",
        label: str | None = None,
    ) -> Rect:
        """Draw visible text ink aligned inside ``rect``.

        High-level layout aligns the pixels that form the letters, accounting
        for font side bearings and transparent alpha-mask margins.
        """
        self._require_on_canvas(rect)
        metrics = RemoteDisplay.measure_text(text, font, font_size)
        if metrics.ink_width > rect.width or metrics.ink_height > rect.height:
            raise ValueError(
                f"visible text {text!r} ({metrics.ink_width}x{metrics.ink_height}) does not fit in "
                f"{rect.width}x{rect.height} layout box"
            )
        if align == "left":
            x = rect.x
        elif align == "center":
            x = rect.x + (rect.width - metrics.ink_width) // 2
        elif align == "right":
            x = rect.right - metrics.ink_width
        else:
            raise ValueError("align must be left, center, or right")
        if valign == "top":
            y = rect.y
        elif valign == "middle":
            y = rect.y + (rect.height - metrics.ink_height) // 2
        elif valign == "bottom":
            y = rect.bottom - metrics.ink_height
        else:
            raise ValueError("valign must be top, middle, or bottom")
        text_rect = Rect(x, y, metrics.ink_width, metrics.ink_height)
        self._require_on_canvas(text_rect)
        if hasattr(self.display, "draw_text_box"):
            self.display.draw_text_box(
                rect.x, rect.y, rect.width, rect.height, text, color,
                font=font, size=font_size, align=align, valign=valign, compression=compression,
            )
        else:
            # Lightweight display doubles used by callers and tests may expose
            # only the lower-level API. Preserve the same visual-ink origin.
            mask_x = text_rect.x - metrics.ink_x
            mask_y = text_rect.y - metrics.ink_y
            self.display.draw_text(text, mask_x, mask_y, color, font=font, size=font_size, compression=compression)
        if self.debug.enabled and self.debug.show_bounds:
            self._bounds.append(_Bound(label or f"text:{text[:12]}", rect, self.debug.bounds_color))
        if self.debug.enabled and self.debug.show_baselines:
            self.display.line(rect.x, text_rect.bottom - 1, rect.right - 1, text_rect.bottom - 1, self.debug.baseline_color, 1)
        return text_rect

    def button(
        self,
        rect: Rect,
        text: str,
        *,
        background: int,
        border: int,
        text_color: int,
        font=None,
        font_size: int = 18,
        label: str | None = None,
    ) -> None:
        self.fill(rect, background)
        self.stroke(rect, border, 2)
        self.text_box(rect.inset((6, 4, 6, 4)), text, text_color, font=font, font_size=font_size, align="center", valign="middle", compression="rle", label=label or f"button:{text}")

    def checkbox(
        self,
        rect: Rect,
        checked: bool,
        label: str,
        *,
        foreground: int,
        background: int,
        font=None,
        font_size: int = 16,
        label_name: str | None = None,
    ) -> None:
        self._require_on_canvas(rect)
        box_size = min(rect.height, 24)
        box = Rect(rect.x, rect.y + (rect.height - box_size) // 2, box_size, box_size)
        self.fill(box, background)
        self.stroke(box, foreground, 2)
        if checked:
            self.display.line(box.x + box_size // 5, box.y + box_size // 2, box.x + box_size * 2 // 5, box.y + box_size * 3 // 4, foreground, 3)
            self.display.line(box.x + box_size * 2 // 5, box.y + box_size * 3 // 4, box.x + box_size * 5 // 6, box.y + box_size // 5, foreground, 3)
        label_rect = Rect(box.right + 8, rect.y, max(0, rect.right - (box.right + 8)), rect.height)
        self.text_box(label_rect, label, foreground, font=font, font_size=font_size, valign="middle", compression="rle", label=label_name or f"checkbox:{label}")
        if self.debug.enabled and self.debug.show_bounds:
            self._bounds.append(_Bound(label_name or f"checkbox:{label}", rect, self.debug.bounds_color))

    def line_chart(self, rect: Rect, values: Sequence[float], *, line_color: int, grid_color: int, background: int, label: str | None = None) -> None:
        self._require_on_canvas(rect)
        self.display.line_chart(rect.x, rect.y, rect.width, rect.height, values, line_color=line_color, grid_color=grid_color, background=background)
        if self.debug.enabled and self.debug.show_bounds:
            self._bounds.append(_Bound(label or "line_chart", rect, self.debug.bounds_color))

    def bar_chart(self, rect: Rect, values: Sequence[float], *, bar_color: int, grid_color: int, background: int, label: str | None = None) -> None:
        self._require_on_canvas(rect)
        self.display.bar_chart(rect.x, rect.y, rect.width, rect.height, values, bar_color=bar_color, grid_color=grid_color, background=background)
        if self.debug.enabled and self.debug.show_bounds:
            self._bounds.append(_Bound(label or "bar_chart", rect, self.debug.bounds_color))

    def pie_chart(self, rect: Rect, values: Sequence[float], colors: Sequence[int], *, background: int, compression: str = "rle", label: str | None = None) -> None:
        self._require_on_canvas(rect)
        diameter = min(rect.width, rect.height)
        if diameter <= 0:
            return
        x = rect.x + (rect.width - diameter) // 2
        y = rect.y + (rect.height - diameter) // 2
        self.display.pie_chart(x, y, diameter, values, colors, background=background, compression=compression)
        if self.debug.enabled and self.debug.show_bounds:
            self._bounds.append(_Bound(label or "pie_chart", rect, self.debug.bounds_color))

    def begin_debug_overlay(self) -> None:
        if not self.debug.enabled:
            return
        if self.debug.minor_grid > 0:
            for x in range(0, SCREEN_WIDTH, self.debug.minor_grid):
                color = self.debug.major_color if self.debug.major_grid and x % self.debug.major_grid == 0 else self.debug.minor_color
                self.display.line(x, 0, x, SCREEN_HEIGHT - 1, color, 1)
            for y in range(0, SCREEN_HEIGHT, self.debug.minor_grid):
                color = self.debug.major_color if self.debug.major_grid and y % self.debug.major_grid == 0 else self.debug.minor_color
                self.display.line(0, y, SCREEN_WIDTH - 1, y, color, 1)
        self.display.stroke_rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, self.debug.major_color, 2)
        if self.debug.show_tile_profile:
            self.draw_tile_grid(self.debug.show_tile_profile)
        if self.debug.show_labels:
            self._draw_axis_labels()

    def end_debug_overlay(self) -> None:
        if not self.debug.enabled:
            return
        for bound in self._bounds:
            if bound.rect.width <= 0 or bound.rect.height <= 0:
                continue
            self.display.stroke_rect(bound.rect.x, bound.rect.y, bound.rect.width, bound.rect.height, bound.color, 1)
            if self.debug.show_labels and bound.name:
                label = bound.name[:18]
                width, height = self.text_metrics(label, None, 10)
                if width <= bound.rect.width and bound.rect.y >= height:
                    self.display.draw_text(label, bound.rect.x, bound.rect.y - height, self.debug.label_color, font=None, size=10, compression="rle")
        self._bounds.clear()

    def draw_tile_grid(self, profile: str) -> None:
        profiles = {"small": (18, 24), "medium": (30, 40), "large": (45, 60)}
        try:
            width, height = profiles[profile]
        except KeyError as exc:
            raise ValueError("tile profile must be small, medium, or large") from exc
        for x in range(0, SCREEN_WIDTH, width):
            self.display.line(x, 0, x, SCREEN_HEIGHT - 1, self.debug.tile_color, 1)
        for y in range(0, SCREEN_HEIGHT, height):
            self.display.line(0, y, SCREEN_WIDTH - 1, y, self.debug.tile_color, 1)

    def _draw_axis_labels(self) -> None:
        for x in range(0, SCREEN_WIDTH, self.debug.major_grid or 50):
            text = str(x)
            width, _ = self.text_metrics(text, None, 10)
            if x + width <= SCREEN_WIDTH:
                self.display.draw_text(text, x, 2, self.debug.label_color, font=None, size=10, compression="rle")
        for y in range(0, SCREEN_HEIGHT, self.debug.major_grid or 50):
            text = str(y)
            _, height = self.text_metrics(text, None, 10)
            if y + height <= SCREEN_HEIGHT:
                self.display.draw_text(text, 2, y, self.debug.label_color, font=None, size=10, compression="rle")

    @staticmethod
    def _require_on_canvas(rect: Rect) -> None:
        if rect.x < 0 or rect.y < 0 or rect.right > SCREEN_WIDTH or rect.bottom > SCREEN_HEIGHT:
            raise ValueError(
                f"rectangle {rect.x},{rect.y} {rect.width}x{rect.height} exceeds "
                f"the {SCREEN_WIDTH}x{SCREEN_HEIGHT} display canvas"
            )

    @staticmethod
    def _require_point(x: int, y: int) -> None:
        if not (0 <= x < SCREEN_WIDTH and 0 <= y < SCREEN_HEIGHT):
            raise ValueError(f"point {x},{y} is outside the {SCREEN_WIDTH}x{SCREEN_HEIGHT} display canvas")
