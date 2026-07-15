# User guide

## What this project does

RP2350 Remote Display turns the Waveshare RP2350 Touch AMOLED 2.41 board into a USB-attached display endpoint for a host application. The host sends drawing commands and image data. The firmware manages the panel, a 450×600 RGB565 framebuffer, touch events, and the PCF85063 RTC.

The board has no application-specific shell or window system. Your host application owns the full display area.

One firmware image supports both Linux and Windows. Linux uses its normal libusb path; Windows 11 reads the firmware's Microsoft OS descriptors and automatically associates the normal display interface with WinUSB.

## Hardware and host requirements

Supported hardware:

- Waveshare RP2350 Touch AMOLED 2.41 board.
- USB connection between the host computer and the board.
- A method to enter BOOTSEL mode for firmware flashing.

Supported host environment:

- Linux for direct USB operation.
- 64-bit x86 Windows 11 (AMD64) for native WinUSB operation and BOOTSEL flashing.
- WSL 2 as an optional alternative Windows host path.
- Python 3.10 through 3.14 for the host library and examples.
- CMake, an Arm embedded toolchain, and the Raspberry Pi Pico SDK when building firmware.
- PyUSB with a libusb backend. Linux supplies libusb through the operating system; the Python package installs `libusb-package` automatically on Windows AMD64.

The supplied bootstrap supports Debian, Ubuntu, Arch Linux, and CachyOS. Other distributions can use the package list printed by `./scripts/bootstrap-linux.sh --help` and the manual firmware instructions in [firmware/README.md](../firmware/README.md). Windows setup is covered separately in the [Windows 11 guide](windows-11.md).

## First-time setup

### Use a prebuilt release

