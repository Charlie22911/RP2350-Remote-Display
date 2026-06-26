#!/usr/bin/env python3
"""Hardware functional validation for RP2350 Remote Display.

The script uses only the published Python-library API. It exercises compatible
firmware through real USB traffic and preserves a concise JSON report for bug
reports or release records.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import time
import zlib

from PIL import Image, ImageDraw, ImageFont

from rp2350_remote_display import (
    Canvas,
    CoordinateSpace,
    DebugOverlay,
    DirtyTilePresenter,
    Layout,
    Rect,
    RemoteDisplay,
    RemoteDisplayError,
    __version__ as PROJECT_VERSION,
    rgb565,
)
from rp2350_remote_display.protocol import (
    CAP_ALPHA8_TILES,
    CAP_ASYNC_PRESENT,
    CAP_BRIGHTNESS,
    CAP_CANVAS_CRC32,
    CAP_DIRTY_TILE_PRESENT,
    CAP_FRAME_TRANSACTIONS,
    CAP_OPTIONAL_PACKET_CRC32,
    CAP_OPTIONAL_TILE_CRC32,
    CAP_PALETTE4_TILES,
    CAP_PALETTE64_TILES,
    CAP_RGB565_SCALE2,
    CAP_PALETTE4_SCALE2,
    CAP_PALETTE64_SCALE2,
    CAP_PRIMITIVES,
    CAP_RESOURCE_CACHE,
    CAP_RGB565_TILES,
    CAP_RLE,
    CAP_SEGMENTED_TILES,
    CAP_SESSION_REATTACH,
    CAP_TILE_PROFILES,
    TILE_PROFILES,
    CAP_TOUCH_COALESCING,
    CAP_TOUCH_EVENTS,
    CAP_DEVICE_TEXT,
    CAP_COPY_RECT,
    CAP_SCROLL_RECT,
    PROTOCOL_VERSION,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)

ROOT = Path(__file__).resolve().parent
ASSET_PATH = ROOT / "assets" / "reference_image_450x600.png"
ASSET_SHA256 = "62d9f269cc8b8f59005bad37768f43bce027697c31773e76ff1c76565f59b2a6"

BLACK = rgb565(0, 0, 0)
INK = rgb565(5, 9, 18)
PANEL = rgb565(17, 29, 50)
PANEL_ALT = rgb565(27, 45, 76)
GRID = rgb565(58, 92, 143)
WHITE = rgb565(244, 248, 255)
MUTED = rgb565(161, 185, 219)
CYAN = rgb565(45, 219, 255)
GREEN = rgb565(68, 232, 158)
YELLOW = rgb565(255, 214, 76)
ORANGE = rgb565(255, 141, 69)
PINK = rgb565(255, 84, 175)
VIOLET = rgb565(169, 111, 255)
RED = rgb565(255, 85, 94)

REQUIRED_CAPABILITIES = (
    CAP_RGB565_TILES
    | CAP_ALPHA8_TILES
    | CAP_RLE
    | CAP_TOUCH_EVENTS
    | CAP_PRIMITIVES
    | CAP_FRAME_TRANSACTIONS
    | CAP_BRIGHTNESS
    | CAP_SESSION_REATTACH
    | CAP_TILE_PROFILES
    | CAP_SEGMENTED_TILES
    | CAP_CANVAS_CRC32
    | CAP_DIRTY_TILE_PRESENT
    | CAP_RESOURCE_CACHE
    | CAP_PALETTE4_TILES
    | CAP_PALETTE64_TILES
    | CAP_RGB565_SCALE2
    | CAP_PALETTE4_SCALE2
    | CAP_PALETTE64_SCALE2
    | CAP_ASYNC_PRESENT
    | CAP_TOUCH_COALESCING
    | CAP_DEVICE_TEXT
    | CAP_COPY_RECT
    | CAP_SCROLL_RECT
)


class FunctionalTestError(RuntimeError):
    """Raised when a functional test assertion fails."""


@dataclass
class StageResult:
    name: str
    seconds: float
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class Report:
    project_version: str = PROJECT_VERSION
    library_protocol: int = PROTOCOL_VERSION
    started_utc: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    stages: list[StageResult] = field(default_factory=list)

    def add(self, name: str, started: float, **details: object) -> None:
        self.stages.append(StageResult(name, round(time.monotonic() - started, 4), details))


class Stage:
    def __init__(self, report: Report, name: str, detail: str = "") -> None:
        self.report = report
        self.name = name
        self.detail = detail
        self.started = 0.0
        self.details: dict[str, object] = {}

    def __enter__(self) -> "Stage":
        self.started = time.monotonic()
        suffix = f" | {self.detail}" if self.detail else ""
        print(f"\n[{time.strftime('%H:%M:%S')}] {self.name}{suffix}", flush=True)
        return self

    def set(self, **details: object) -> None:
        self.details.update(details)

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc is None:
            self.report.add(self.name, self.started, **self.details)
            print(f"  PASS ({time.monotonic() - self.started:.3f}s)", flush=True)
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a complete functional validation of rp2350-remote-display.")
    parser.add_argument("--hold-seconds", type=float, default=5.0, help="Hold time for each static visual stage.")
    parser.add_argument("--ball-frames", type=int, default=120, help="Frames in the photo-and-ball dirty-tile stage.")
    parser.add_argument("--dashboard-frames", type=int, default=120, help="Frames in the dashboard dirty-tile stage.")
    parser.add_argument("--touch-seconds", type=float, default=12.0, help="Duration of the interactive touch stage.")
    parser.add_argument("--touch-fps", type=float, default=60.0, help="Maximum host presentation rate during touch feedback.")
    parser.add_argument("--brightness", type=int, default=70, help="Brightness restored before completion.")
    parser.add_argument("--report", type=Path, default=None, help="Write a JSON report to this path.")
    parser.add_argument("--skip-touch", action="store_true", help="Skip the interactive touch stage.")
    parser.add_argument("--skip-strict-crc", action="store_true", help="Skip optional strict packet/tile CRC validation.")
    parser.add_argument("--quick", action="store_true", help="Use shorter animation and touch stages.")
    parser.add_argument("--preflight-only", action="store_true", help="Validate static scene geometry and text layout without opening the USB device.")
    args = parser.parse_args()
    if args.quick:
        args.hold_seconds = min(args.hold_seconds, 0.5)
        args.ball_frames = min(args.ball_frames, 36)
        args.dashboard_frames = min(args.dashboard_frames, 36)
        args.touch_seconds = min(args.touch_seconds, 4.0)
    if args.hold_seconds < 0:
        parser.error("--hold-seconds must be non-negative")
    if args.ball_frames < 4 or args.dashboard_frames < 4:
        parser.error("animation frame counts must be at least four")
    if args.touch_seconds < 1:
        parser.error("--touch-seconds must be at least one second")
    if args.touch_fps <= 0:
        parser.error("--touch-fps must be positive")
    if not 0 <= args.brightness <= 100:
        parser.error("--brightness must be in the range 0..100")
    return args


def choose_font(size: int, *, bold: bool = False):
    """Load DejaVu Sans from standard Linux locations, with a usable fallback."""
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu") / filename,
        Path("/usr/share/fonts/dejavu") / filename,
        Path("/usr/share/fonts/TTF") / filename,
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_12 = choose_font(12)
FONT_14 = choose_font(14)
FONT_16 = choose_font(16)
FONT_18 = choose_font(18)
FONT_22 = choose_font(22, bold=True)
FONT_28 = choose_font(28, bold=True)
FONT_42 = choose_font(42, bold=True)


def wait(display: RemoteDisplay, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        display.poll_events(timeout_ms=20)


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def require_capabilities(display: RemoteDisplay, *, strict: bool = False) -> None:
    if display.info is None:
        raise FunctionalTestError("HELLO did not return display information")
    if display.info.protocol_version != PROTOCOL_VERSION:
        raise FunctionalTestError(
            f"protocol mismatch: library={PROTOCOL_VERSION}, device={display.info.protocol_version}"
        )
    if (display.info.width, display.info.height) != (SCREEN_WIDTH, SCREEN_HEIGHT):
        raise FunctionalTestError("unexpected display geometry")
    required = REQUIRED_CAPABILITIES
    if strict:
        required |= CAP_OPTIONAL_PACKET_CRC32 | CAP_OPTIONAL_TILE_CRC32
    missing = required & ~display.info.capabilities
    if missing:
        raise FunctionalTestError(f"firmware is missing capability bits 0x{missing:08X}")


def verify_reference_asset() -> None:
    if not ASSET_PATH.is_file():
        raise FunctionalTestError(f"missing test image: {ASSET_PATH}")
    actual_hash = hashlib.sha256(ASSET_PATH.read_bytes()).hexdigest()
    if actual_hash != ASSET_SHA256:
        raise FunctionalTestError(
            f"unexpected test-image SHA-256: {actual_hash}; expected {ASSET_SHA256}"
        )
    with Image.open(ASSET_PATH) as source:
        if source.mode != "RGB" or source.size != (SCREEN_WIDTH, SCREEN_HEIGHT):
            raise FunctionalTestError(
                f"unexpected test-image format: mode={source.mode}, size={source.size}; expected RGB {SCREEN_WIDTH}x{SCREEN_HEIGHT}"
            )


def load_photo() -> Image.Image:
    verify_reference_asset()
    with Image.open(ASSET_PATH) as source:
        return source.copy()


def rgb565_bytes(image: Image.Image) -> bytes:
    return Canvas.from_image(image).rgb565_bytes()


def solid_rgb565(width: int, height: int, color: int) -> bytes:
    return struct.pack("<H", color) * (width * height)


def checker_rgb565(width: int, height: int, a: int = CYAN, b: int = ORANGE) -> bytes:
    output = bytearray(width * height * 2)
    for y in range(height):
        for x in range(width):
            struct.pack_into("<H", output, (y * width + x) * 2, a if ((x + y) & 1) == 0 else b)
    return bytes(output)


def alpha_badge(width: int = 45, height: int = 48) -> bytes:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((1, 1, width - 2, height - 2), radius=9, outline=255, width=3)
    draw.polygon(((width // 3, 10), (width // 3, height - 10), (width - 10, height // 2)), fill=255)
    return mask.tobytes()


MAX_DIRECT_TILE_WIDTH = 45
MAX_DIRECT_TILE_HEIGHT = 60


def require_direct_tile_geometry(width: int, height: int, label: str) -> None:
    if not 1 <= width <= MAX_DIRECT_TILE_WIDTH or not 1 <= height <= MAX_DIRECT_TILE_HEIGHT:
        raise FunctionalTestError(
            f"{label} exceeds the direct tile limit of "
            f"{MAX_DIRECT_TILE_WIDTH}x{MAX_DIRECT_TILE_HEIGHT}: {width}x{height}"
        )


def palette_tile(width: int = 45, height: int = 60) -> tuple[tuple[int, ...], bytes]:
    palette = (INK, PANEL_ALT, CYAN, GREEN, YELLOW, ORANGE, PINK, VIOLET)
    indices = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            if (x - width // 2) ** 2 + (y - height // 2) ** 2 < min(width, height) ** 2 // 5:
                index = 2 + ((x // 6 + y // 6) % 6)
            else:
                index = 1 if (x // 7 + y // 7) % 2 else 0
            indices[y * width + x] = index
    return palette, bytes(indices)



SCENE_SPACE = CoordinateSpace.design(1000, 1000)


def scene_rect(x: int, y: int, width: int, height: int) -> Rect:
    """Create a physical rectangle from the shared 1000x1000 design grid."""
    return SCENE_SPACE.rect(x, y, width, height)


def require_on_canvas(rect: Rect, label: str) -> None:
    if rect.x < 0 or rect.y < 0 or rect.right > SCREEN_WIDTH or rect.bottom > SCREEN_HEIGHT:
        raise FunctionalTestError(
            f"{label} exceeds the {SCREEN_WIDTH}x{SCREEN_HEIGHT} canvas: "
            f"{rect.x},{rect.y} {rect.width}x{rect.height}"
        )


def require_disjoint(rectangles: tuple[tuple[str, Rect], ...]) -> None:
    for index, (left_name, left) in enumerate(rectangles):
        require_on_canvas(left, left_name)
        for right_name, right in rectangles[index + 1:]:
            if left.intersects(right):
                raise FunctionalTestError(f"layout overlap: {left_name} intersects {right_name}")


def require_minimum_gap(first: Rect, second: Rect, gap: int, label: str) -> None:
    horizontal_gap = max(second.x - first.right, first.x - second.right)
    vertical_gap = max(second.y - first.bottom, first.y - second.bottom)
    if max(horizontal_gap, vertical_gap) < gap:
        raise FunctionalTestError(f"layout gap below {gap}px: {label}")


def require_contained(inner: Rect, outer: Rect, label: str) -> None:
    if inner.x < outer.x or inner.y < outer.y or inner.right > outer.right or inner.bottom > outer.bottom:
        raise FunctionalTestError(
            f"{label} is outside its parent region: "
            f"{inner.x},{inner.y} {inner.width}x{inner.height} not within "
            f"{outer.x},{outer.y} {outer.width}x{outer.height}"
        )


def require_interior_padding(inner: Rect, outer: Rect, padding: int, label: str) -> None:
    require_contained(inner, outer, label)
    left = inner.x - outer.x
    top = inner.y - outer.y
    right = outer.right - inner.right
    bottom = outer.bottom - inner.bottom
    if min(left, top, right, bottom) < padding:
        raise FunctionalTestError(f"{label} has less than {padding}px of interior padding")


def rgb565_to_rgb888_local(color: int) -> tuple[int, int, int]:
    return (
        ((color >> 11) & 0x1F) * 255 // 31,
        ((color >> 5) & 0x3F) * 255 // 63,
        (color & 0x1F) * 255 // 31,
    )


def composite_translucent_panel(canvas: Canvas, rect: Rect, color: int, opacity: int) -> None:
    """Blend a translucent host-composited panel over the current canvas."""
    if not 0 <= opacity <= 255:
        raise ValueError("opacity must be in the range 0..255")
    require_on_canvas(rect, "translucent panel")
    if rect.width == 0 or rect.height == 0:
        return
    from PIL import Image

    red, green, blue = rgb565_to_rgb888_local(color)
    base = canvas.image.crop((rect.x, rect.y, rect.right, rect.bottom)).convert("RGBA")
    overlay = Image.new("RGBA", (rect.width, rect.height), (red, green, blue, opacity))
    canvas.image.paste(Image.alpha_composite(base, overlay).convert("RGB"), (rect.x, rect.y))


def visual_text_rect(rect: Rect, text: str, font, *, align: str = "left", valign: str = "top") -> Rect:
    """Return the visible glyph-ink rectangle for a text box without drawing."""
    metrics = RemoteDisplay.measure_text(text, font)
    if metrics.ink_width > rect.width or metrics.ink_height > rect.height:
        raise FunctionalTestError(
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
    result = Rect(x, y, metrics.ink_width, metrics.ink_height)
    require_contained(result, rect, f"visual text {text!r}")
    return result


def display_text_box(
    display: RemoteDisplay,
    rect: Rect,
    text: str,
    color: int,
    *,
    font,
    align: str = "left",
    valign: str = "top",
    compression: str = "rle",
) -> Rect:
    """Draw aligned visible glyph ink through the library's public API."""
    result = visual_text_rect(rect, text, font, align=align, valign=valign)
    display.draw_text_box(
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        text,
        color,
        font=font,
        align=align,
        valign=valign,
        compression=compression,
    )
    return result


