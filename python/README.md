# Python library

`rp2350-remote-display` is the Linux host library for RP2350 Remote Display. It opens the board over USB, checks protocol compatibility, sends drawing commands, receives touch events, and provides helpers for images, text, caching, dirty updates, layout, diagnostics, and RTC access.

This checkout packages release **1.2.16** of the project and Python library. It requires firmware release **1.2.16**, which speaks USB **protocol 16**.

## Requirements

- Python 3.10 or newer.
- A board running compatible firmware.
- PyUSB and a system libusb backend.
- Linux USB permission to claim the vendor interface.

## Install from this repository

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./python"
```

For development dependencies and tests:

```bash
python -m pip install -e "./python[dev]"
python -m pytest python/tests
```

Install Linux USB access rules once per host:

```bash
./python/scripts/install_linux_udev_rule.sh
```

Log out and back in, then reconnect the board. The default development firmware uses `CAFE:4010`.

## Minimal application

```python
from rp2350_remote_display import RemoteDisplay, rgb565

BLACK = rgb565(0, 0, 0)
BLUE = rgb565(45, 110, 255)
WHITE = rgb565(255, 255, 255)

with RemoteDisplay.open() as display:
    display.set_brightness(65)

    with display.frame():
        display.clear(BLACK)
        display.fill_rect(24, 24, 402, 96, BLUE)
        display.draw_text("Hello, RP2350", 48, 62, WHITE, size=22)
