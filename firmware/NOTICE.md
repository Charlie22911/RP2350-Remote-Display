# Notices

This project includes source from multiple origins.

- `firmware/`, project CMake files, scripts, and project documentation are original project material under the MIT License in [LICENSE](LICENSE).
- `drivers/waveshare/` derives from Waveshare board support source and retains its MIT permission notices in the source files.
- `drivers/psram/tlsf/` is TLSF by Matthew Conte under BSD-3-Clause. Its source retains SPDX identifiers and its license is reproduced in [LICENSES/BSD-3-Clause-TLSF.txt](LICENSES/BSD-3-Clause-TLSF.txt).
- `pico_sdk_import.cmake` originates from the Raspberry Pi Pico SDK and retains its BSD-3-Clause notice in the file header. The Raspberry Pi Pico SDK itself is not bundled.

## Built-in GNU Unifont asset

`firmware/assets/unifont_all-17.0.04.hex.gz` is the GNU Unifont 17.0.04
`unifont_all` bitmap source. `firmware/assets/unifont_all-17.0.04.bin` is a
lossless project-specific binary packing of that font data for direct firmware
flash storage. The renderer reads it through `firmware/builtin_font.c`.

The compiled fonts are dual-licensed under the SIL Open Font License 1.1 and
GNU GPL version 2 or later with the GNU Font Embedding Exception. The upstream
license text is retained in
[`LICENSES/GNU-Unifont-License.txt`](LICENSES/GNU-Unifont-License.txt). The
font asset is separate from the project MIT source files.

Retain applicable source notices and license texts in redistributed copies.
