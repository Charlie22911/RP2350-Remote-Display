# Release guide

This project uses one repository version for the Python package, firmware metadata, and functional test. Development checkouts use a PEP 440 development version such as `1.2.17.dev0`; published releases use the corresponding final version such as `1.2.17`. The USB protocol version changes only when the wire contract changes.

## Prepare a release

1. Start from a clean commit on `main` with successful required checks.
2. Replace the development value in `VERSION` and the synchronized package/test metadata with the final `MAJOR.MINOR.PATCH` value. Remove `(development)` from the root compatibility row, describe the Python checkout as `release`, and describe the firmware version as the current `release`; `scripts/check-version-consistency.py` enforces those final-release forms.
3. Move the relevant `Unreleased` notes in both changelogs under that final version heading and add the release date.
4. Confirm that user-facing compatibility tables and release references describe the final version.
5. Run the complete source verification:

   ```bash
   ./scripts/verify.sh
   ```

6. Build the Python wheel and source distribution, then install the wheel into a clean environment:

   ```bash
   ./scripts/build-python-wheel.sh
   python3 -m venv /tmp/rpd-release-check
   /tmp/rpd-release-check/bin/python -m pip install dist/*.whl
   /tmp/rpd-release-check/bin/python -m pip check
   ```

7. Build the firmware from a clean directory and run the physical functional test on the target board.

   ```bash
   ./firmware/scripts/build.sh --clean --sdk /path/to/pico-sdk
   ./functional-test/run.sh --report ./functional-test/reports/release.json
   ```

The release firmware uses the documented 250 MHz system-clock and 133 MHz PSRAM-ceiling performance profile unless the release notes explicitly identify another profile.

## Record provenance and checksums

Keep enough information to reproduce the binary without implying a stronger attestation than the project actually provides:

- Exact project source commit and release tag.
- Raspberry Pi Pico SDK commit. CI uses SDK 2.2.0 commit `a1438dff1d38bd9c65dbd693f0e5db4b9ae91779`.
- Arm compiler, CMake, Python, and build frontend versions.
- Board name, `RPD_SYS_CLOCK_KHZ`, `RPD_PSRAM_MAX_SCK_HZ`, USB VID/PID, and build type.
- CI run URL and the functional-test JSON report from physical hardware.

Generate SHA-256 checksums after all artifacts are final:

```bash
sha256sum \
  firmware/build/rp2350_remote_display.uf2 \
  dist/*.whl \
  dist/*.tar.gz > SHA256SUMS
```

Do not regenerate an artifact after producing `SHA256SUMS`. A checksum detects a changed download; it is not a substitute for signed provenance because an attacker who can replace both files can replace the checksum too.

## Publish and advance development

1. Create an immutable `MAJOR.MINOR.PATCH` tag at the verified release commit.
2. Create the GitHub release from that tag and attach the UF2, wheel, source distribution, `SHA256SUMS`, build-provenance record, and relevant functional-test report.
3. State supported hardware, protocol, default clock, known limitations, and whether the release is a prerelease.
4. Verify the downloaded artifacts and perform one clean install from the release page.
5. Advance `main` to the next `.dev0` version and restore `Unreleased` changelog sections before accepting additional user-visible changes.

Never move or reuse a published release tag. If an artifact is wrong, withdraw it, fix the source, and publish a new patch release.