def canvas_text_box(
    canvas: Canvas,
    rect: Rect,
    text: str,
    color: int,
    *,
    font,
    align: str = "left",
    valign: str = "top",
) -> Rect:
    """Draw visual-ink-aligned text inside a host-composed Canvas region."""
    require_on_canvas(rect, "canvas text box")
    x, y, width, height = canvas.text_box(
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        text,
        color,
        font=font,
        align=align,
        valign=valign,
    )
    result = Rect(x, y, width, height)
    require_contained(result, rect, f"canvas text {text!r}")
    return result


def final_screen_geometry() -> dict[str, Rect]:
    """Define the completion screen as a constrained visual-ink composition."""
    card = Rect(30, 132, 390, 336)
    title = Rect(card.x + 26, card.y + 40, card.width - 52, 42)
    status = Rect(card.x + 26, card.y + 102, card.width - 52, 68)
    divider = Rect(card.x + 52, card.y + 196, card.width - 104, 2)
    caption = Rect(card.x + 26, card.y + 218, card.width - 52, 28)
    require_on_canvas(card, "final status card")
    for label, rect in (("final title", title), ("final status", status), ("final divider", divider), ("final caption", caption)):
        require_on_canvas(rect, label)
    require_disjoint((("final title", title), ("final status", status), ("final divider", divider), ("final caption", caption)))
    require_minimum_gap(title, status, 18, "final title to status")
    require_minimum_gap(status, divider, 18, "final status to divider")
    require_minimum_gap(divider, caption, 18, "final divider to caption")
    for text, font, rect, label in (
        ("FUNCTIONAL TEST", FONT_28, title, "final title"),
        ("COMPLETE", FONT_42, status, "final status"),
        ("See terminal output and JSON report for details.", FONT_14, caption, "final caption"),
    ):
        metrics = RemoteDisplay.measure_text(text, font)
        if metrics.ink_width > rect.width or metrics.ink_height > rect.height:
            raise FunctionalTestError(f"{label} does not fit its final screen region")
    return {"card": card, "title": title, "status": status, "divider": divider, "caption": caption}


