# User guide

## What this project does

RP2350 Remote Display turns the Waveshare RP2350 Touch AMOLED 2.41 board into a USB-attached display endpoint for a Linux application. The host sends drawing commands and image data. The firmware manages the panel, a 450×600 RGB565 framebuffer, touch events, and the PCF85063 RTC.

The board has no application-specific shell or window system. Your host application owns the full display area.

## Hardware and host requirements

Supported hardware:

- Waveshare RP2350 Touch AMOLED 2.41 board.
- USB connection between the Linux host and the board.
- A method to enter BOOTSEL mode for firmware flashing.

Supported host environment:

- Linux.
- Python 3.10 or newer for the host library and examples.
- CMake, an Arm embedded toolchain, and the Raspberry Pi Pico SDK when building firmware.
- A libusb backend for PyUSB.

The supplied bootstrap supports Debian, Ubuntu, Arch Linux, and CachyOS. Other distributions can use the package list printed by `./scripts/bootstrap-linux.sh --help` and the manual firmware instructions in [firmware/README.md](../firmware/README.md).

## First-time setup

From the repository root:

```bash
./scripts/bootstrap-linux.sh
```

By default, the script installs packages, creates or uses `$HOME/src/pico-sdk`, initializes the Pico SDK TinyUSB dependency, builds the firmware, installs the USB access rule, creates `.venv`, installs the local Python package, and runs the functional-test preflight.

Pass an existing SDK path when you already have one:

```bash
./scripts/bootstrap-linux.sh --sdk /path/to/pico-sdk
```

Run `./scripts/bootstrap-linux.sh --help` for options that skip individual setup steps.

### Flash the firmware

The firmware build produces:

```text
firmware/build/rp2350_remote_display.uf2
```

Put the board in BOOTSEL mode and copy that UF2 file to the mounted boot volume. After the board reboots into normal firmware, it presents a `WAITING FOR HOST` screen until a host application begins a frame.

The interactive helper combines a clean firmware build with a hardware test:

```bash
./scripts/build-flash-test.sh --sdk /path/to/pico-sdk
```

### Enable Linux USB access

The setup script installs a udev rule and adds the current user to the `rp2350-display` group. Log out and back in, then reconnect the board before opening it from an unprivileged application.

Confirm that the development firmware is visible:

```bash
lsusb -d cafe:4010
```

The default USB ID is for development. Change it, along with the udev rule, before distributing hardware.

## Write a first application

Activate the environment prepared by the bootstrap:

```bash
source .venv/bin/activate
```

Create a small script such as `hello_display.py`:

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

Run it with:

```bash
python hello_display.py
```

The public API is covered in [python/README.md](../python/README.md). The examples directory contains complete working programs for image modes, touch, device text, caching, dirty updates, layout tools, scrolling, plasma animation, and RTC access.

## Display model

The visible canvas is 450×600 pixels in RGB565 format. The origin is the top-left corner. Rectangles use `x`, `y`, `width`, and `height` with half-open bounds:

```text
[x, x + width) × [y, y + height)
```

The device keeps one framebuffer in external PSRAM. A frame transaction groups commands and presents changed display bands when the frame ends. It does not provide a second backbuffer or retained visual layers.

All rendering commands belong inside `with display.frame():`. Calls such as brightness control, cache management, RTC access, device-font inspection, and framebuffer CRC diagnostics run outside a frame.

### Choose a rendering path

| Workload | Recommended path |
|---|---|
| Static controls, labels, and simple graphics | Primitives and host-rendered text |
| Frequently changing full-resolution dashboard | `Canvas` with `DirtyTilePresenter` |
| Reused full-resolution image or icon | Resource cache |
| Scrolling log, chart, or local animation | `copy_rect()` or `scroll_rect()` |
| Full-screen animated background | Scale2, followed by sharp full-resolution overlays |
| Pixel-exact image output | RGB565 RAW or RLE |
| Lower-bandwidth artwork | Palette64 or Palette4, with visual quality tradeoffs |

The full-resolution tile profiles are 18×24, 30×40, and 45×60 pixels. Smaller tiles limit redundant updates around a local change. Larger tiles reduce command overhead for broad changes.

