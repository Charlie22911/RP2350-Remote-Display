# Contributing

Open an issue before starting a broad redesign. Keep changes focused and include the behavior, compatibility impact, and validation performed.

## Before opening a pull request

Run the repository checks from the root:

```bash
./scripts/verify.sh
```

Run a clean firmware build and the physical functional test when a change affects firmware, rendering, USB transport, touch, the resource cache, or protocol behavior:

```bash
./firmware/scripts/build.sh --clean --sdk /path/to/pico-sdk
./functional-test/run.sh
```

Document changes that affect setup, supported hardware, public API behavior, protocol behavior, or test expectations. Update the canonical page for the topic instead of adding a duplicate explanation.

## Release-version changes

`VERSION` defines the current project version. Development checkouts use a value such as `1.2.17.dev0`; published releases use the corresponding final value such as `1.2.17`. Release preparation must keep the Python package, firmware build metadata, functional-test metadata, changelogs, and current documentation aligned. Run the consistency check before committing:

```bash
python3 scripts/check-version-consistency.py
```

The USB `bcdDevice` value is a compact BCD release code derived from `VERSION`; it is not an independent project version.

Follow the [release guide](docs/releasing.md) for final-version promotion, clean builds, artifact checksums, provenance records, immutable tags, and the post-release development bump.

## Protocol changes

The protocol declarations in `firmware/firmware/remote_protocol.h` and `python/src/rp2350_remote_display/protocol.py` must stay synchronized. A wire-format change requires all of the following:

- Increment the protocol version in both implementations.
- Define capability reporting when the feature is optional.
- Validate packet length, geometry, encoded data, and command state in firmware.
- Add Python input validation and tests.
- Update [docs/protocol.md](docs/protocol.md), the relevant public API guidance, and functional-test coverage.
- Build, flash, and test matching firmware and host software together.

## Documentation changes

Keep the root README concise. Put setup, rendering, protocol, test, and troubleshooting information in their canonical documentation pages. Verify commands, names, versions, and links against the source tree before submitting a documentation change.