Download the UF2 and checksum file from the [GitHub releases page](https://github.com/Charlie22911/RP2350-Remote-Display/releases). Verify the SHA-256 value, put the board in BOOTSEL mode, and copy the UF2 to the mounted boot volume. This flashing path works directly on Windows 11 and Linux and does not require the Pico SDK.

Use matching firmware and Python artifacts from the same release. Native Windows hosting requires firmware and host software from the 1.2.18 development line or a later compatible release; earlier published firmware does not advertise WinUSB automatically. Continue with the host setup below when the board shows `WAITING FOR HOST`.

### Build and set up on Linux

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

### Set up the native Windows host

Clone or download this repository, open PowerShell in its root directory, and create a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\python
```

Installing the package on Windows AMD64 also installs the packaged libusb runtime used by PyUSB. No Zadig step, custom INF, or separate libusb DLL download is required. Flash matching 1.2.18-line firmware, reconnect the board, and Windows should select its inbox WinUSB driver automatically.

Windows ARM64 is not currently a supported native host because the packaged backend dependency is limited to AMD64. WSL 2 remains an alternative, but a display attached to WSL is unavailable to native Windows applications until it is detached. See the [Windows 11 guide](windows-11.md) for driver checks and the complete WSL workflow.

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

### Performance clock profile

Release firmware defaults to the project's intentional performance profile: a 250 MHz RP2350 system clock and a 133 MHz maximum requested PSRAM serial clock. The divider produces an actual PSRAM clock of about 125 MHz at that system clock. If a board is unstable, rebuild with the conservative profile without editing source files:

```bash
./firmware/scripts/build.sh --clean \
  --clock-khz 150000 \
  --psram-max-sck-hz 109000000 \
  --sdk /path/to/pico-sdk
```

Supported system-clock values are 120–250 MHz. Keep both selected clock values in test reports and release provenance.

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

On Linux, run it with:

```bash
python hello_display.py
```

On native Windows, activation is optional; run the virtual environment's Python executable directly:

```powershell
.\.venv\Scripts\python.exe .\hello_display.py
```

The public API is covered in [python/README.md](../python/README.md), including a guide to each complete example and the rendering path it demonstrates.

## Display model

The visible canvas is 450×600 pixels in RGB565 format. The origin is the top-left corner. Rectangles use `x`, `y`, `width`, and `height` with half-open bounds:

```text
[x, x + width) × [y, y + height)
```

The device keeps one framebuffer in external PSRAM. A frame transaction groups commands and presents changed display bands when the frame ends. It does not provide a second backbuffer or retained visual layers.

All rendering commands belong inside `with display.frame():`. Calls such as brightness control, cache management, RTC access, device-font inspection, and framebuffer CRC diagnostics run outside a frame.

### Rendering terminology

The **host** is the Linux or Windows computer running the Python application. The **Pico** is the RP2350 board and its firmware.

- **Host rendering** means the host creates final pixels or an Alpha8 text mask and transfers them to the Pico. `Canvas`, `DirtyTilePresenter`, `draw_image()`, and `draw_text()` are host-rendering paths.
- **Pico rendering** means the host sends commands and the Pico creates pixels in its framebuffer. Primitives, `draw_device_text()`, cached-resource replay, `copy_rect()`, and `scroll_rect()` are Pico-rendering paths.

The Pico retains framebuffer pixels after each frame, but it does not retain a command list. Static Pico-rendered walls, labels, and grid lines can be drawn once. Later frames should contain only commands for regions that change.

### Choose a rendering path

| Workload | Recommended path |
|---|---|
| Static controls, labels, and simple graphics | Pico rendering with primitives and Pico-rendered text, or host rendering with Alpha8 text when host fonts are required |
| Live metrics dashboard or bounded control UI | Pico rendering with primitives, `draw_device_text()`, declared clear regions, and `scroll_rect()` |
| Frequently changing host-rendered full-resolution pixels | Host rendering with `Canvas` and `DirtyTilePresenter` |
| Reused full-resolution image or icon | Upload once, then Pico-render from the resource cache |
| Scrolling log, chart, or local animation | Pico rendering with `copy_rect()` or `scroll_rect()` |
| Full-screen animated background | Host-rendered Scale2 source, followed by sharp full-resolution overlays |
| Pixel-exact image output | Host-rendered RGB565 RAW or RLE |
| Lower-bandwidth artwork | Host-rendered Palette64 or Palette4, with visual quality tradeoffs |

The full-resolution tile profiles are 18×24, 30×40, and 45×60 pixels. Smaller tiles limit redundant updates around a local change. Larger tiles reduce command overhead for broad changes.

The included Linux-specific `python/examples/dirty_dashboard.py` uses the Pico-rendered live-UI path. The host samples Linux metrics and calculates graph points. The Pico draws the static frame once, updates only named text rectangles, and scrolls graph interiors inside the existing framebuffer. Its geometry constants are the shared contract for drawing, clearing, scrolling, and touch hit testing.


### Scale2 rendering

Scale2 sends a half-resolution source image that the RP2350 expands with 2× nearest-neighbor replication. A 225×300 source fills the 450×600 panel. A raw RGB565 full-screen source is 135,000 bytes before transport encoding, compared with 540,000 bytes at full resolution.

Use Scale2 for animated backgrounds where lower source resolution is acceptable. The board expands RGB565, Palette4, and Palette64 source tiles. Palette modes are lossy and optional Floyd-Steinberg dithering is calculated at source resolution, so each dithered source pixel becomes a visible 2×2 block.

Scale2 writes directly into the normal framebuffer. Draw a Scale2 background first, then draw text, icons, and controls on top. Redraw every overlay that overlaps a changed Scale2 area in the next frame.

Scale2 reduces source pixels and transport data, but it does not guarantee a proportional frame-rate increase. Host-side pixel generation, image encoding, USB scheduling, PSRAM writes, and panel presentation still contribute to total frame time.

## Touch and RTC

Touch input is delivered as asynchronous events. Use `poll_events()`, `poll_latest_touch()`, or `wait_for_touch()` from the Python library. Move events are coalesced so interactive applications can use the most recent contact position efficiently.

The board RTC stores UTC calendar values. `read_rtc()` returns its current state. `set_rtc()` writes a timezone-aware value. `sync_rtc_from_ntp()` asks an NTP server from the host computer, writes the resulting UTC time to the board, and reads it back. RTC synchronization does not change the host operating system clock.

The RTC clock can be invalid after power loss. Check `RtcReading.oscillator_valid` before trusting a reading.

## Next steps

- Review [python/README.md](../python/README.md) before building an application.
- Read the [protocol reference](protocol.md) when writing another host implementation or changing firmware-host behavior.
- Run the [testing guide](testing.md) before relying on a new firmware build.
- Use [troubleshooting.md](troubleshooting.md) for common setup and runtime failures.