### Scale2 rendering

Scale2 sends a half-resolution source image that the RP2350 expands with 2× nearest-neighbor replication. A 225×300 source fills the 450×600 panel. A raw RGB565 full-screen source is 135,000 bytes before transport encoding, compared with 540,000 bytes at full resolution.

Use Scale2 for animated backgrounds where lower source resolution is acceptable. The board expands RGB565, Palette4, and Palette64 source tiles. Palette modes are lossy and optional Floyd-Steinberg dithering is calculated at source resolution, so each dithered source pixel becomes a visible 2×2 block.

Scale2 writes directly into the normal framebuffer. Draw a Scale2 background first, then draw text, icons, and controls on top. Redraw every overlay that overlaps a changed Scale2 area in the next frame.

Scale2 reduces source pixels and transport data, but it does not guarantee a proportional frame-rate increase. Host rendering, image encoding, USB scheduling, PSRAM writes, and panel presentation still contribute to total frame time.

## Performance expectations

This project is bandwidth-sensitive. Frame rate depends on host rendering and encoding time, USB scheduling and packet overhead, RP2350 PSRAM writes, and panel presentation. The figures below are practical expectations for the included firmware and Python library. They are representative observations, not guaranteed rates for every Linux host or scene.

| Workload | Practical expectation |
|---|---|
| Full-screen, full-resolution RGB565 with most pixels changing every frame | The interactive full-resolution RGB plasma demo is a deliberately demanding case and runs at roughly **1 FPS**. A 450×600 RGB565 frame contains 540,000 bytes before packet framing or encoding. |
| Full-screen Scale2 background | Scale2 sends a 225×300 source image and expands it 2× on the RP2350. Its raw RGB565 source is 135,000 bytes, one quarter of a full-resolution source. It is the preferred path for animated backgrounds where 2× nearest-neighbor pixels are acceptable. |
| Palette4 or Palette64, including Scale2 variants | Palette modes can lower transport volume for artwork that tolerates quantization. Dithering and palette conversion add host work, so the benefit depends on the image and host. Measure the workload instead of assuming a fixed gain. |
| Full-resolution dashboards, graphs, and controls with small local changes | `Canvas` with `DirtyTilePresenter` can approach **30 FPS** in favorable cases because it transfers only changed tiles or rectangles. Small, sparse updates are important. A redraw that changes most of the display behaves much closer to a full-screen transfer. |
| Device primitives, cached assets, `copy_rect()`, and `scroll_rect()` | These paths avoid sending a fresh full-screen image. They are suitable for responsive controls, log views, charts, and UI elements whose changes are spatially limited. |

The plasma demo is useful for comparing modes and measuring a specific host and board:

```bash
./python/scripts/run_examples.sh
```

Choose **Plasma transport demo**, then compare RGB565, palette modes, and the Scale2 toggle. It reports live FPS, transfer throughput, host render time, and transfer time.

For dashboards, preserve a host-side `Canvas`, present it with `DirtyTilePresenter`, and update only the regions that changed. Use `region_mode="rect"` when a small changed area inside a tile benefits from a tighter RGB565 update. Reset the presenter after any direct device-side framebuffer operation so its baseline remains correct.

## Touch and RTC

Touch input is delivered as asynchronous events. Use `poll_events()`, `poll_latest_touch()`, or `wait_for_touch()` from the Python library. Move events are coalesced so interactive applications can use the most recent contact position efficiently.

The board RTC stores UTC calendar values. `read_rtc()` returns its current state. `set_rtc()` writes a timezone-aware value. `sync_rtc_from_ntp()` asks an NTP server from the Linux host, writes the resulting UTC time to the board, and reads it back. RTC synchronization does not change the host operating system clock.

The RTC clock can be invalid after power loss. Check `RtcReading.oscillator_valid` before trusting a reading.

## Next steps

- Review [python/README.md](../python/README.md) before building an application.
- Read the [protocol reference](protocol.md) when writing another host implementation or changing firmware-host behavior.
- Run the [testing guide](testing.md) before relying on a new firmware build.
- Use [troubleshooting.md](troubleshooting.md) for common setup and runtime failures.
