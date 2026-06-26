# Firmware

This directory contains firmware for the Waveshare RP2350 Touch AMOLED 2.41 board. The firmware owns panel initialization, the 450×600 RGB565 framebuffer, PSRAM allocation, touch sampling, USB transport, device text, the resource cache, and the board RTC interface.

The current firmware release is **1.2.16**. It exposes the display through USB protocol **16**. See the repository [protocol reference](../docs/protocol.md) for the transport contract.

## Build requirements

- CMake
- Python 3
- Arm GNU toolchain with `arm-none-eabi-gcc`
- Raspberry Pi Pico SDK with TinyUSB initialized

Set `PICO_SDK_PATH` or provide `--sdk`:

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
./scripts/build.sh --clean
```

Equivalent explicit form:

```bash
./scripts/build.sh --clean --sdk /path/to/pico-sdk
```

The build produces:

```text
build/rp2350_remote_display.uf2
```

## Flash

Put the board in BOOTSEL mode and copy `build/rp2350_remote_display.uf2` to the mounted boot volume. The board reboots into normal firmware after the copy completes.

Run the full host-to-device validation from the repository root after flashing:

```bash
./functional-test/run.sh
```

## Build configuration

`build.sh` accepts these commonly used options:

```text
--sdk PATH          Pico SDK location
--build-dir PATH    Alternative build directory
--clean             Recreate the selected build directory
--debug             Configure a Debug build
--clock-khz VALUE   RP2350 system clock in kHz
--vid VALUE         USB vendor ID C literal
--pid VALUE         USB product ID C literal
```

The default clock is 250 MHz. It is an overclock. Test panel output, touch, USB, PSRAM behavior, and temperature after changing this value or using a different board.

The default USB identity is `0xCAFE:0x4010` for development. Replace it with an appropriate assigned identity before distributing hardware, then update `../python/udev/60-rp2350-remote-display.rules` to match.

## Firmware behavior

The device maintains one RGB565 framebuffer in external PSRAM. Frame transactions collect host drawing commands, and the firmware presents changed display bands after `FRAME_END`. There is no page flip or retained foreground/background layer system.

The built-in device font is generated from GNU Unifont source and stored as a flash asset. Regenerate it after changing the source asset:

```bash
python tools/generate_builtin_font.py --help
```

Keep the asset, source notices, and license material in this directory when redistributing the firmware.

## Directory map

```text
boards/      Pico SDK board definition for the target hardware
drivers/     Display, touch, PSRAM, and board-support drivers
firmware/    Protocol, renderer, USB, RTC, font, and application sources
assets/      Built-in device-font source and generated binary
scripts/     Firmware build helper
tests/       Native harnesses and font-asset checks
tools/       Asset-generation tools
```

## License and notices

The project firmware is MIT licensed. This directory also includes code and assets with additional notices. See [LICENSE](LICENSE), [NOTICE.md](NOTICE.md), and [LICENSES](LICENSES/).
