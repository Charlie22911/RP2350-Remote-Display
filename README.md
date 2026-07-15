# RP2350 Remote Display

RP2350 Remote Display connects a host computer to a Waveshare RP2350 Touch AMOLED 2.41 board over USB. The host owns the application. The RP2350, called the Pico in this documentation, drives the 450×600 AMOLED panel, maintains the framebuffer, reports touch input, and exposes the board RTC.

Two rendering terms are used consistently:

- **Host rendering**: the host computer creates the final pixels, then transfers RGB565, Alpha8, or palette image data to the Pico. `Canvas` and `DirtyTilePresenter` follow this path.
- **Pico rendering**: the host sends compact primitive, text, cache, copy, or scroll commands; the Pico firmware turns those commands into framebuffer pixels. The framebuffer persists between frames, but the Pico does not retain a reusable command list.

The project includes firmware, a Python library, examples, and a hardware functional test.

## Compatibility

The USB protocol version is the compatibility boundary. The host and firmware exchange their protocol version during connection setup and reject a mismatch.

| Component | Current release or requirement |
|---|---|
| Project version | 1.2.18.dev0 (development) |
| Latest release | [1.2.16](https://github.com/Charlie22911/RP2350-Remote-Display/releases/tag/1.2.16) |
| Firmware/Python compatibility | Use matching versions from the same release or checkout |
| USB protocol | 16 |
| Board | Waveshare RP2350 Touch AMOLED 2.41 |
| Host operating system | Linux; Windows 11 on AMD64; WSL 2 is an alternative Windows path |
| Python | 3.10 through 3.14 |

The development firmware uses USB vendor ID `0xCAFE` and product ID `0x4010`. Use an assigned USB identity before distributing hardware.

## Quick start

### Flash firmware

The quickest route does not require a firmware toolchain. Download the UF2 and its SHA-256 checksum from the [GitHub releases page](https://github.com/Charlie22911/RP2350-Remote-Display/releases), verify the checksum, put the board in BOOTSEL mode, and copy the UF2 to its mounted boot volume.

Windows 11 can perform this BOOTSEL copy directly. Firmware from the 1.2.18 development line publishes Microsoft OS descriptors so Windows automatically binds its inbox WinUSB driver; no custom INF or driver-association tool is required. The same firmware image continues to work on Linux. Native Windows hosting also requires the Python package from this development line, or a future 1.2.18-or-newer release. See the [Windows 11 guide](docs/windows-11.md).

### Build from source on Linux

Clone the repository, enter it, and run the Linux bootstrap script:

```bash
git clone https://github.com/Charlie22911/RP2350-Remote-Display.git
cd RP2350-Remote-Display
./scripts/bootstrap-linux.sh
```

The script installs supported Linux dependencies, prepares the Pico SDK when needed, builds the firmware, installs Linux USB access rules, creates a local Python environment, installs the package, and runs the non-hardware test preflight.

To build, flash, and test after the SDK is available:

```bash
./scripts/build-flash-test.sh --sdk "$HOME/src/pico-sdk"
```

Put the board in BOOTSEL mode when prompted, copy the generated UF2 to its boot volume, wait for the normal USB reboot, and then continue the test runner. The complete setup flow is in the [user guide](docs/README.md).

The default firmware uses a 250 MHz RP2350 system clock and a 133 MHz PSRAM serial-clock ceiling as its performance profile; the divider produces an actual PSRAM clock of about 125 MHz at that system clock. If a particular board is unstable, rebuild with the conservative profile without changing source code:

```bash
./firmware/scripts/build.sh --clean \
  --clock-khz 150000 \
  --psram-max-sck-hz 109000000 \
  --sdk "$HOME/src/pico-sdk"
```

### Set up the host on Windows 11

Native Windows support targets 64-bit x86 Windows 11 (AMD64). Installing the Python package also installs its packaged libusb backend dependency; the firmware's descriptors let Windows use that backend through WinUSB automatically. WSL 2 remains available, but Windows and WSL cannot own the same attached display at the same time.

Use the step-by-step [Windows 11 guide](docs/windows-11.md) for source or wheel installation, driver verification, WSL ownership, and native hardware-test commands.

## First example

After the Linux bootstrap has completed and USB access is active:

```bash
source .venv/bin/activate
python python/examples/basic_primitives.py
```

On native Windows, use the environment's Python executable from PowerShell:

```powershell
.\.venv\Scripts\python.exe .\python\examples\basic_primitives.py
```

The display should show a simple panel and text. For a complete application example, see the [Python library guide](python/README.md).

## Documentation

- [User guide](docs/README.md): hardware, setup, rendering choices, touch, and RTC use.
- [Protocol reference](docs/protocol.md): wire format, session rules, image transport, and capabilities.
- [Testing guide](docs/testing.md): source verification and hardware validation.
- [Troubleshooting](docs/troubleshooting.md): USB, build, rendering, test, and RTC issues.
- [Windows 11 guide](docs/windows-11.md): native WinUSB setup, BOOTSEL flashing, hardware validation, and optional WSL 2 use.
- [Release guide](docs/releasing.md): versioning, verification, artifacts, checksums, and provenance.
- [Firmware guide](firmware/README.md): firmware build and board-level configuration.
- [Python library guide](python/README.md): installation, API overview, and examples.
- [Functional-test guide](functional-test/README.md): test scope and report interpretation.
- [Contributing](CONTRIBUTING.md): validation expectations for changes.
- [Security policy](SECURITY.md): supported versions, private reporting, and trust boundaries.

## Repository layout

```text
firmware/         RP2350 firmware, board support, assets, and firmware tests
python/           Installable Python host library, examples, and unit tests
functional-test/  Hardware validation tool and visual test assets
scripts/          Repository setup, verification, build, and package helpers
docs/             User, protocol, testing, and troubleshooting documentation
VERSION           Current project version used by firmware and package metadata
.github/          Issue forms, pull-request template, and continuous integration
```

## TODO

- [ ] Add UART support
- [ ] Investigate lossless packet or tile compression
- [ ] Support other display modules
  - [ ] Different-resolution LCDs
  - [ ] Monochrome OLEDs
  - [ ] E-paper displays
- [ ] Generalize display resolution, pixel format, and update constraints
- [ ] Add performance telemetry and benchmarking
- [ ] Add protocol trace capture and replay
- [ ] Expand functional tests for new transports and displays
- [ ] Document supported hardware, wiring, and firmware updates

## License and notices

Project code is released under the MIT License. See [LICENSE](LICENSE). The repository includes material with additional notices and licenses. See [NOTICE.md](NOTICE.md) and the notices within the firmware and functional-test directories.