```

Drawing methods run inside `display.frame()`. Connection, brightness, cache management, RTC operations, device-font inspection, and diagnostics run outside a frame.

## API overview

| Area | Main API |
|---|---|
| Connection | `RemoteDisplay.open()`, `ping()`, `DisplayInfo` |
| Frames and primitives | `frame()`, `clear()`, `fill_rect()`, `stroke_rect()`, `line()`, `polyline()` |
| Images | `draw_image()`, `blit_rgb565()`, `blit_alpha()`, `blit_palette4()`, `blit_palette64()` |
| Half-resolution image transport | `draw_image_scale2()`, `blit_rgb565_scale2()`, `blit_palette4_scale2()`, `blit_palette64_scale2()` |
| Text | `draw_text()`, `draw_text_box()`, `draw_device_text()`, `measure_device_text()` |
| Reused images | `cache_rgb565()`, `cache_alpha()`, `cache_palette4()`, `draw_cached()` |
| Pico-rendered live UI | primitives, `draw_device_text()`, `scroll_rect()` |
| Host-rendered canvas updates | `Canvas`, `DirtyTilePresenter` |
| Framebuffer movement | `copy_rect()`, `scroll_rect()` |
| Touch | `poll_events()`, `poll_latest_touch()`, `wait_for_touch()` |
| Diagnostics | `canvas_crc32()`, `tile_transfer_stats` |
| RTC | `read_rtc()`, `set_rtc()`, `sync_rtc_from_ntp()` |

The exported `rgb565()` helper converts 8-bit RGB components to the 16-bit display format.

## Rendering terminology

The **host** is the Linux computer running this Python library. The **Pico** is the RP2350 board and the firmware running on it. The distinction matters because both machines can participate in producing a visible screen.

- **Host rendering** means Python generates final image pixels or an Alpha8 text mask, then transfers those pixels to the Pico. `draw_image()`, `draw_text()`, `Canvas`, and `DirtyTilePresenter` use host rendering. The Pico writes the received pixels into its framebuffer.
- **Pico rendering** means Python sends compact drawing commands and the Pico firmware produces the pixels locally. `clear()`, `fill_rect()`, `stroke_rect()`, `line()`, `polyline()`, `draw_device_text()`, `draw_cached()`, `copy_rect()`, and `scroll_rect()` use Pico rendering.
- **Pico-rendered text** is specifically `draw_device_text()`. It uses the Pico firmware's resident 8×16 bitmap font. The older API term **device text** refers to this same Pico-rendered path.

The Pico keeps the resulting framebuffer pixels after a frame ends. It does not keep a display list of commands. Draw static Pico-rendered content once, then send only commands for areas that actually change.

## Image modes and rendering choices

| Mode | Suitable use |
|---|---|
| RGB565 RAW | Exact full-color image data |
| RGB565 RLE | Flat graphics, repeated pixels, and simple UI art |
| RGB565 auto | Per-tile RAW or RLE selection |
| Alpha8 | Tinted masks and host-rendered text |
| Palette4 | Lower-bandwidth artwork that tolerates limited color detail |
| Palette64 | Better palette fidelity with lower bandwidth than RGB565 |
| Scale2 | Animated 225×300 source background expanded to 450×600 |

Palette4 and Palette64 are visually lossy. Their optional Floyd-Steinberg dithering changes source-to-palette mapping on the host. Use RGB565 when every output pixel must match the source.

Scale2 uses 2× nearest-neighbor expansion. Draw a changing Scale2 background first, then redraw full-resolution overlays that overlap it. Scale2 source tiles are direct transfers and cannot use the cache or `DirtyTilePresenter`.

For a live dashboard or control UI made from text, lines, and bounded panels, prefer **Pico rendering** with primitives plus `draw_device_text()`. Draw static walls and labels once, clear only declared value rectangles, and use `scroll_rect()` for graph interiors.

For frequently changing full-resolution pixels that the host must compose, use **host rendering** with `Canvas` plus `DirtyTilePresenter`. Use `region_mode="rect"` when small, sparse changes benefit from tighter lossless RGB565 rectangles. Tile profiles are 18×24, 30×40, and 45×60 pixels.

## Resource cache

The session-local resource cache is suited to repeated full-resolution icons, masks, sprites, and small panels. Upload a resource outside a frame with `cache_rgb565()`, `cache_alpha()`, or `cache_palette4()`, then replay it inside a frame with `draw_cached()`. A firmware reset or a new USB session clears the cache, so applications must upload their resources again.

The cache holds up to 64 resources and 256 KiB of combined encoded data. Use `resource_cache_info()` to inspect usage and `release_cached()` or `clear_cached()` to reclaim space. Scale2 transfers cannot use the cache.

## Canvas and dirty updates

`DirtyTilePresenter` compares each full-resolution RGB565 canvas with the preceding host-rendered canvas. Its first `present()` transfers the complete canvas; later calls transfer only changed tiles or changed rectangles. It does not infer framebuffer changes made through Pico-rendering commands.

Call `presenter.reset()` after any Pico framebuffer update that did not come from that presenter, including direct drawing frames, Scale2 updates, cached-resource draws, `copy_rect()`, and `scroll_rect()`. The next `present()` then sends the complete host-rendered canvas and restores the presenter's baseline.

## Pico-rendered text

`draw_text()` uses **host rendering**: Python rasterizes a host font into Alpha8 tiles and transfers the mask. `draw_device_text()` uses **Pico rendering**: the firmware draws UTF-8 with its resident Unifont grid. The API and protocol call this feature device text, but it is Pico-rendered text in this guide. Use it when an application needs firmware-provided glyph metrics and compact UTF-8 drawing without transferring a mask.

The built-in font uses an 8×16 base cell, with integer scales from 1 through 4. Most glyphs occupy one cell; full-width glyphs occupy two. `measure_device_text()` returns the exact result for mixed-width text. Newline starts at the original X position, tab advances to a four-cell stop, and unsupported code points render as `?`.

Query `device_font_info()` and `measure_device_text()` outside a frame before building layouts that depend on cell geometry.

## Pico-rendered dashboard

`examples/dirty_dashboard.py` is a Linux system-monitor example that uses **Pico rendering** almost exclusively. The host samples metrics and calculates graph points; the Pico draws primitives and its resident 8×16 font into the framebuffer. It uses touch hitboxes, bounded text-clear rectangles, and `scroll_rect()` for graph updates. Static panel walls and labels remain in the framebuffer; ordinary updates send only changed text, graph movement, and new trace segments.

At startup, the terminal menu selects the network interface, disk, target update rate from 1 through 15 FPS, and a 10 through 60 second history window. While it is running, type `m` and press Enter to reopen settings, `s` to print the active monitor settings, or `q` to exit. Tap a card for its fullscreen graph and tap the right-aligned Back button to return. Disk temperature is shown only when `smartctl` can retrieve it.

## Pico framebuffer copy and scroll

`copy_rect()` and `scroll_rect()` are **Pico-rendering** operations that move existing RGB565 pixels inside the Pico framebuffer and run inside `display.frame()`. Overlapping `copy_rect()` operations are safe. Positive scroll X moves pixels right, positive scroll Y moves pixels down, and `fill_color` fills newly exposed pixels.

```python
with display.frame():
    display.scroll_rect(24, 120, 360, 300, delta_x=0, delta_y=-16, fill_color=0x0000)