def direct_scene_geometry() -> dict[str, Rect | tuple[Rect, ...]]:
    page = scene_rect(40, 30, 920, 940)
    header = scene_rect(40, 30, 920, 104)
    visual_row = scene_rect(40, 166, 920, 354)
    controls = scene_rect(40, 552, 920, 418)
    cards = visual_row.split_columns(3, gap=14)
    alpha_row = Rect(controls.x + 18, controls.y + 50, controls.width - 36, 66)
    alpha_columns = alpha_row.split_columns(4, gap=10)
    button_row = Rect(controls.x + 14, controls.y + 126, controls.width - 28, 44)
    buttons = button_row.split_columns(3, gap=12)
    chart_row = Rect(controls.x + 14, controls.y + 180, controls.width - 28, 50)
    chart_left, chart_right = chart_row.split_columns(2, gap=14)
    require_disjoint((
        ("direct header", header),
        ("direct visual row", visual_row),
        ("direct controls", controls),
    ))
    require_minimum_gap(header, visual_row, 14, "header to visual row")
    require_minimum_gap(visual_row, controls, 14, "visual row to controls")
    for index, card in enumerate(cards):
        require_on_canvas(card, f"direct card {index}")
    for index, button in enumerate(buttons):
        require_on_canvas(button, f"direct button {index}")

    for index, card in enumerate(cards):
        title = Rect(card.x + 12, card.y + 10, card.width - 24, 20)
        visual = Rect(card.x + 14, card.y + 42, card.width - 28, 104)
        caption = Rect(card.x + 12, card.y + 162, card.width - 24, 22)
        require_interior_padding(title, card, 10, f"direct card {index} title")
        require_interior_padding(visual, card, 12, f"direct card {index} visual")
        require_interior_padding(caption, card, 10, f"direct card {index} caption")
        require_disjoint((
            (f"direct card {index} title", title),
            (f"direct card {index} visual", visual),
            (f"direct card {index} caption", caption),
        ))

    badge_width, badge_height = 45, 48
    require_direct_tile_geometry(badge_width, badge_height, "direct alpha badge")
    for index, column in enumerate(alpha_columns):
        label = Rect(column.x, alpha_row.y, column.width, 16)
        text_sample = Rect(column.x, alpha_row.y + 27, column.width, 18)
        badge = Rect(column.x + (column.width - badge_width) // 2, alpha_row.y + 18, badge_width, badge_height)
        require_contained(label, alpha_row, f"direct alpha label {index}")
        if index < 2:
            require_contained(text_sample, alpha_row, f"direct alpha text sample {index}")
        else:
            require_contained(badge, alpha_row, f"direct alpha badge {index}")
            require_minimum_gap(label, badge, 2, f"direct alpha label to badge {index}")

    for index, chart in enumerate((chart_left, chart_right)):
        require_interior_padding(chart, controls, 12, f"direct chart {index}")
    for index, button in enumerate(buttons):
        require_interior_padding(button, controls, 12, f"direct button {index}")
    require_disjoint((
        ("direct alpha row", alpha_row),
        ("direct button row", button_row),
        ("direct chart row", chart_row),
    ))
    return {
        "page": page,
        "header": header,
        "visual_row": visual_row,
        "controls": controls,
        "cards": cards,
        "alpha_row": alpha_row,
        "alpha_columns": alpha_columns,
        "buttons": buttons,
        "chart_left": chart_left,
        "chart_right": chart_right,
    }


def coordinate_reference_geometry() -> dict[str, Rect | tuple[Rect, ...]]:
    """Geometry for the presentation-ready coordinate reference screen."""
    content = scene_rect(82, 90, 878, 840)
    header = scene_rect(82, 90, 878, 124)
    main = scene_rect(82, 244, 878, 500)
    left_card, right_card = main.split_columns(2, gap=16)
    right_top, right_bottom = right_card.inset(14).split_rows(2, gap=16)
    footer = scene_rect(82, 774, 878, 156)
    top_ruler = Rect(content.x, 12, content.width, 24)
    left_ruler = Rect(4, content.y, 26, content.height)

    require_disjoint((
        ("coordinate header", header),
        ("coordinate main", main),
        ("coordinate footer", footer),
    ))
    require_minimum_gap(header, main, 14, "coordinate header to main")
    require_minimum_gap(main, footer, 14, "coordinate main to footer")
    require_contained(header, content, "coordinate header")
    require_contained(main, content, "coordinate main")
    require_contained(footer, content, "coordinate footer")
    require_interior_padding(right_top, right_card, 12, "coordinate right top")
    require_interior_padding(right_bottom, right_card, 12, "coordinate right bottom")
    require_on_canvas(top_ruler, "coordinate top ruler")
    require_on_canvas(left_ruler, "coordinate left ruler")

    return {
        "content": content,
        "header": header,
        "main": main,
        "left_card": left_card,
        "right_card": right_card,
        "right_top": right_top,
        "right_bottom": right_bottom,
        "footer": footer,
        "top_ruler": top_ruler,
        "left_ruler": left_ruler,
    }


def motion_scene_geometry() -> dict[str, Rect]:
    page = scene_rect(40, 30, 920, 940)
    header = scene_rect(40, 30, 920, 104)
    field = scene_rect(40, 166, 920, 570)
    footer = scene_rect(40, 768, 920, 202)
    field_title = Rect(field.x + 16, field.y + 14, field.width - 32, 22)
    ball_track = field.inset((30, 56, 30, 34))
    footer_title = Rect(footer.x + 18, footer.y + 14, footer.width - 36, 20)
    progress = Rect(footer.x + 18, footer.y + 58, footer.width - 36, 16)
    footer_caption = Rect(footer.x + 18, footer.y + 96, footer.width - 36, 24)
    require_disjoint((("motion header", header), ("motion field", field), ("motion footer", footer)))
    require_minimum_gap(header, field, 14, "motion header to field")
    require_minimum_gap(field, footer, 14, "motion field to footer")
    for name, rect in (
        ("motion page", page),
        ("motion field title", field_title),
        ("motion ball track", ball_track),
        ("motion footer title", footer_title),
        ("motion progress", progress),
        ("motion footer caption", footer_caption),
    ):
        require_on_canvas(rect, name)
    return {
        "page": page,
        "header": header,
        "field": field,
        "field_title": field_title,
        "ball_track": ball_track,
        "footer": footer,
        "footer_title": footer_title,
        "progress": progress,
        "footer_caption": footer_caption,
    }


def dashboard_scene_geometry() -> dict[str, Rect]:
    page = scene_rect(40, 30, 920, 940)
    header = scene_rect(40, 30, 920, 104)
    metrics = scene_rect(40, 166, 920, 342)
    cpu_card, memory_card = metrics.split_columns(2, gap=18)
    network_card = scene_rect(40, 540, 920, 430)
    require_disjoint((("dashboard header", header), ("dashboard metrics", metrics), ("dashboard network", network_card)))
    require_minimum_gap(header, metrics, 14, "dashboard header to metrics")
    require_minimum_gap(metrics, network_card, 14, "dashboard metrics to network")
    return {
        "page": page,
        "header": header,
        "cpu_card": cpu_card,
        "memory_card": memory_card,
        "network_card": network_card,
    }


def crc_diagnostic_geometry() -> dict[str, Rect]:
    """Define the CRC diagnostic card and its text-safe regions."""
    card = Rect(18, 18, 414, 564)
    title = Rect(42, 72, 366, 34)
    subtitle = Rect(42, 116, 366, 22)
    line_chart = Rect(42, 180, 366, 140)
    bar_chart = Rect(42, 350, 202, 120)
    pie_chart = Rect(274, 350, 120, 120)
    for label, rect in (
        ("CRC card", card),
        ("CRC title", title),
        ("CRC subtitle", subtitle),
        ("CRC line chart", line_chart),
        ("CRC bar chart", bar_chart),
        ("CRC pie chart", pie_chart),
    ):
        require_on_canvas(rect, label)
    for label, rect in (
        ("CRC title", title),
        ("CRC subtitle", subtitle),
        ("CRC line chart", line_chart),
        ("CRC bar chart", bar_chart),
        ("CRC pie chart", pie_chart),
    ):
        require_contained(rect, card, label)
    require_disjoint((
        ("CRC title", title),
        ("CRC subtitle", subtitle),
        ("CRC line chart", line_chart),
        ("CRC bar chart", bar_chart),
        ("CRC pie chart", pie_chart),
    ))
    return {
        "card": card,
        "title": title,
        "subtitle": subtitle,
        "line_chart": line_chart,
        "bar_chart": bar_chart,
        "pie_chart": pie_chart,
    }


def _audit_text_regions(name: str, entries: tuple[tuple[str, Rect, str, object, str, str], ...]) -> None:
    """Verify that visible text fits its box and never overlaps peer labels."""
    ink_regions: list[tuple[str, Rect]] = []
    for label, rect, text, font, align, valign in entries:
        ink = visual_text_rect(rect, text, font, align=align, valign=valign)
        require_contained(ink, rect, f"{name} {label}")
        ink_regions.append((f"{name} {label}", ink))
    require_disjoint(tuple(ink_regions))


def visual_layout_audit() -> None:
    """Audit all presentation-only text before any USB traffic is sent."""
    direct = direct_scene_geometry()
    header = direct["header"]
    controls = direct["controls"]
    cards = direct["cards"]
    alpha_columns = direct["alpha_columns"]
    assert isinstance(header, Rect) and isinstance(controls, Rect) and isinstance(cards, tuple) and isinstance(alpha_columns, tuple)
    entries: list[tuple[str, Rect, str, object, str, str]] = [
        ("title", header.inset((14, 10, 14, 10)), "PRIMITIVES AND WIDGETS", FONT_22, "center", "middle"),
        ("controls", Rect(controls.x + 14, controls.y + 12, controls.width - 28, 24), "TEXT, ALPHA8, BUTTONS, AND CHECKBOXES", FONT_14, "center", "middle"),
    ]
    for card, label in zip(cards, ("LINES", "LINE CHART", "PIE CHART")):
        entries.append((f"{label} title", Rect(card.x + 12, card.y + 10, card.width - 24, 20), label, FONT_12, "center", "middle"))
        entries.append((f"{label} caption", Rect(card.x + 12, card.y + 162, card.width - 24, 22), "Safe visual area", FONT_12, "center", "middle"))
    for column, label in zip(alpha_columns, ("RAW TEXT", "RLE TEXT", "RAW MASK", "RLE MASK")):
        entries.append((f"{label} label", Rect(column.x, column.y, column.width, 16), label, FONT_12, "center", "middle"))
    _audit_text_regions("direct", tuple(entries))

    coordinate = coordinate_reference_geometry()
    header = coordinate["header"]
    left_card = coordinate["left_card"]
    right_top = coordinate["right_top"]
    right_bottom = coordinate["right_bottom"]
    footer = coordinate["footer"]
    assert all(isinstance(rect, Rect) for rect in (header, left_card, right_top, right_bottom, footer))
    left_inner = left_card.inset(16)
    top_inner = right_top.inset(12)
    _audit_text_regions("coordinate", (
        ("title", Rect(header.x + 16, header.y + 12, header.width - 32, 24), "COORDINATE REFERENCE", FONT_18, "center", "middle"),
        ("subtitle", Rect(header.x + 16, header.y + 44, header.width - 32, 16), "1000x1000 design grid to 450x600 pixels", FONT_12, "center", "middle"),
        ("line title", Rect(left_inner.x, left_inner.y, left_inner.width, 18), "LINE CHART REGION", FONT_12, "center", "middle"),
        ("bar title", Rect(top_inner.x, top_inner.y, top_inner.width, 16), "BAR CHART REGION", FONT_12, "center", "middle"),
        ("action", right_bottom.inset(14), "LAYOUT OK", FONT_16, "center", "middle"),
        ("confirmation", Rect(footer.x + 52, footer.y + 20, footer.width - 70, footer.height - 40), "Controls stay inside reserved regions", FONT_12, "left", "middle"),
    ))

    _audit_text_regions("brightness", (
        ("title", Rect(78, 178, 294, 42), "BRIGHTNESS", FONT_28, "center", "middle"),
        ("value", Rect(78, 242, 294, 64), "100%", FONT_42, "center", "middle"),
        ("meter label", Rect(78, 338, 294, 18), "PANEL OUTPUT", FONT_12, "center", "middle"),
    ))

    _audit_text_regions("tile", (
        ("title", Rect(52, 52, 346, 28), "DIRECT TILE MODES", FONT_22, "center", "middle"),
        ("subtitle", Rect(52, 84, 346, 18), "Raw, RLE, and Palette4 tile decode paths", FONT_12, "center", "middle"),
        ("caption one", Rect(52, 488, 346, 16), "Cyan and orange checker detail should remain distinct.", FONT_12, "center", "middle"),
        ("caption two", Rect(52, 508, 346, 16), "The Palette4 tile uses local four-bit indices.", FONT_12, "center", "middle"),
    ))

    _audit_text_regions("cache", (
        ("title", Rect(52, 52, 346, 28), "RESOURCE CACHE", FONT_22, "center", "middle"),
        ("subtitle", Rect(52, 84, 346, 18), "Upload once, then replay by resource ID", FONT_12, "center", "middle"),
        ("footer line one", Rect(50, 519, 350, 14), "Tintable Alpha8 and Palette4 resources", FONT_12, "center", "middle"),
        ("footer line two", Rect(50, 533, 350, 14), "replay from the session cache.", FONT_12, "center", "middle"),
    ))

    motion = motion_scene_geometry()
    _audit_text_regions("motion", (
        ("header", motion["header"].inset((16, 10, 16, 32)), "DIRTY-TILE MOTION", FONT_18, "left", "middle"),
        ("field title", motion["field_title"], "SEMI-TRANSPARENT BALL FIELD", FONT_14, "left", "middle"),
        ("field note", Rect(motion["field"].right - 170, motion["field"].y + 14, 154, 18), "PHOTO REMAINS VISIBLE", FONT_12, "right", "middle"),
        ("footer", motion["footer_caption"], "Photo field is restored before every dirty-tile frame.", FONT_12, "left", "middle"),
    ))

    dashboard = dashboard_scene_geometry()
    header = dashboard["header"]
    _audit_text_regions("dashboard", (
        ("header", Rect(header.x + 18, header.y + 10, header.width - 36, 20), "SYSTEM DASHBOARD", FONT_18, "left", "middle"),
        ("subtitle", Rect(header.x + 18, header.y + 38, header.width - 36, 14), "Medium dirty tiles, bounded metric cards", FONT_12, "left", "middle"),
    ))

    touch_entries = (
        ("title", Rect(36, 36, 378, 24), "TOUCH LATENCY AND COMPOSITING", FONT_18, "left", "middle"),
        ("subtitle", Rect(36, 64, 378, 18), "The marker is composited over a fresh backing canvas.", FONT_12, "left", "middle"),
    )
    _audit_text_regions("touch", touch_entries)

    crc = crc_diagnostic_geometry()
    _audit_text_regions("canvas CRC", (
        ("title", crc["title"], "CANVAS CRC DIAGNOSTIC", FONT_22, "center", "middle"),
        ("subtitle", crc["subtitle"], "The host and panel framebuffer should match exactly.", FONT_12, "center", "middle"),
    ))


def design_preflight() -> None:
    """Validate scene geometry and visual text placement before USB I/O."""
    direct_scene_geometry()
    coordinate_reference_geometry()
    motion_scene_geometry()
    dashboard_scene_geometry()
    crc_diagnostic_geometry()
    final_screen_geometry()
    copy_scroll_scene()
    verify_reference_asset()
    visual_layout_audit()


def device_text_stage(display: RemoteDisplay, hold: float, report: Report) -> None:
    with Stage(report, "DEVICE TEXT", "flash-resident GNU Unifont grid font and coordinate metrics") as stage:
        font = display.device_font_info()
        if (font.font_id, font.cell_width, font.cell_height) != (0, 8, 16):
            raise FunctionalTestError(f"unexpected built-in font metrics: {font}")
        if font.glyph_count != 127011 or font.fallback_codepoint != 0x003F or font.coverage_version != 2:
            raise FunctionalTestError(f"unexpected GNU Unifont coverage: {font}")

        narrow_sample = "CPU 42% | Ω ± 26°C"
        narrow = display.measure_device_text(narrow_sample)
        expected_narrow_width = len(narrow_sample) * font.cell_width
        if (narrow.width, narrow.height, narrow.glyph_count, narrow.missing_glyph_count) != (
            expected_narrow_width,
            font.cell_height,
            len(narrow_sample),
            0,
        ):
            raise FunctionalTestError(f"unexpected narrow-cell device text metrics: {narrow}")

        wide = display.measure_device_text("A漢B")
        if (wide.width, wide.height, wide.glyph_count, wide.missing_glyph_count) != (
            4 * font.cell_width,
            font.cell_height,
            3,
            0,
        ):
            raise FunctionalTestError(f"unexpected full-width device text metrics: {wide}")

        multiline = display.measure_device_text("METRICS\n8x16 CELLS", scale=2)
        if multiline.width != 10 * font.cell_width * 2 or multiline.height != font.cell_height * 2 * 2:
            raise FunctionalTestError(f"unexpected multiline device-text metrics: {multiline}")

        fallback = display.measure_device_text(chr(0x10FFFF))
        if (fallback.width, fallback.height, fallback.glyph_count, fallback.missing_glyph_count) != (
            font.cell_width,
            font.cell_height,
            1,
            1,
        ):
            raise FunctionalTestError(f"unexpected missing-glyph fallback: {fallback}")

        with display.frame(timeout_ms=3000):
            display.clear(INK)
            display.fill_rect(18, 18, 414, 564, PANEL)
            display.stroke_rect(18, 18, 414, 564, CYAN, 2)
            display.draw_device_text("DEVICE TEXT", 38, 42, WHITE, scale=2)
            display.draw_device_text("Firmware-resident GNU Unifont 17.0.04", 38, 82, MUTED)
            display.fill_rect(38, 118, 374, 136, INK)
            display.stroke_rect(38, 118, 374, 136, GRID, 1)
            display.draw_device_text("┌────────────────────────────────────────────┐", 46, 130, CYAN)
            display.draw_device_text("│ CPU 42% │ TEMP 26°C │ USB ONLINE │ ✓ │", 46, 146, WHITE)
            display.draw_device_text("│ 1 CELL: Ω ± → │ 2 CELLS: 漢 字 │", 46, 162, YELLOW)
            display.draw_device_text("└────────────────────────────────────────────┘", 46, 178, CYAN)
            display.fill_rect(38, 280, 374, 118, INK)
            display.stroke_rect(38, 280, 374, 118, GRID, 1)
            display.draw_device_text("COORDINATE CELL GRID", 52, 296, GREEN)
            display.draw_device_text("base: 8 x 16 px", 52, 320, MUTED)
            display.draw_device_text("wide: 16 x 16 px", 52, 336, MUTED)
            display.draw_device_text("scale 2: 16 x 32 px", 52, 352, MUTED)
            display.draw_device_text("METRICS", 258, 320, WHITE, scale=2)
            display.draw_device_text("UTF-8 grid text", 258, 356, CYAN)
            display.draw_device_text("Missing glyphs render as ?", 52, 430, ORANGE)
            display.draw_device_text("Text pixels are generated on the Pico.", 52, 522, MUTED)
            display.draw_device_text("Host transfer: command metadata + UTF-8 bytes.", 52, 538, MUTED)
        wait(display, hold)
        stage.set(
            font_id=font.font_id,
            cell=f"{font.cell_width}x{font.cell_height}",
            glyph_count=font.glyph_count,
            coverage_version=font.coverage_version,
            narrow_sample_width=narrow.width,
            wide_sample_width=wide.width,
            fallback_glyphs=fallback.missing_glyph_count,
        )


def direct_primitives_stage(display: RemoteDisplay, hold: float, report: Report) -> None:
    with Stage(report, "PRIMITIVES + WIDGETS", "coordinate layout, safe zones, charts, controls, Alpha8") as stage:
        geometry = direct_scene_geometry()
        with display.frame(timeout_ms=6000):
            display.clear(INK)
            layout = Layout(display, space=CoordinateSpace.pixels())
            header = layout.region("header", geometry["header"])
            cards = geometry["cards"]
            controls = layout.region("controls", geometry["controls"])
            assert isinstance(cards, tuple)
            assert isinstance(header, Rect)
            assert isinstance(controls, Rect)

            layout.fill(header, PANEL)
            layout.stroke(header, CYAN, 2)
            layout.text_box(header.inset((14, 10, 14, 10)), "PRIMITIVES AND WIDGETS", WHITE, font=FONT_22, align="center", valign="middle", label="title")

            labels = ("LINES", "LINE CHART", "PIE CHART")
            accents = (CYAN, GREEN, ORANGE)
            for card, label, accent in zip(cards, labels, accents):
                card = layout.region(f"{label.lower()} card", card)
                layout.fill(card, PANEL)
                layout.stroke(card, GRID, 2)
                title_box = Rect(card.x + 12, card.y + 10, card.width - 24, 20)
                visual = Rect(card.x + 14, card.y + 42, card.width - 28, 104)
                caption = Rect(card.x + 12, card.y + 162, card.width - 24, 22)
                layout.text_box(title_box, label, WHITE, font=FONT_12, align="center", valign="middle", label=f"{label.lower()} title")
                if label == "LINES":
                    layout.stroke(visual, GRID, 1)
                    display.line(visual.x + 7, visual.bottom - 12, visual.right - 8, visual.y + 22, accent, 2)
                    display.polyline(
                        (
                            (visual.x + 7, visual.y + 76),
                            (visual.x + visual.width // 3, visual.y + 40),
                            (visual.x + visual.width * 2 // 3, visual.y + 78),
                            (visual.right - 9, visual.y + 32),
                        ),
                        VIOLET,
                        2,
                    )
                elif label == "LINE CHART":
                    layout.line_chart(visual, (22, 48, 35, 66, 51, 78, 62, 88), line_color=accent, grid_color=GRID, background=PANEL, label="line chart visual")
                else:
                    layout.pie_chart(visual, (48, 28, 16, 8), (CYAN, GREEN, YELLOW, ORANGE), background=PANEL, compression="rle", label="pie chart visual")
                layout.text_box(caption, "Safe visual area", MUTED, font=FONT_12, align="center", valign="middle", label=f"{label.lower()} caption")

            layout.fill(controls, PANEL)
            layout.stroke(controls, GRID, 2)
            controls_title = Rect(controls.x + 14, controls.y + 12, controls.width - 28, 24)
            layout.text_box(controls_title, "TEXT, ALPHA8, BUTTONS, AND CHECKBOXES", WHITE, font=FONT_14, align="center", valign="middle", label="controls title")

            alpha_row = geometry["alpha_row"]
            alpha_columns = geometry["alpha_columns"]
            assert isinstance(alpha_row, Rect) and isinstance(alpha_columns, tuple)
            badge_width, badge_height = 45, 48
            require_direct_tile_geometry(badge_width, badge_height, "alpha badge")
            badge = alpha_badge(badge_width, badge_height)
            alpha_specs = (
                ("RAW TEXT", CYAN, "raw"),
                ("RLE TEXT", GREEN, "rle"),
                ("RAW MASK", ORANGE, "raw"),
                ("RLE MASK", PINK, "rle"),
            )
            for column, (label, color, compression) in zip(alpha_columns, alpha_specs):
                label_box = Rect(column.x, column.y, column.width, 16)
                layout.text_box(label_box, label, color, font=FONT_12, align="center", valign="middle", label=f"{label.lower()} label")
                if "TEXT" in label:
                    text = "RAW" if compression == "raw" else "RLE"
                    layout.text_box(Rect(column.x, column.y + 27, column.width, 18), text, color, font=FONT_14, align="center", valign="middle", label=f"{label.lower()} sample")
                else:
                    badge_x = column.x + (column.width - badge_width) // 2
                    display.blit_alpha(badge_x, column.y + 18, badge_width, badge_height, badge, color, compression=compression)

            buttons = geometry["buttons"]
            assert isinstance(buttons, tuple)
            for button, (label, border) in zip(buttons, (("APPLY", CYAN), ("PAUSE", ORANGE), ("LIVE", GREEN))):
                display.button(button.x, button.y, button.width, button.height, label, background=PANEL_ALT, border=border, text_color=WHITE, font=FONT_14, font_size=14)

            chart_left = geometry["chart_left"]
            chart_right = geometry["chart_right"]
            assert isinstance(chart_left, Rect) and isinstance(chart_right, Rect)
            display.bar_chart(chart_left.x, chart_left.y, chart_left.width, chart_left.height, (14, 35, 23, 57, 46, 72, 50), bar_color=VIOLET, grid_color=GRID, background=PANEL)
            display.line_chart(chart_right.x, chart_right.y, chart_right.width, chart_right.height, (30, 52, 44, 65, 58, 76), line_color=YELLOW, grid_color=GRID, background=PANEL)
        stage.set(cards=3, coordinate_space="1000x1000 design grid", alpha_raw=True, alpha_rle=True, widgets=True, charts=3)
        wait(display, hold)


def _draw_coordinate_rulers(display: RemoteDisplay, geometry: dict[str, Rect | tuple[Rect, ...]]) -> None:
    """Draw unobtrusive pixel rulers in the reserved outer gutter."""
    content = geometry["content"]
    assert isinstance(content, Rect)

    ruler_y = content.y - 16
    ruler_x = content.x - 10
    display.line(content.x, ruler_y, content.right - 1, ruler_y, GRID, 1)
    display.line(ruler_x, content.y, ruler_x, content.bottom - 1, GRID, 1)

    for x in range(50, SCREEN_WIDTH, 50):
        if content.x <= x < content.right:
            display.line(x, ruler_y - 3, x, ruler_y + 3, CYAN, 1)
            if x % 100 == 0 and x + 18 <= SCREEN_WIDTH:
                display_text_box(display, Rect(x - 12, 2, 24, 14), str(x), MUTED, font=FONT_12, align="center", valign="middle")

    for y in range(50, SCREEN_HEIGHT, 50):
        if content.y <= y < content.bottom:
            display.line(ruler_x - 3, y, ruler_x + 3, y, CYAN, 1)
            if y % 100 == 0 and y + 12 <= SCREEN_HEIGHT:
                display_text_box(display, Rect(2, y - 8, 24, 16), str(y), MUTED, font=FONT_12, align="left", valign="middle")


def coordinate_reference_stage(display: RemoteDisplay, hold: float, report: Report) -> None:
    """Clean, presentation-ready coordinate and bounds reference page."""
    with Stage(report, "COORDINATE REFERENCE", "1000x1000 design space with reserved pixel rulers") as stage:
        geometry = coordinate_reference_geometry()
        content = geometry["content"]
        header = geometry["header"]
        left_card = geometry["left_card"]
        right_card = geometry["right_card"]
        right_top = geometry["right_top"]
        right_bottom = geometry["right_bottom"]
        footer = geometry["footer"]
        assert all(isinstance(rect, Rect) for rect in (content, header, left_card, right_card, right_top, right_bottom, footer))

        with display.frame(timeout_ms=7000):
            display.clear(INK)
            _draw_coordinate_rulers(display, geometry)
            layout = Layout(display, space=CoordinateSpace.design(1000, 1000))

            layout.fill(header, PANEL)
            layout.stroke(header, CYAN, 2)
            layout.text_box(
                Rect(header.x + 16, header.y + 12, header.width - 32, 24),
                "COORDINATE REFERENCE",
                WHITE,
                font=FONT_18,
                align="center",
                valign="middle",
                label="coordinate title",
            )
            layout.text_box(
                Rect(header.x + 16, header.y + 44, header.width - 32, 16),
                "1000x1000 design grid to 450x600 pixels",
                MUTED,
                font=FONT_12,
                align="center",
                valign="middle",
                label="coordinate subtitle",
            )

            for card, border in ((left_card, GREEN), (right_card, ORANGE)):
                layout.fill(card, PANEL)
                layout.stroke(card, border, 2)

            left_inner = left_card.inset(16)
            left_title = Rect(left_inner.x, left_inner.y, left_inner.width, 18)
            left_chart = Rect(left_inner.x, left_inner.y + 32, left_inner.width, left_inner.height - 32)
            require_disjoint((("coordinate left title", left_title), ("coordinate left chart", left_chart)))
            layout.text_box(left_title, "LINE CHART REGION", WHITE, font=FONT_12, align="center", valign="middle", label="coordinate line title")
            layout.line_chart(
                left_chart,
                (14, 22, 20, 38, 31, 48, 42, 59),
                line_color=CYAN,
                grid_color=GRID,
                background=PANEL,
                label="coordinate line chart",
            )

            for rect, border in ((right_top, ORANGE), (right_bottom, ORANGE)):
                layout.fill(rect, PANEL_ALT)
                layout.stroke(rect, border, 1)
            right_top_inner = right_top.inset(12)
            top_title = Rect(right_top_inner.x, right_top_inner.y, right_top_inner.width, 16)
            top_chart = Rect(right_top_inner.x, right_top_inner.y + 26, right_top_inner.width, right_top_inner.height - 26)
            require_disjoint((("coordinate bar title", top_title), ("coordinate bar chart", top_chart)))
            layout.text_box(top_title, "BAR CHART REGION", WHITE, font=FONT_12, align="center", valign="middle", label="coordinate bar title")
            layout.bar_chart(top_chart, (34, 58, 42, 73, 61), bar_color=GREEN, grid_color=GRID, background=PANEL_ALT, label="coordinate bar chart")

            layout.button(
                right_bottom.inset(14),
                "LAYOUT OK",
                background=PANEL,
                border=ORANGE,
                text_color=WHITE,
                font=FONT_16,
                label="coordinate action",
            )

            layout.fill(footer, PANEL)
            layout.stroke(footer, PINK, 2)
            layout.checkbox(
                footer.inset((18, 20, 18, 20)),
                True,
                "Controls stay inside reserved regions",
                foreground=PINK,
                background=PANEL_ALT,
                font=FONT_12,
                label_name="coordinate confirmation",
            )
        stage.set(design_space="1000x1000", coordinate_rulers="reserved outer gutter", overlays=False)
        wait(display, hold)


def debug_overlay_stage(display: RemoteDisplay, hold: float, report: Report) -> None:
    """Exercise the optional diagnostic overlay without mixing it into UI examples."""
    with Stage(report, "DEBUG OVERLAY DIAGNOSTIC", "sparse bounds, baseline, pixel grid, and medium tile grid") as stage:
        debug = DebugOverlay(
            enabled=True,
            minor_grid=50,
            major_grid=100,
            show_labels=True,
            show_bounds=True,
            show_baselines=True,
            show_tile_profile="medium",
        )
        with display.frame(timeout_ms=7000):
            display.clear(INK)
            layout = Layout(display, space=CoordinateSpace.pixels(), debug=debug)
            layout.begin_debug_overlay()

            samples = (
                ("debug-a", Rect(66, 126, 128, 92), CYAN),
                ("debug-b", Rect(256, 280, 128, 92), GREEN),
                ("debug-c", Rect(116, 430, 218, 84), ORANGE),
            )
            for name, rect, color in samples:
                layout.region(name, rect, color=color)
                layout.fill(rect, PANEL)
                layout.stroke(rect, color, 2)
            layout.text_box(Rect(86, 154, 88, 18), "TEXT", WHITE, font=FONT_12, align="center", valign="middle", label="debug text")
            layout.text_box(Rect(136, 460, 178, 18), "OVERLAY SAMPLE", WHITE, font=FONT_12, align="center", valign="middle", label="debug caption")
            layout.end_debug_overlay()
        stage.set(pixel_grid=True, tile_profile="medium", isolated_from_presentation_scenes=True)
        wait(display, hold)



def _expand_palette4_tiles(width: int, height: int, tiles) -> bytes:
    """Expand library-generated Palette4 tiles into a host RGB565 preview."""
    output = bytearray(width * height * 2)
    for tile_x, tile_y, tile_width, tile_height, palette, indices in tiles:
        for row in range(tile_height):
            for column in range(tile_width):
                color = palette[indices[row * tile_width + column]]
                destination = ((tile_y + row) * width + tile_x + column) * 2
                output[destination] = color & 0xFF
                output[destination + 1] = color >> 8
    return bytes(output)


def palette4_dither_preflight(photo: Image.Image) -> int:
    """Require Floyd-Steinberg to change the real reference image before USB I/O."""
    profile = TILE_PROFILES["medium"]
    none_tiles = list(RemoteDisplay._palette4_image_tiles(None, photo, profile, dither="none"))
    dithered_tiles = list(
        RemoteDisplay._palette4_image_tiles(None, photo, profile, dither="floyd-steinberg")
    )
    none_rgb565 = _expand_palette4_tiles(photo.width, photo.height, none_tiles)
    dithered_rgb565 = _expand_palette4_tiles(photo.width, photo.height, dithered_tiles)
    changed_pixels = sum(
        none_rgb565[offset:offset + 2] != dithered_rgb565[offset:offset + 2]
        for offset in range(0, len(none_rgb565), 2)
    )
    if changed_pixels == 0:
        raise FunctionalTestError(
            "Floyd-Steinberg Palette4 output matches no-dither for the reference image"
        )
    return changed_pixels


def palette64_dither_preflight(photo: Image.Image) -> int:
    """Require Palette64 Floyd-Steinberg to change the reference image before USB I/O."""
    profile = TILE_PROFILES["medium"]
    none_tiles = list(RemoteDisplay._palette64_image_tiles(None, photo, profile, dither="none"))
    dithered_tiles = list(
        RemoteDisplay._palette64_image_tiles(None, photo, profile, dither="floyd-steinberg")
    )
    none_rgb565 = _expand_palette4_tiles(photo.width, photo.height, none_tiles)
    dithered_rgb565 = _expand_palette4_tiles(photo.width, photo.height, dithered_tiles)
    changed_pixels = sum(
        none_rgb565[offset:offset + 2] != dithered_rgb565[offset:offset + 2]
        for offset in range(0, len(none_rgb565), 2)
    )
    if changed_pixels == 0:
        raise FunctionalTestError(
            "Floyd-Steinberg Palette64 output matches no-dither for the reference image"
        )
    return changed_pixels


def image_modes_stage(
    display: RemoteDisplay,
    photo: Image.Image,
    hold: float,
    report: Report,
    palette4_dithered_pixels: int,
    palette64_dithered_pixels: int,
) -> None:
    expected_rgb565_crc = crc32(rgb565_bytes(photo))
    half_photo = photo.resize((photo.width // 2, photo.height // 2), Image.Resampling.BILINEAR)
    cases = (
        ("RGB565 RAW", "draw_image", photo, "raw", "small", "none", True),
        ("RGB565 RLE", "draw_image", photo, "rle", "medium", "none", True),
        ("PALETTE4", "draw_image", photo, "palette4", "large", "none", False),
        ("PALETTE4 FLOYD-STEINBERG", "draw_image", photo, "palette4", "medium", "floyd-steinberg", False),
        ("PALETTE64", "draw_image", photo, "palette64", "large", "none", False),
        ("PALETTE64 FLOYD-STEINBERG", "draw_image", photo, "palette64", "medium", "floyd-steinberg", False),
        ("PALETTE4 SCALE2", "draw_image_scale2", half_photo, "palette4", "scale2", "none", False),
        ("PALETTE4 SCALE2 FLOYD-STEINBERG", "draw_image_scale2", half_photo, "palette4", "scale2", "floyd-steinberg", False),
        ("PALETTE64 SCALE2", "draw_image_scale2", half_photo, "palette64", "scale2", "none", False),
        ("PALETTE64 SCALE2 FLOYD-STEINBERG", "draw_image_scale2", half_photo, "palette64", "scale2", "floyd-steinberg", False),
    )
    for title, method, source_image, compression, profile, dither, lossless_rgb565 in cases:
        with Stage(report, title, f"profile={profile} dither={dither}") as stage:
            display.reset_tile_transfer_stats()
            started = time.monotonic()
            with display.frame(timeout_ms=9000):
                if method == "draw_image_scale2":
                    display.draw_image_scale2(source_image, 0, 0, compression=compression, dither=dither)
                else:
                    display.draw_image(source_image, 0, 0, compression=compression, tile_profile=profile, dither=dither)
            elapsed = time.monotonic() - started
            stats = display.tile_transfer_stats
            metadata = {
                "compression": compression,
                "profile": profile,
                "dither": dither,
                "packets": stats.packet_count,
                "wire_bytes": stats.wire_bytes,
                "elapsed_seconds": round(elapsed, 4),
            }
            if lossless_rgb565:
                actual_crc = display.canvas_crc32()
                if actual_crc != expected_rgb565_crc:
                    raise FunctionalTestError(
                        f"{title} canvas CRC mismatch: "
                        f"expected={expected_rgb565_crc:08X} actual={actual_crc:08X}"
                    )
                metadata["canvas_crc32"] = f"{actual_crc:08X}"
                metadata["exact_crc_verified"] = True
            else:
                # Palette modes are intentionally lossy. A source RGB565 canvas CRC is not
                # a valid expectation and must never be queried or compared here.
                metadata["visual_validation"] = f"lossy {compression} presentation"
                metadata["exact_crc_verified"] = False
                if dither == "floyd-steinberg":
                    metadata["dithered_rgb565_pixels_changed_vs_none"] = (
                        palette4_dithered_pixels if compression == "palette4" else palette64_dithered_pixels
                    )
            stage.set(**metadata)
            wait(display, hold)


def segmented_and_palette_stage(display: RemoteDisplay, hold: float, report: Report) -> None:
    """Exercise direct large-tile and Palette4 transfers in a bounded reference scene."""
    with Stage(report, "DIRECT TILE MODES", "large segmented RAW/RLE plus direct Palette4") as stage:
        raw_checker = checker_rgb565(45, 60)
        palette, indices = palette_tile()
        page = Rect(22, 24, 406, 552)
        header = Rect(40, 42, 370, 72)
        mode_row = Rect(40, 140, 370, 172)
        chart_card = Rect(40, 338, 370, 116)
        footer = Rect(40, 480, 370, 54)
        cards = mode_row.split_columns(3, gap=14)
        require_contained(header, page, "direct tile header")
        require_contained(mode_row, page, "direct tile mode row")
        require_contained(chart_card, page, "direct tile chart card")
        require_contained(footer, page, "direct tile footer")
        require_disjoint((("direct tile header", header), ("direct tile row", mode_row), ("direct tile chart", chart_card), ("direct tile footer", footer)))
        for index, card in enumerate(cards):
            require_interior_padding(card, mode_row, 0, f"direct tile card {index}")
        display.reset_tile_transfer_stats()
        with display.frame(timeout_ms=6000):
            display.clear(INK)
            display.fill_rect(page.x, page.y, page.width, page.height, PANEL)
            display.stroke_rect(page.x, page.y, page.width, page.height, CYAN, 2)
            display.fill_rect(header.x, header.y, header.width, header.height, PANEL_ALT)
            display.stroke_rect(header.x, header.y, header.width, header.height, CYAN, 1)
            display_text_box(display, Rect(header.x + 12, header.y + 10, header.width - 24, 28), "DIRECT TILE MODES", WHITE, font=FONT_22, align="center", valign="middle")
            display_text_box(display, Rect(header.x + 12, header.y + 42, header.width - 24, 18), "Raw, RLE, and Palette4 tile decode paths", MUTED, font=FONT_12, align="center", valign="middle")

            for card, label, color, mode in zip(cards, ("RAW", "RLE", "PALETTE4"), (CYAN, GREEN, ORANGE), ("raw", "rle", "palette")):
                display.fill_rect(card.x, card.y, card.width, card.height, INK)
                display.stroke_rect(card.x, card.y, card.width, card.height, color, 2)
                display_text_box(display, Rect(card.x + 6, card.y + 10, card.width - 12, 18), label, color, font=FONT_12, align="center", valign="middle")
                tile_x = card.x + (card.width - 45) // 2
                tile_y = card.y + 42
                if mode == "raw":
                    display.blit_rgb565(tile_x, tile_y, 45, 60, raw_checker, compression="raw")
                elif mode == "rle":
                    display.blit_rgb565(tile_x, tile_y, 45, 60, raw_checker, compression="rle")
                else:
                    display.blit_palette4(tile_x, tile_y, 45, 60, palette, indices)
                display_text_box(display, Rect(card.x + 8, card.y + 120, card.width - 16, 22), "45 x 60 tile", MUTED, font=FONT_12, align="center", valign="middle")

            display.fill_rect(chart_card.x, chart_card.y, chart_card.width, chart_card.height, PANEL_ALT)
            display.stroke_rect(chart_card.x, chart_card.y, chart_card.width, chart_card.height, GRID, 1)
            display_text_box(display, Rect(chart_card.x + 12, chart_card.y + 10, chart_card.width - 24, 18), "SEGMENTED TRANSPORT PATH", WHITE, font=FONT_12, align="center", valign="middle")
            graph = Rect(chart_card.x + 16, chart_card.y + 36, chart_card.width - 32, 60)
            display.stroke_rect(graph.x, graph.y, graph.width, graph.height, GRID, 1)
            for division in range(1, 3):
                y = graph.y + division * graph.height // 3
                display.line(graph.x + 1, y, graph.right - 2, y, GRID, 1)
            display.polyline(((graph.x + 10, graph.bottom - 12), (graph.x + 68, graph.y + 18), (graph.x + 126, graph.bottom - 20), (graph.x + 184, graph.y + 28), (graph.x + 242, graph.bottom - 16), (graph.right - 10, graph.y + 16)), VIOLET, 3)

            display.fill_rect(footer.x, footer.y, footer.width, footer.height, INK)
            display.stroke_rect(footer.x, footer.y, footer.width, footer.height, GRID, 1)
            display_text_box(display, Rect(footer.x + 12, footer.y + 8, footer.width - 24, 16), "Cyan and orange checker detail should remain distinct.", WHITE, font=FONT_12, align="center", valign="middle")
            display_text_box(display, Rect(footer.x + 12, footer.y + 28, footer.width - 24, 16), "The Palette4 tile uses local four-bit indices.", MUTED, font=FONT_12, align="center", valign="middle")
        transfer = display.tile_transfer_stats
        if transfer.segmented_tiles < 2:
            raise FunctionalTestError("large RAW/RLE tile test did not use staged transport")
        stage.set(segmented_tiles=transfer.segmented_tiles, direct_tiles=transfer.direct_tiles, wire_bytes=transfer.wire_bytes)
        wait(display, hold)


def resource_cache_stage(display: RemoteDisplay, photo: Image.Image, hold: float, report: Report) -> None:
    """Validate resource upload, replay, tint, release, and clear in one clean scene."""
    with Stage(report, "RESOURCE CACHE", "RGB565, Alpha8, Palette4 upload, replay, release, clear") as stage:
        display.clear_cached()
        cached_palette, cached_indices = palette_tile(40, 40)
        uploads = []
        try:
            uploads.append(display.cache_rgb565(0x2001, 45, 60, checker_rgb565(45, 60), compression="rle"))
            uploads.append(display.cache_rgb565(0x2002, 30, 40, solid_rgb565(30, 40, PANEL_ALT), compression="raw"))
            badge = alpha_badge(40, 40)
            uploads.append(display.cache_alpha(0x2003, 40, 40, badge, compression="raw"))
            uploads.append(display.cache_alpha(0x2004, 40, 40, badge, compression="rle"))
            uploads.append(display.cache_palette4(0x2005, 40, 40, cached_palette, cached_indices))
            cache_info = display.resource_cache_info()
            if cache_info.slot_used < 5:
                raise FunctionalTestError("cache did not report all uploaded resources")

            page = Rect(22, 24, 406, 552)
            header = Rect(40, 42, 370, 72)
            checker_row = Rect(40, 142, 370, 84)
            raw_row = Rect(40, 246, 370, 70)
            alpha_row = Rect(40, 336, 370, 74)
            palette_row = Rect(40, 430, 370, 66)
            footer = Rect(40, 516, 370, 34)
            require_disjoint((("cache header", header), ("cache checker", checker_row), ("cache raw", raw_row), ("cache alpha", alpha_row), ("cache palette", palette_row), ("cache footer", footer)))
            with display.frame(timeout_ms=6000):
                display.clear(INK)
                display.fill_rect(page.x, page.y, page.width, page.height, PANEL)
                display.stroke_rect(page.x, page.y, page.width, page.height, GREEN, 2)
                display.fill_rect(header.x, header.y, header.width, header.height, PANEL_ALT)
                display.stroke_rect(header.x, header.y, header.width, header.height, GREEN, 1)
                display_text_box(display, Rect(header.x + 12, header.y + 10, header.width - 24, 28), "RESOURCE CACHE", WHITE, font=FONT_22, align="center", valign="middle")
                display_text_box(display, Rect(header.x + 12, header.y + 42, header.width - 24, 18), "Upload once, then replay by resource ID", MUTED, font=FONT_12, align="center", valign="middle")

                for row, label, color in ((checker_row, "RGB565 RLE REPLAY", CYAN), (raw_row, "RGB565 RAW REPLAY", GREEN), (alpha_row, "ALPHA8 TINT REPLAY", YELLOW), (palette_row, "PALETTE4 REPLAY", ORANGE)):
                    display.fill_rect(row.x, row.y, row.width, row.height, INK)
                    display.stroke_rect(row.x, row.y, row.width, row.height, color, 1)
                    display_text_box(display, Rect(row.x + 8, row.y + 6, 132, 16), label, color, font=FONT_12, valign="middle")

                for x in (164, 214, 264, 314, 364):
                    display.draw_cached(0x2001, x, checker_row.y + 16)
                for x in (168, 218, 268, 318, 368):
                    display.draw_cached(0x2002, x, raw_row.y + 18)
                for x, color in ((166, CYAN), (216, GREEN), (266, YELLOW), (316, PINK)):
                    display.draw_cached(0x2003, x, alpha_row.y + 24, color)
                display.draw_cached(0x2004, 366, alpha_row.y + 24, WHITE)
                for x in (170, 218, 266, 314, 362):
                    display.draw_cached(0x2005, x, palette_row.y + 18)

                display.fill_rect(footer.x, footer.y, footer.width, footer.height, PANEL_ALT)
                display.stroke_rect(footer.x, footer.y, footer.width, footer.height, GRID, 1)
                display_text_box(display, Rect(footer.x + 10, footer.y + 3, footer.width - 20, 14), "Tintable Alpha8 and Palette4 resources", MUTED, font=FONT_12, align="center", valign="middle")
                display_text_box(display, Rect(footer.x + 10, footer.y + 17, footer.width - 20, 14), "replay from the session cache.", MUTED, font=FONT_12, align="center", valign="middle")
            stage.set(
                slots=cache_info.slot_used,
                cache_bytes=cache_info.byte_used,
                upload_bytes=sum(item.encoded_bytes for item in uploads),
                upload_packets=sum(item.packet_count for item in uploads),
            )
            wait(display, hold)
        finally:
            display.clear_cached()
        if display.resource_cache_info().slot_used != 0:
            raise FunctionalTestError("resource cache clear did not release all test resources")


def photo_overlay_stage(display: RemoteDisplay, photo: Image.Image, hold: float, report: Report) -> None:
    with Stage(report, "PHOTO + UI COMPOSITION", "Palette4 photo with bounded overlay regions") as stage:
        space = CoordinateSpace.design(1000, 1000)
        header = space.rect(0, 0, 1000, 124)
        footer = space.rect(40, 750, 920, 220)
        footer_controls = footer.inset((14, 14, 14, 14))
        buttons = Rect(footer_controls.x, footer_controls.y, 250, 42).split_columns(2, gap=14)
        checkbox_rect = Rect(footer_controls.x + 282, footer_controls.y, footer_controls.width - 282, 42)
        charts = Rect(footer_controls.x, footer_controls.y + 66, footer_controls.width, 42).split_columns(2, gap=18)
        require_disjoint((("photo header", header), ("photo footer", footer)))
        with display.frame(timeout_ms=9000):
            display.draw_image(photo, 0, 0, compression="palette4", tile_profile="medium", dither="floyd-steinberg")
            layout = Layout(display, space=CoordinateSpace.pixels())
            layout.fill(header, INK)
            display.fill_rect(0, header.bottom - 2, SCREEN_WIDTH, 2, CYAN)
            layout.text_box(Rect(18, 12, 250, 26), "REFERENCE IMAGE", WHITE, font=FONT_22, valign="middle", label="photo title")
            layout.text_box(Rect(18, 44, 360, 20), "Palette4 image with structured overlays", MUTED, font=FONT_14, valign="middle", label="photo subtitle")
            layout.fill(footer, INK)
            layout.stroke(footer, CYAN, 2)
            display.button(buttons[0].x, buttons[0].y, buttons[0].width, buttons[0].height, "OPEN", background=PANEL_ALT, border=CYAN, text_color=WHITE, font=FONT_14, font_size=14)
            display.button(buttons[1].x, buttons[1].y, buttons[1].width, buttons[1].height, "STATUS", background=PANEL_ALT, border=GREEN, text_color=WHITE, font=FONT_14, font_size=14)
            layout.checkbox(checkbox_rect, True, "LIVE", foreground=YELLOW, background=INK, font=FONT_14, label_name="photo live")
            display.line_chart(charts[0].x, charts[0].y, charts[0].width, charts[0].height, (28, 44, 37, 58, 51, 67, 60, 79), line_color=PINK, grid_color=GRID, background=PANEL)
            display.bar_chart(charts[1].x, charts[1].y, charts[1].width, charts[1].height, (15, 25, 19, 34, 26), bar_color=GREEN, grid_color=GRID, background=PANEL)
        stage.set(composition="Palette4 + bounded primitive, text, chart, and control overlays")
        wait(display, hold)


def motion_base(photo: Image.Image) -> tuple[Canvas, dict[str, Rect]]:
    geometry = motion_scene_geometry()
    canvas = Canvas.from_image(photo)
    header = geometry["header"]
    field = geometry["field"]
    footer = geometry["footer"]
    field_title = geometry["field_title"]
    footer_title = geometry["footer_title"]
    footer_caption = geometry["footer_caption"]

    canvas.fill_rect(header.x, header.y, header.width, header.height, INK)
    canvas.fill_rect(header.x, header.bottom - 2, header.width, 2, CYAN)
    canvas_text_box(canvas, header.inset((16, 10, 16, 32)), "DIRTY-TILE MOTION", WHITE, font=FONT_18, valign="middle")
    canvas_text_box(canvas, Rect(header.x + 16, header.y + 38, header.width - 32, 14), "Host-composited field preserves the photo under animation", MUTED, font=FONT_12, valign="middle")

    composite_translucent_panel(canvas, field, INK, 146)
    canvas.stroke_rect(field.x, field.y, field.width, field.height, CYAN, 2)
    canvas_text_box(canvas, field_title, "SEMI-TRANSPARENT BALL FIELD", WHITE, font=FONT_14, valign="middle")
    canvas_text_box(canvas, Rect(field.right - 170, field.y + 14, 154, 18), "PHOTO REMAINS VISIBLE", MUTED, font=FONT_12, align="right", valign="middle")
    for y in range(field.y + 56, field.bottom - 24, 48):
        canvas.line(field.x + 2, y, field.right - 3, y, rgb565(38, 78, 116), 1)
    for x in range(field.x + 48, field.right - 24, 58):
        canvas.line(x, field.y + 38, x, field.bottom - 3, rgb565(38, 78, 116), 1)

    canvas.fill_rect(footer.x, footer.y, footer.width, footer.height, INK)
    canvas.stroke_rect(footer.x, footer.y, footer.width, footer.height, GREEN, 2)
    canvas_text_box(canvas, footer_title, "BOUNCING BALL", WHITE, font=FONT_14, valign="middle")
    canvas.fill_rect(geometry["progress"].x, geometry["progress"].y, geometry["progress"].width, geometry["progress"].height, PANEL_ALT)
    canvas_text_box(canvas, footer_caption, "Photo field is restored before every dirty-tile frame.", MUTED, font=FONT_12, valign="middle")
    return canvas, geometry


def dirty_motion_stage(display: RemoteDisplay, photo: Image.Image, frames: int, report: Report) -> None:
    with Stage(report, "PHOTO + BOUNCING BALL", f"dirty tiles, translucent photo field, {frames} frames") as stage:
        base, geometry = motion_base(photo)
        presenter = DirtyTilePresenter(display, tile_profile="small", compression="auto")
        wires: list[int] = []
        elapsed: list[float] = []
        changed: list[int] = []
        last_bytes: bytes | None = None
        track = geometry["ball_track"]
        progress = geometry["progress"]
        radius = 18
        for index in range(frames):
            canvas = base.copy()
            phase = index / max(1, frames - 1)
            ball_x = track.x + radius + round((track.width - 2 * radius) * phase)
            arc = abs(math.sin(phase * math.pi * 3.3))
            ball_y = track.y + radius + round((track.height - 2 * radius) * arc)
            draw = ImageDraw.Draw(canvas.image)
            draw.ellipse((ball_x - radius, ball_y - radius, ball_x + radius, ball_y + radius), fill=(255, 85, 94), outline=(244, 248, 255), width=2)
            draw.line((ball_x - 24, ball_y, ball_x + 24, ball_y), fill=(255, 214, 76), width=2)
            draw.line((ball_x, ball_y - 24, ball_x, ball_y + 24), fill=(255, 214, 76), width=2)
            canvas.fill_rect(progress.x, progress.y, round(progress.width * phase), progress.height, GREEN)
            frame = canvas.rgb565_bytes()
            result = presenter.present(frame, timeout_ms=1800)
            wires.append(result.transfer.wire_bytes)
            elapsed.append(result.elapsed_seconds)
            changed.append(result.changed_tiles)
            last_bytes = frame
            target = (index + 1) / 30.0
            remaining = target - (time.monotonic() - stage.started)
            if remaining > 0:
                time.sleep(remaining)
        if last_bytes is None:
            raise FunctionalTestError("motion scene did not create a frame")
        no_change = presenter.present(last_bytes)
        empty = presenter.present(last_bytes, force_frame=True)
        if no_change.changed_tiles != 0 or no_change.frame_sent:
            raise FunctionalTestError("dirty-tile no-change detection failed")
        if not empty.frame_sent or empty.changed_tiles != 0:
            raise FunctionalTestError("empty frame transaction probe failed")
        stage.set(
            profile="small",
            field_opacity_percent=round(146 * 100 / 255),
            average_changed_tiles=round(statistics.mean(changed), 2),
            average_wire_bytes=round(statistics.mean(wires), 1),
            average_elapsed_ms=round(statistics.mean(elapsed) * 1000, 2),
            max_elapsed_ms=round(max(elapsed) * 1000, 2),
            no_change=True,
            empty_frame=True,
        )


def dashboard_base() -> tuple[Canvas, dict[str, Rect]]:
    geometry = dashboard_scene_geometry()
    canvas = Canvas(background=INK)
    header = geometry["header"]
    canvas.fill_rect(header.x, header.y, header.width, header.height, PANEL)
    canvas.stroke_rect(header.x, header.y, header.width, header.height, CYAN, 2)
    canvas_text_box(canvas, Rect(header.x + 18, header.y + 10, header.width - 36, 20), "SYSTEM DASHBOARD", WHITE, font=FONT_18, valign="middle")
    canvas_text_box(canvas, Rect(header.x + 18, header.y + 38, header.width - 36, 14), "Medium dirty tiles, bounded metric cards", MUTED, font=FONT_12, valign="middle")
    for card in (geometry["cpu_card"], geometry["memory_card"], geometry["network_card"]):
        canvas.fill_rect(card.x, card.y, card.width, card.height, PANEL)
        canvas.stroke_rect(card.x, card.y, card.width, card.height, GRID, 2)
    return canvas, geometry


def dashboard_stage(display: RemoteDisplay, frames: int, report: Report) -> None:
    with Stage(report, "DIRTY-TILE DASHBOARD", f"structured cards, live line/bar/pie charts, {frames} frames") as stage:
        base, geometry = dashboard_base()
        presenter = DirtyTilePresenter(display, tile_profile="medium", compression="auto")
        wires: list[int] = []
        elapsed: list[float] = []
        changed: list[int] = []
        cpu_card = geometry["cpu_card"]
        memory_card = geometry["memory_card"]
        network_card = geometry["network_card"]
        history_length = 32
        cpu_history = [52 + 24 * math.sin((sample - history_length + 1) / 12.0) for sample in range(history_length)]
        network_history = [44 + 22 * math.sin((sample - history_length + 1) / 15.0) for sample in range(history_length)]
        for index in range(frames):
            canvas = base.copy()
            phase = index / 15.0
            cpu = 52 + 33 * math.sin(phase)
            memory = 64 + 21 * math.sin(phase * 0.63 + 1.3)
            network_sample = 44 + 28 * math.sin(index / 10.0)
            cpu_history = cpu_history[1:] + [cpu]
            network_history = network_history[1:] + [network_sample]
            bars = [12 + 52 * abs(math.sin((index + i) / 11.0)) for i in range(8)]

            cpu_inner = cpu_card.inset(18)
            memory_inner = memory_card.inset(18)
            network_inner = network_card.inset(18)
            canvas_text_box(canvas, Rect(cpu_inner.x, cpu_inner.y, cpu_inner.width, 20), f"CPU  {cpu:05.1f}%", WHITE, font=FONT_16, valign="middle")
            cpu_meter = Rect(cpu_inner.x, cpu_inner.y + 38, cpu_inner.width, 14)
            canvas.fill_rect(cpu_meter.x, cpu_meter.y, cpu_meter.width, cpu_meter.height, rgb565(8, 14, 25))
            canvas.fill_rect(cpu_meter.x, cpu_meter.y, max(0, min(cpu_meter.width, round(cpu_meter.width * cpu / 100))), cpu_meter.height, CYAN)
            canvas.line_chart(cpu_inner.x, cpu_inner.y + 70, cpu_inner.width, cpu_inner.height - 70, cpu_history, line_color=CYAN, grid_color=GRID, background=PANEL, min_value=0, max_value=100)

            canvas_text_box(canvas, Rect(memory_inner.x, memory_inner.y, memory_inner.width, 20), f"MEM  {memory:05.1f}%", WHITE, font=FONT_16, valign="middle")
            memory_meter = Rect(memory_inner.x, memory_inner.y + 38, memory_inner.width, 14)
            canvas.fill_rect(memory_meter.x, memory_meter.y, memory_meter.width, memory_meter.height, rgb565(8, 14, 25))
            canvas.fill_rect(memory_meter.x, memory_meter.y, max(0, min(memory_meter.width, round(memory_meter.width * memory / 100))), memory_meter.height, GREEN)
            canvas.bar_chart(memory_inner.x, memory_inner.y + 70, memory_inner.width, memory_inner.height - 70, bars, bar_color=ORANGE, grid_color=GRID, background=PANEL)

            canvas_text_box(canvas, Rect(network_inner.x, network_inner.y, network_inner.width, 20), "NETWORK ACTIVITY", WHITE, font=FONT_16, valign="middle")
            graph_rect, pie_slot = Rect(network_inner.x, network_inner.y + 36, network_inner.width, network_inner.height - 36).split_columns(2, gap=18)
            canvas.line_chart(graph_rect.x, graph_rect.y, graph_rect.width, graph_rect.height, network_history, line_color=GREEN, grid_color=GRID, background=PANEL, min_value=0, max_value=100)
            pie_diameter = min(pie_slot.width, pie_slot.height - 22)
            pie_x = pie_slot.x + (pie_slot.width - pie_diameter) // 2
            canvas.pie_chart(pie_x, pie_slot.y, pie_diameter, (cpu, memory, 100 - cpu), (CYAN, GREEN, VIOLET), background=PANEL)
            canvas_text_box(canvas, Rect(pie_slot.x, pie_slot.bottom - 18, pie_slot.width, 16), "CPU / MEM / FREE", MUTED, font=FONT_12, align="center", valign="middle")

            result = presenter.present(canvas.rgb565_bytes(), timeout_ms=1800)
            wires.append(result.transfer.wire_bytes)
            elapsed.append(result.elapsed_seconds)
            changed.append(result.changed_tiles)
            target = (index + 1) / 30.0
            remaining = target - (time.monotonic() - stage.started)
            if remaining > 0:
                time.sleep(remaining)
        stage.set(
            profile="medium",
            coordinate_space="1000x1000 design grid",
            average_changed_tiles=round(statistics.mean(changed), 2),
            average_wire_bytes=round(statistics.mean(wires), 1),
            average_elapsed_ms=round(statistics.mean(elapsed) * 1000, 2),
            host_present_fps=round(1 / statistics.mean(elapsed), 2),
        )


def touch_base() -> Canvas:
    canvas = Canvas(background=INK)
    canvas.fill_rect(18, 18, 414, 564, PANEL)
    canvas.stroke_rect(18, 18, 414, 564, CYAN, 2)
    canvas_text_box(canvas, Rect(36, 36, 378, 24), "TOUCH LATENCY AND COMPOSITING", WHITE, font=FONT_18, valign="middle")
    canvas_text_box(canvas, Rect(36, 64, 378, 18), "The marker is composited over a fresh backing canvas.", MUTED, font=FONT_12, valign="middle")
    canvas.fill_rect(36, 116, 378, 376, rgb565(8, 14, 25))
    canvas.stroke_rect(36, 116, 378, 376, GRID, 1)
    for y in range(156, 490, 56):
        canvas.line(38, y, 412, y, GRID, 1)
    for x in range(76, 414, 56):
        canvas.line(x, 118, x, 490, GRID, 1)
    canvas.fill_rect(36, 516, 378, 46, PANEL_ALT)
    canvas.stroke_rect(36, 516, 378, 46, GRID, 1)
    return canvas


def touch_stage(display: RemoteDisplay, seconds: float, fps: float, report: Report) -> None:
    with Stage(report, "LOW-LATENCY TOUCH", f"drag for {seconds:.0f}s; latest-event presentation capped at {fps:.0f} FPS") as stage:
        base = touch_base()
        presenter = DirtyTilePresenter(display, tile_profile="small", compression="auto")
        presenter.present(base.rgb565_bytes(), timeout_ms=1800)
        latest = None
        event_count = 0
        presentation_count = 0
        latencies: list[float] = []
        next_present = 0.0
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            event = display.poll_latest_touch(timeout_ms=2)
            if event is not None:
                latest = event
                event_count += 1
            now = time.monotonic()
            if latest is None or now < next_present:
                continue
            next_present = now + 1.0 / fps
            canvas = base.copy()
            if latest.pressed:
                x = max(52, min(398, latest.x))
                y = max(132, min(476, latest.y))
                draw = ImageDraw.Draw(canvas.image)
                draw.ellipse((x - 11, y - 11, x + 11, y + 11), outline=(255, 214, 76), width=2)
                draw.line((x - 17, y, x + 17, y), fill=(255, 214, 76), width=1)
                draw.line((x, y - 17, x, y + 17), fill=(255, 214, 76), width=1)
                canvas_text_box(canvas, Rect(52, 526, 346, 22), f"X {latest.x:03d}   Y {latest.y:03d}   DOWN", WHITE, font=FONT_14, valign="middle")
            else:
                canvas_text_box(canvas, Rect(52, 526, 346, 22), "TOUCH RELEASED", WHITE, font=FONT_14, valign="middle")
            present_started = time.monotonic()
            presenter.present(canvas.rgb565_bytes(), timeout_ms=1600)
            latencies.append(time.monotonic() - present_started)
            presentation_count += 1
        stage.set(
            received_latest_events=event_count,
            presentations=presentation_count,
            average_present_ms=round(statistics.mean(latencies) * 1000, 2) if latencies else None,
            p95_present_ms=round(sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)] * 1000, 2) if latencies else None,
            max_present_ms=round(max(latencies) * 1000, 2) if latencies else None,
        )


def copy_scroll_scene() -> tuple[Canvas, Rect, Rect, Rect, tuple[int, int]]:
    """Build a three-state visual fixture for COPY_RECT and SCROLL_RECT."""
    canvas = Canvas(background=INK)
    card = Rect(18, 18, 414, 564)
    pane = Rect(42, 136, 366, 288)
    content = Rect(56, 178, 338, 224)
    source = Rect(76, 216, 104, 76)
    destination = (272, 304)
    destination_rect = Rect(destination[0], destination[1], source.width, source.height)

    for label, rect in (
        ("copy/scroll card", card),
        ("copy/scroll pane", pane),
        ("copy/scroll content", content),
        ("copy source", source),
        ("copy destination", destination_rect),
    ):
        require_on_canvas(rect, label)
    require_contained(content, pane, "copy/scroll content")
    if source.intersects(destination_rect):
        raise FunctionalTestError("copy source and destination must not overlap in the visual fixture")

    canvas.fill_rect(card.x, card.y, card.width, card.height, PANEL)
    canvas.stroke_rect(card.x, card.y, card.width, card.height, CYAN, 2)
    canvas_text_box(canvas, Rect(36, 36, 378, 30), "COPY_RECT / SCROLL_RECT", WHITE, font=FONT_22, align="center", valign="middle")
    canvas_text_box(
        canvas,
        Rect(36, 72, 378, 18),
        "Pico framebuffer operations shown as three separate views.",
        MUTED,
        font=FONT_12,
        align="center",
        valign="middle",
    )
    canvas_text_box(
        canvas,
        Rect(36, 98, 378, 16),
        "VIEW 1: INITIAL  |  VIEW 2: COPY  |  VIEW 3: SCROLL",
        CYAN,
        font=FONT_12,
        align="center",
        valign="middle",
    )

    canvas.fill_rect(pane.x, pane.y, pane.width, pane.height, rgb565(8, 14, 25))
    canvas.stroke_rect(pane.x, pane.y, pane.width, pane.height, GRID, 2)
    canvas_text_box(canvas, Rect(pane.x + 14, pane.y + 10, pane.width - 28, 16), "WORK AREA", WHITE, font=FONT_14, align="left", valign="middle")
    canvas_text_box(
        canvas,
        Rect(pane.x + 14, pane.y + 30, pane.width - 28, 14),
        "Inner rectangle scrolls. Outer frame stays fixed.",
        MUTED,
        font=FONT_12,
        align="left",
        valign="middle",
    )

    canvas.fill_rect(content.x, content.y, content.width, content.height, PANEL_ALT)
    canvas.stroke_rect(content.x, content.y, content.width, content.height, GRID, 1)
    for x in range(content.x + 22, content.right, 32):
        canvas.line(x, content.y, x, content.bottom - 1, GRID, 1)
    for y in range(content.y + 20, content.bottom, 32):
        canvas.line(content.x, y, content.right - 1, y, GRID, 1)

    canvas_text_box(canvas, Rect(source.x, source.y - 18, source.width, 16), "SOURCE A", CYAN, font=FONT_12, align="center", valign="middle")
    canvas_text_box(canvas, Rect(destination_rect.x, destination_rect.y - 18, destination_rect.width, 16), "TARGET B", PINK, font=FONT_12, align="center", valign="middle")
    canvas.fill_rect(source.x, source.y, source.width, source.height, rgb565(11, 25, 45))
    canvas.stroke_rect(source.x, source.y, source.width, source.height, CYAN, 3)
    canvas_text_box(canvas, Rect(source.x + 10, source.y + 7, source.width - 20, 16), "A: COPY", WHITE, font=FONT_12, align="center", valign="middle")
    canvas.fill_rect(source.x + 12, source.y + 28, 78, 10, YELLOW)
    canvas.fill_rect(source.x + 12, source.y + 44, 24, 20, CYAN)
    canvas.fill_rect(source.x + 42, source.y + 44, 48, 10, GREEN)
    canvas.fill_rect(source.x + 42, source.y + 58, 30, 6, ORANGE)

    canvas.fill_rect(destination_rect.x, destination_rect.y, destination_rect.width, destination_rect.height, rgb565(34, 18, 52))
    canvas.stroke_rect(destination_rect.x, destination_rect.y, destination_rect.width, destination_rect.height, PINK, 3)
    canvas_text_box(canvas, Rect(destination_rect.x + 10, destination_rect.y + 28, destination_rect.width - 20, 18), "EMPTY", PINK, font=FONT_12, align="center", valign="middle")

    arrow_y = content.y + 26
    canvas.line(source.right + 18, arrow_y, destination_rect.x - 18, arrow_y, YELLOW, 2)
    canvas.line(destination_rect.x - 18, arrow_y, destination_rect.x - 28, arrow_y - 7, YELLOW, 2)
    canvas.line(destination_rect.x - 18, arrow_y, destination_rect.x - 28, arrow_y + 7, YELLOW, 2)

    canvas.fill_rect(36, 450, 378, 82, PANEL_ALT)
    canvas.stroke_rect(36, 450, 378, 82, GRID, 1)
    canvas_text_box(canvas, Rect(50, 462, 350, 16), "VIEW 1: initial source and empty target", WHITE, font=FONT_14, align="left", valign="middle")
    canvas_text_box(canvas, Rect(50, 484, 350, 16), "VIEW 2: target becomes an exact source copy", GREEN, font=FONT_12, align="left", valign="middle")
    canvas_text_box(canvas, Rect(50, 506, 350, 16), "VIEW 3: work area scrolls up; new bottom rows clear", CYAN, font=FONT_12, align="left", valign="middle")
    return canvas, content, source, destination


def copy_scroll_stage(display: RemoteDisplay, hold: float, report: Report) -> None:
    """Show and CRC-verify COPY_RECT, then SCROLL_RECT, as distinct states."""
    with Stage(report, "COPY + SCROLL", "three held Pico framebuffer states with CRC after each operation") as stage:
        canvas, content, copy_source, copy_destination = copy_scroll_scene()

        initial = canvas.rgb565_bytes()
        with display.frame(timeout_ms=6000):
            display.draw_image(canvas.image, 0, 0, compression="rle", tile_profile="large")
        initial_expected_crc = crc32(initial)
        initial_actual_crc = display.canvas_crc32()
        if initial_actual_crc != initial_expected_crc:
            raise FunctionalTestError(
                f"COPY/SCROLL initial CRC mismatch: expected={initial_expected_crc:08X} actual={initial_actual_crc:08X}"
            )
        print("  showing view 1 of 3: initial layout", flush=True)
        wait(display, hold)

        canvas.copy_rect(
            copy_source.x,
            copy_source.y,
            copy_source.width,
            copy_source.height,
            copy_destination[0],
            copy_destination[1],
        )
        after_copy = canvas.rgb565_bytes()
        with display.frame(timeout_ms=4000):
            display.copy_rect(
                copy_source.x,
                copy_source.y,
                copy_source.width,
                copy_source.height,
                copy_destination[0],
                copy_destination[1],
            )
        copy_expected_crc = crc32(after_copy)
        copy_actual_crc = display.canvas_crc32()
        if copy_actual_crc != copy_expected_crc:
            raise FunctionalTestError(
                f"COPY_RECT CRC mismatch: expected={copy_expected_crc:08X} actual={copy_actual_crc:08X}"
            )
        print("  showing view 2 of 3: copied source at target", flush=True)
        wait(display, hold)

        scroll_delta_y = -48
        canvas.scroll_rect(content.x, content.y, content.width, content.height, 0, scroll_delta_y, PANEL_ALT)
        after_scroll = canvas.rgb565_bytes()
        with display.frame(timeout_ms=4000):
            display.scroll_rect(content.x, content.y, content.width, content.height, 0, scroll_delta_y, PANEL_ALT)
        scroll_expected_crc = crc32(after_scroll)
        scroll_actual_crc = display.canvas_crc32()
        if scroll_actual_crc != scroll_expected_crc:
            raise FunctionalTestError(
                f"SCROLL_RECT CRC mismatch: expected={scroll_expected_crc:08X} actual={scroll_actual_crc:08X}"
            )
        print("  showing view 3 of 3: work area scrolled upward", flush=True)
        wait(display, hold)

        stage.set(
            copy=f"{copy_source.width}x{copy_source.height}",
            scroll_region=f"{content.width}x{content.height}",
            scroll_delta_y=scroll_delta_y,
            initial_crc32=f"{initial_actual_crc:08X}",
            copy_crc32=f"{copy_actual_crc:08X}",
            scroll_crc32=f"{scroll_actual_crc:08X}",
            verified=True,
        )


def crc_diagnostic_stage(display: RemoteDisplay, hold: float, report: Report) -> None:
    with Stage(report, "CANVAS CRC DIAGNOSTIC", "host RGB565 canvas versus device framebuffer") as stage:
        geometry = crc_diagnostic_geometry()
        card = geometry["card"]
        title = geometry["title"]
        subtitle = geometry["subtitle"]
        line_chart = geometry["line_chart"]
        bar_chart = geometry["bar_chart"]
        pie_chart = geometry["pie_chart"]
        canvas = Canvas(background=INK)
        canvas.fill_rect(card.x, card.y, card.width, card.height, PANEL)
        canvas.stroke_rect(card.x, card.y, card.width, card.height, CYAN, 2)
        canvas_text_box(canvas, title, "CANVAS CRC DIAGNOSTIC", WHITE, font=FONT_22, align="center", valign="middle")
        canvas_text_box(canvas, subtitle, "The host and panel framebuffer should match exactly.", MUTED, font=FONT_12, align="center", valign="middle")
        canvas.line_chart(line_chart.x, line_chart.y, line_chart.width, line_chart.height, (18, 32, 26, 54, 41, 67, 58, 81), line_color=CYAN, grid_color=GRID, background=PANEL)
        canvas.bar_chart(bar_chart.x, bar_chart.y, bar_chart.width, bar_chart.height, (13, 31, 49, 35, 63, 55), bar_color=GREEN, grid_color=GRID, background=PANEL)
        canvas.pie_chart(pie_chart.x, pie_chart.y, pie_chart.width, (42, 31, 18, 9), (CYAN, GREEN, YELLOW, ORANGE), background=PANEL)
        expected = canvas.rgb565_bytes()
        presenter = DirtyTilePresenter(display, tile_profile="large", compression="auto")
        presenter.present(expected, timeout_ms=2200)
        actual = display.canvas_crc32()
        expected_crc = crc32(expected)
        if actual != expected_crc:
            raise FunctionalTestError(f"canvas CRC mismatch: expected={expected_crc:08X} actual={actual:08X}")
        wait(display, hold)
        stage.set(expected_crc32=f"{expected_crc:08X}", actual_crc32=f"{actual:08X}", verified=True)


def session_abort_stage(display: RemoteDisplay, report: Report) -> None:
    with Stage(report, "SESSION RECOVERY", "frame abort and idempotent HELLO") as stage:
        display.frame_begin()
        try:
            display.fill_rect(0, 0, 24, 24, RED)
        finally:
            display.frame_abort()
        info = display.hello(retries=3)
        payload = b"functional-test"
        if display.ping(payload) != payload:
            raise FunctionalTestError("PING/PONG mismatch after frame abort")
        stage.set(protocol=info.protocol_version, abort_recovery=True, ping=True)


def strict_crc_stage(report: Report, hold: float) -> None:
    with Stage(report, "OPTIONAL STRICT CRC", "packet CRC plus staged-tile content CRC") as stage:
        with RemoteDisplay.open(timeout_ms=1800, strict_packet_crc=True, strict_tile_crc=True) as display:
            require_capabilities(display, strict=True)
            raw = checker_rgb565(45, 60)
            expected = bytearray(solid_rgb565(SCREEN_WIDTH, SCREEN_HEIGHT, INK))
            for row in range(60):
                target = ((180 + row) * SCREEN_WIDTH + 202) * 2
                source = row * 45 * 2
                expected[target:target + 90] = raw[source:source + 90]
            with display.frame(timeout_ms=5000):
                display.clear(INK)
                display.blit_rgb565(202, 180, 45, 60, raw, compression="rle")
            actual = display.canvas_crc32()
            expected_crc = crc32(bytes(expected))
            if actual != expected_crc:
                raise FunctionalTestError("strict CRC staged tile did not match device canvas")
            if display.ping(b"strict") != b"strict":
                raise FunctionalTestError("strict CRC PING/PONG mismatch")
            wait(display, hold)
            stage.set(expected_crc32=f"{expected_crc:08X}", actual_crc32=f"{actual:08X}", strict_packet_crc=True, strict_tile_crc=True)


def final_screen(display: RemoteDisplay, hold: float, report: Report, brightness: int) -> None:
    with Stage(report, "FINAL STATUS", "reconnect and visually centered completion screen") as stage:
        geometry = final_screen_geometry()
        card = geometry["card"]
        title = geometry["title"]
        status = geometry["status"]
        divider = geometry["divider"]
        caption = geometry["caption"]
        display.set_brightness(brightness)
        with display.frame(timeout_ms=5000):
            display.clear(INK)
            display.fill_rect(card.x, card.y, card.width, card.height, PANEL)
            display.stroke_rect(card.x, card.y, card.width, card.height, GREEN, 3)
            display.fill_rect(divider.x, divider.y, divider.width, divider.height, GRID)
            title_rect = display_text_box(display, title, "FUNCTIONAL TEST", WHITE, font=FONT_28, align="center", valign="middle")
            status_rect = display_text_box(display, status, "COMPLETE", GREEN, font=FONT_42, align="center", valign="middle")
            caption_rect = display_text_box(
                display,
                caption,
                "See terminal output and JSON report for details.",
                MUTED,
                font=FONT_14,
                align="center",
                valign="middle",
            )
        if display.ping(b"final") != b"final":
            raise FunctionalTestError("PING/PONG mismatch on final connection")
        wait(display, hold)
        stage.set(
            reconnected=True,
            restored_brightness=brightness,
            title_bounds=asdict(title_rect),
            status_bounds=asdict(status_rect),
            caption_bounds=asdict(caption_rect),
            visual_centering=True,
        )


def write_report(report: Report, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "library_protocol": report.library_protocol,
        "started_utc": report.started_utc,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stages": [asdict(stage) for stage in report.stages],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nJSON report: {path}")


def main() -> int:
    args = parse_args()
    design_preflight()
    photo = load_photo()
    palette4_dithered_pixels = palette4_dither_preflight(photo)
    palette64_dithered_pixels = palette64_dither_preflight(photo)
    if args.preflight_only:
        print(
            "Static layout and palette dither preflight completed successfully "
            f"(Palette4: {palette4_dithered_pixels}; Palette64: {palette64_dithered_pixels} "
            "RGB565 pixels differ from no-dither)."
        )
        return 0
    report = Report()
    report_path = args.report or ROOT / "reports" / f"functional_test_{time.strftime('%Y%m%d_%H%M%S')}.json"

    print("RP2350 Remote Display Python Library Functional Test")
    print(f"Project release: {PROJECT_VERSION}; library protocol: {PROTOCOL_VERSION}; test image: {ASSET_PATH.name}")

    with RemoteDisplay.open(timeout_ms=1800) as display:
        require_capabilities(display)
        assert display.info is not None
        print(f"Connected: {display.info}")
        session_abort_stage(display, report)
        with Stage(report, "CONNECTION + CAPABILITIES", "HELLO, geometry, tile profiles, PING/PONG") as stage:
            if display.ping(b"library-functional-test") != b"library-functional-test":
                raise FunctionalTestError("initial PING/PONG mismatch")
            stage.set(
                protocol=display.info.protocol_version,
                width=display.info.width,
                height=display.info.height,
                capabilities=f"0x{display.info.capabilities:08X}",
                small=f"{display.info.small_tile_width}x{display.info.small_tile_height}",
                medium=f"{display.info.medium_tile_width}x{display.info.medium_tile_height}",
                large=f"{display.info.large_tile_width}x{display.info.large_tile_height}",
            )
        with Stage(report, "BRIGHTNESS", "8%, 35%, 70%, 100%") as stage:
            card = Rect(54, 134, 342, 326)
            title = Rect(card.x + 24, card.y + 44, card.width - 48, 42)
            value = Rect(card.x + 24, card.y + 108, card.width - 48, 64)
            meter_label = Rect(card.x + 24, card.y + 204, card.width - 48, 18)
            meter = Rect(card.x + 24, card.y + 234, card.width - 48, 20)
            require_disjoint((("brightness title", title), ("brightness value", value), ("brightness label", meter_label), ("brightness meter", meter)))
            for percent in (8, 35, 70, 100):
                display.set_brightness(percent)
                with display.frame(timeout_ms=3000):
                    display.clear(INK)
                    display.fill_rect(card.x, card.y, card.width, card.height, PANEL)
                    display.stroke_rect(card.x, card.y, card.width, card.height, CYAN, 2)
                    display_text_box(display, title, "BRIGHTNESS", WHITE, font=FONT_28, align="center", valign="middle")
                    display_text_box(display, value, f"{percent}%", CYAN, font=FONT_42, align="center", valign="middle")
                    display_text_box(display, meter_label, "PANEL OUTPUT", MUTED, font=FONT_12, align="center", valign="middle")
                    display.fill_rect(meter.x, meter.y, meter.width, meter.height, PANEL_ALT)
                    display.stroke_rect(meter.x, meter.y, meter.width, meter.height, GRID, 1)
                    display.fill_rect(meter.x, meter.y, meter.width * percent // 100, meter.height, GREEN)
                # Brightness is a dynamic calibration sweep, not a static scene.
                wait(display, min(args.hold_seconds, 0.45))
            stage.set(percentages=[8, 35, 70, 100])
        device_text_stage(display, args.hold_seconds, report)
        direct_primitives_stage(display, args.hold_seconds, report)
        coordinate_reference_stage(display, args.hold_seconds, report)
        debug_overlay_stage(display, args.hold_seconds, report)
        image_modes_stage(
            display,
            photo,
            args.hold_seconds,
            report,
            palette4_dithered_pixels,
            palette64_dithered_pixels,
        )
        segmented_and_palette_stage(display, args.hold_seconds, report)
        resource_cache_stage(display, photo, args.hold_seconds, report)
        photo_overlay_stage(display, photo, args.hold_seconds, report)
        copy_scroll_stage(display, args.hold_seconds, report)
        dirty_motion_stage(display, photo, args.ball_frames, report)
        dashboard_stage(display, args.dashboard_frames, report)
        if not args.skip_touch:
            touch_stage(display, args.touch_seconds, args.touch_fps, report)
        crc_diagnostic_stage(display, args.hold_seconds, report)

    if not args.skip_strict_crc:
        strict_crc_stage(report, args.hold_seconds)

    with RemoteDisplay.open(timeout_ms=1800) as display:
        require_capabilities(display)
        final_screen(display, args.hold_seconds, report, args.brightness)

    write_report(report, report_path)
    print("\nFunctional test completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nFunctional test interrupted.", file=sys.stderr)
        raise SystemExit(130)
