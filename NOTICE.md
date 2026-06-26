# Notices

This repository combines original project code with retained upstream material.

- Project firmware, Python package, functional-test code, build helpers, and documentation are released under the MIT License in [LICENSE](LICENSE), except assets identified as separately copyrighted below.
- `firmware/drivers/waveshare/` derives from Waveshare board-support source. Retain the MIT notices present in those files.
- `firmware/drivers/psram/tlsf/` is TLSF by Matthew Conte under BSD-3-Clause. The applicable text is in [`firmware/LICENSES/BSD-3-Clause-TLSF.txt`](firmware/LICENSES/BSD-3-Clause-TLSF.txt).
- `firmware/pico_sdk_import.cmake` originates from the Raspberry Pi Pico SDK and retains its BSD-3-Clause notice in the file header. The Pico SDK itself is not included in this repository.
- `firmware/assets/unifont_all-17.0.04.hex.gz` is the GNU Unifont 17.0.04 `unifont_all` bitmap source. The derived `unifont_all-17.0.04.bin` asset is used only for flash-resident device text. Its upstream dual license and attribution are in [`firmware/LICENSES/GNU-Unifont-License.txt`](firmware/LICENSES/GNU-Unifont-License.txt) and [`firmware/NOTICE.md`](firmware/NOTICE.md).
- `functional-test/assets/reference_image_450x600.png` is copyright © 2026 Charles McPherson. It is included with permission for use and redistribution with this repository. It remains separately copyrighted and is not covered by the repository MIT License.

Retain applicable source notices and license texts in redistributed copies.
