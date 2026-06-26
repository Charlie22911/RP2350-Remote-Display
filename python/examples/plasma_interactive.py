#!/usr/bin/env python3
"""Interactive plasma benchmark with live full-res or half-res scale2 output."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageChops


WIDTH: Final = 450
HEIGHT: Final = 600
HALF_WIDTH: Final = WIDTH // 2
HALF_HEIGHT: Final = HEIGHT // 2
TILE_PROFILE: Final = "medium"
X_CYCLES: Final = 2
Y_CYCLES: Final = 3
DIAGONAL_X_CYCLES: Final = 2
DIAGONAL_Y_CYCLES: Final = 3
RADIAL_WAVELENGTH: Final = 145.0

# Fewer spatial cycles make the plasma forms larger. The colour stops are
# deliberately muted and cycle back to deep blue-black so the animation keeps
# dark regions and contrast without hard palette edges.
PLASMA_COLOR_STOPS: Final = (
    (4, 7, 16),
    (10, 22, 42),
    (25, 59, 75),
    (60, 98, 102),
    (108, 124, 113),
    (146, 127, 96),
    (174, 110, 83),
    (107, 66, 91),
    (28, 25, 53),
    (4, 7, 16),
)

MODE_BY_KEY: Final = {
    "1": "raw",
    "2": "rle",
    "3": "palette4",
    "4": "palette64",
}
MODE_LABELS: Final = {
    "raw": "RGB565 RAW",
    "rle": "RGB565 RLE",
    "palette4": "PALETTE4",
    "palette64": "PALETTE64",
}


@dataclass
class RateWindow:
    frames: int = 0
    wire_bytes: int = 0
    render_seconds: float = 0.0
    transfer_seconds: float = 0.0
    started_at: float = 0.0

    def reset(self) -> None:
        self.frames = 0
        self.wire_bytes = 0
        self.render_seconds = 0.0
        self.transfer_seconds = 0.0
        self.started_at = time.monotonic()


class TerminalKeys:
    """Nonblocking single-key reader bound to the controlling terminal.

    Opening /dev/tty keeps controls usable when the launcher is started from a
    pasted heredoc, where standard input is the heredoc instead of the terminal.
    """

    def __init__(self) -> None:
        try:
            self._fd = os.open("/dev/tty", os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            raise RuntimeError("interactive controls require a controlling terminal") from exc
        self._saved = None
        self._saved_flags: bool | None = None

    def __enter__(self) -> "TerminalKeys":
        self._saved = termios.tcgetattr(self._fd)
        self._saved_flags = os.get_blocking(self._fd)
        tty.setcbreak(self._fd)
        os.set_blocking(self._fd, False)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if self._saved is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            if self._saved_flags is not None:
                os.set_blocking(self._fd, self._saved_flags)
        finally:
            os.close(self._fd)

    def read(self) -> str:
        try:
            data = os.read(self._fd, 64)
        except BlockingIOError:
            return ""
        return data.decode("utf-8", errors="ignore")


class PlasmaRenderer:
    """Fast plasma generator built from Pillow operations implemented in C."""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT) -> None:
        self.width = width
        self.height = height
        self._field_x = self._make_field_x()
        self._field_y = self._make_field_y()
        self._field_diagonal = self._make_field_diagonal()
        self._field_radial = self._make_field_radial()
        self._color_lut = self._make_color_lut()

    def _make_field_x(self) -> Image.Image:
        row = bytes(
            int(127.5 + 127.5 * math.sin((x / self.width) * math.tau * X_CYCLES))
            for x in range(self.width)
        )
        return Image.frombytes("L", (self.width, self.height), row * self.height)

    def _make_field_y(self) -> Image.Image:
        values = bytearray(self.width * self.height)
        offset = 0
        for y in range(self.height):
            value = int(127.5 + 127.5 * math.sin((y / self.height) * math.tau * Y_CYCLES))
            values[offset:offset + self.width] = bytes((value,)) * self.width
            offset += self.width
        return Image.frombytes("L", (self.width, self.height), bytes(values))

    def _make_field_diagonal(self) -> Image.Image:
        values = bytearray(self.width * self.height)
        offset = 0
        for y in range(self.height):
            y_phase = DIAGONAL_Y_CYCLES * y / self.height
            for x in range(self.width):
                values[offset + x] = int(127.5 + 127.5 * math.sin(math.tau * (DIAGONAL_X_CYCLES * x / self.width + y_phase)))
            offset += self.width
        return Image.frombytes("L", (self.width, self.height), bytes(values))

    def _make_field_radial(self) -> Image.Image:
        values = bytearray(self.width * self.height)
        cx = self.width / 2.0
        cy = self.height / 2.0
        offset = 0
        scale = math.tau / RADIAL_WAVELENGTH
        for y in range(self.height):
            dy = y - cy
            for x in range(self.width):
                distance = math.hypot(x - cx, dy)
                values[offset + x] = int(127.5 + 127.5 * math.sin(distance * scale))
            offset += self.width
        return Image.frombytes("L", (self.width, self.height), bytes(values))

    @staticmethod
    def _make_color_lut() -> list[int]:
        red: list[int] = []
        green: list[int] = []
        blue: list[int] = []
        segment_count = len(PLASMA_COLOR_STOPS) - 1

        for value in range(256):
            position = value * segment_count / 255.0
            segment = min(int(position), segment_count - 1)
            fraction = position - segment
            start = PLASMA_COLOR_STOPS[segment]
            end = PLASMA_COLOR_STOPS[segment + 1]
            red.append(round(start[0] + (end[0] - start[0]) * fraction))
            green.append(round(start[1] + (end[1] - start[1]) * fraction))
            blue.append(round(start[2] + (end[2] - start[2]) * fraction))

        return red + green + blue

    def render(self, frame_index: int) -> Image.Image:
        a = ImageChops.offset(self._field_x, (frame_index * 3) % self.width, 0)
        b = ImageChops.offset(self._field_y, 0, (frame_index * 2) % self.height)
        c = ImageChops.offset(
            self._field_diagonal,
            (frame_index * 2) % self.width,
            (frame_index * 3) % self.height,
        )
        d = self._field_radial
        plasma = ImageChops.add_modulo(ImageChops.add_modulo(a, b), ImageChops.add_modulo(c, d))
        return plasma.point(self._color_lut, "RGB")


def dither_label(mode: str, enabled: bool) -> str:
    if mode not in {"palette4", "palette64"}:
        return "n/a"
    return "floyd-steinberg" if enabled else "none"


def resolution_label(half_resolution: bool) -> str:
    return "half/scale2" if half_resolution else "full"


def show_help() -> None:
    print(
        "\nControls:\n"
        "  [1] RGB565 RAW       [2] RGB565 RLE\n"
        "  [3] Palette4         [4] Palette64\n"
        "  [d] toggle dithering [h] toggle half-resolution scale2\n"
        "  [?] show controls    [q] quit\n",
        flush=True,
    )


def render_preview(output: Path, frame_index: int) -> None:
    renderer = PlasmaRenderer()
    renderer.render(frame_index).save(output)
    print(f"Wrote preview: {output}")


def run_interactive(initial_mode: str, dither_enabled: bool, half_resolution: bool) -> int:
    from rp2350_remote_display import RemoteDisplay, RemoteDisplayError

    full_renderer = PlasmaRenderer(WIDTH, HEIGHT)
    half_renderer = PlasmaRenderer(HALF_WIDTH, HALF_HEIGHT)
    mode = initial_mode
    frame_index = 0
    rate = RateWindow()
    rate.reset()

    with RemoteDisplay.open(timeout_ms=8000) as display, TerminalKeys() as keys:
        print(
            f"Connected {display.info.width}x{display.info.height}; tile profile {TILE_PROFILE}; "
            f"initial resolution mode: {resolution_label(half_resolution)}.",
            flush=True,
        )
        show_help()
        while True:
            for key in keys.read().lower():
                if key in MODE_BY_KEY:
                    mode = MODE_BY_KEY[key]
                    rate.reset()
                elif key == "d":
                    dither_enabled = not dither_enabled
                    rate.reset()
                elif key == "h":
                    half_resolution = not half_resolution
                    rate.reset()
                    print(f"\nResolution mode: {resolution_label(half_resolution)}", flush=True)
                elif key in {"q", "\x03"}:
                    print("\nStopped.", flush=True)
                    return 0
                elif key == "?":
                    show_help()

            render_started = time.perf_counter()
            if half_resolution:
                image = half_renderer.render(frame_index)
            else:
                image = full_renderer.render(frame_index)
            render_seconds = time.perf_counter() - render_started

            display.reset_tile_transfer_stats()
            transfer_started = time.perf_counter()
            try:
                with display.frame(timeout_ms=8000):
                    if half_resolution:
                        display.draw_image_scale2(
                            image,
                            0,
                            0,
                            compression=mode,
                            dither=dither_label(mode, dither_enabled),
                        )
                    else:
                        display.draw_image(
                            image,
                            0,
                            0,
                            compression=mode,
                            tile_profile=TILE_PROFILE,
                            dither=dither_label(mode, dither_enabled),
                        )
            except RemoteDisplayError as exc:
                print(f"\nDisplay transfer failed: {exc}", file=sys.stderr, flush=True)
                return 2
            transfer_seconds = time.perf_counter() - transfer_started
            stats = display.tile_transfer_stats

            rate.frames += 1
            rate.wire_bytes += stats.wire_bytes
            rate.render_seconds += render_seconds
            rate.transfer_seconds += transfer_seconds
            frame_index = (frame_index + 1) & 0x7FFFFFFF

            now = time.monotonic()
            elapsed = now - rate.started_at
            if elapsed >= 0.5:
                fps = rate.frames / elapsed
                mib_s = rate.wire_bytes / elapsed / (1024 * 1024)
                avg_render_ms = rate.render_seconds * 1000.0 / rate.frames
                avg_transfer_ms = rate.transfer_seconds * 1000.0 / rate.frames
                print(
                    "\r"
                    f"{MODE_LABELS[mode]:<12}  res={resolution_label(half_resolution):<11}  "
                    f"dither={dither_label(mode, dither_enabled):<15}  "
                    f"{fps:5.2f} FPS  {mib_s:5.2f} MiB/s  "
                    f"render={avg_render_ms:5.1f} ms  transfer={avg_transfer_ms:5.1f} ms  "
                    "[1-4 d h ? q]",
                    end="",
                    flush=True,
                )
                rate.reset()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("raw", "rle", "palette4", "palette64"),
        default="raw",
        help="initial transfer mode",
    )
    parser.add_argument(
        "--dither",
        action="store_true",
        help="enable Floyd-Steinberg dithering for Palette4 and Palette64",
    )
    parser.add_argument(
        "--half-resolution",
        action="store_true",
        help="start in half-resolution scale2 mode",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        metavar="PNG",
        help="render one frame to a PNG without opening the display",
    )
    parser.add_argument(
        "--preview-frame",
        type=int,
        default=0,
        help="frame number used with --preview",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.preview is not None:
        render_preview(args.preview, args.preview_frame)
        return 0
    return run_interactive(args.mode, args.dither, args.half_resolution)


if __name__ == "__main__":
    raise SystemExit(main())