```

Mirror these operations with `Canvas.copy_rect()` or `Canvas.scroll_rect()` when a host `Canvas` must remain an exact model of the device framebuffer. Reset any associated `DirtyTilePresenter` before presenting the canvas again.

## Touch and RTC

Touch events report panel coordinates with a top-left origin. The firmware coalesces move events so `poll_latest_touch()` is appropriate for drag feedback.

RTC values are timezone-aware UTC. `sync_rtc_from_ntp()` performs one unauthenticated SNTP request from the host, writes the resulting UTC value to the board, and reads it back. It does not set the Linux system clock. Check `RtcReading.oscillator_valid` after a power-loss event.

## Examples

Run examples from the repository root after activating the virtual environment. The examples are intentionally small, each demonstrating one rendering or device-management decision.

| Example | What it does | Why it matters |
|---|---|---|
| `examples/basic_primitives.py` | Draws a panel, border, accent bar, button, and **host-rendered** Alpha8 text with direct primitive commands. | Establishes the simplest frame workflow and shows that primitives can be Pico-rendered while `draw_text()` remains host-rendered. |
| `examples/device_text.py` | Draws a compact status panel with `draw_device_text()` and the Pico's resident 8×16 font. | Shows the Pico-rendered text path, fixed cell geometry, and compact UTF-8 commands without Alpha8 mask transfers. |
| `examples/graphics_modes.py` | Presents the same generated artwork with RGB565 RAW, RGB565 RLE, Palette4, and dithered Palette4. | Makes the bandwidth-versus-image-quality tradeoff visible instead of theoretical. |
| `examples/plasma_interactive.py` | Animates a generated plasma effect and lets the operator compare full-resolution transfer with Scale2 and palette choices. | Measures actual host, USB, framebuffer, and panel performance on the connected system. Run `./python/examples/run_plasma_interactive.sh`. |
| `examples/dirty_dashboard.py` | Samples Linux CPU, memory, disk, and network metrics; the host calculates values and graph points while the Pico renders the UI, device text, touch navigation, and scrolling plots. | Reference implementation for an efficient live UI: static Pico-rendered layout once, bounded clears for changing text, and `scroll_rect()` for graph history. |
| `examples/resource_cache.py` | Uploads one RGB565 icon into the Pico resource cache, then replays it many times. | Shows when a repeated image should be transferred once and drawn locally thereafter. |
| `examples/scrolling_log.py` | Draws Pico-rendered log lines, then scrolls the existing framebuffer region before adding the next line. | Demonstrates that moving existing Pico framebuffer pixels avoids retransmitting unchanged log content. |
| `examples/touch_canvas.py` | Reads touch events and overlays a marker by composing a fresh **host-rendered** `Canvas` for each update. | Shows the contrasting dirty-tile path, where the host owns the full pixel model and `DirtyTilePresenter` transfers only changes. |
| `examples/layout_debug.py` | Renders design-space coordinates, widget bounds, text boxes, chart helpers, and tile boundaries. | Helps validate coordinate transforms and inspect why a host-rendered or Pico-rendered layout lands where it does. |
| `examples/rtc_sync.py` | Reads the board RTC or performs one host-side NTP query and writes the resulting UTC time to the board. | Keeps time synchronization explicit: it updates the Pico RTC, not the Linux system clock. Run `./python/examples/run_rtc_sync.sh` for the interactive wrapper. |

## Related documentation

- [User guide](../docs/README.md)
- [Protocol reference](../docs/protocol.md)
- [Testing guide](../docs/testing.md)
- [Troubleshooting](../docs/troubleshooting.md)

## License

MIT. See [LICENSE](LICENSE).
