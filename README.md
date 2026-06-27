# RP2350 Remote Display

RP2350 Remote Display connects a Linux host computer to a Waveshare RP2350 Touch AMOLED 2.41 board over USB. The host owns the application. The RP2350, called the Pico in this documentation, drives the 450×600 AMOLED panel, maintains the framebuffer, reports touch input, and exposes the board RTC.

Two rendering terms are used consistently:

- **Host rendering**: the Linux host creates the final pixels, then transfers RGB565, Alpha8, or palette image data to the Pico. `Canvas` and `DirtyTilePresenter` follow this path.
- **Pico rendering**: the Linux host sends compact primitive, text, cache, copy, or scroll commands; the Pico firmware turns those commands into framebuffer pixels. The framebuffer persists between frames, but the Pico does not retain a reusable command list.

The project includes firmware, a Python library, examples, and a hardware functional test.

## Compatibility

The USB protocol version is the compatibility boundary. The host and firmware exchange their protocol version during connection setup and reject a mismatch.

| Component | Current release or requirement |
|---|---|
| Project release | 1.2.16 |
| Firmware release | 1.2.16 |
| Python package | 1.2.16 |
| USB protocol | 16 |
| Board | Waveshare RP2350 Touch AMOLED 2.41 |
| Host operating system | Linux |
| Python | 3.10 or newer |

The development firmware uses USB vendor ID `0xCAFE` and product ID `0x4010`. Use an assigned USB identity before distributing hardware.

## Quick start

Clone the repository, enter it, and run the Linux bootstrap script:

```bash
git clone <repository-url>
cd RP2350-Remote-Display
./scripts/bootstrap-linux.sh
```

The script installs supported Linux dependencies, prepares the Pico SDK when needed, builds the firmware, installs Linux USB access rules, creates a local Python environment, installs the package, and runs the non-hardware test preflight.

To build, flash, and test after the SDK is available:

```bash
./scripts/build-flash-test.sh --sdk "$HOME/src/pico-sdk"
```

Put the board in BOOTSEL mode when prompted, copy the generated UF2 to its boot volume, wait for the normal USB reboot, and then continue the test runner. The complete setup flow is in the [user guide](docs/README.md).

## First example

After the bootstrap has completed and Linux USB access is active:

```bash
source .venv/bin/activate
python python/examples/basic_primitives.py
```

The display should show a simple panel and text. For a complete application example, see the [Python library guide](python/README.md).

## Documentation

- [User guide](docs/README.md): hardware, setup, rendering choices, touch, and RTC use.
- [Protocol reference](docs/protocol.md): wire format, session rules, image transport, and capabilities.
- [Testing guide](docs/testing.md): source verification and hardware validation.
- [Troubleshooting](docs/troubleshooting.md): USB, build, rendering, test, and RTC issues.
- [Firmware guide](firmware/README.md): firmware build and board-level configuration.
- [Python library guide](python/README.md): installation, API overview, and examples.
- [Functional-test guide](functional-test/README.md): test scope and report interpretation.
- [Contributing](CONTRIBUTING.md): validation expectations for changes.

## Repository layout

```text
firmware/         RP2350 firmware, board support, assets, and firmware tests
python/           Installable Python host library, examples, and unit tests
functional-test/  Hardware validation tool and visual test assets
scripts/          Repository setup, verification, build, and package helpers
docs/             User, protocol, testing, and troubleshooting documentation
VERSION           Current project release used by firmware and package metadata
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
