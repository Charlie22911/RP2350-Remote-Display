#!/usr/bin/env python3
"""Check current-release metadata across the repository."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?$")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc


def require_equal(label: str, actual: str, expected: str, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected}, found {actual}")


def require_match(label: str, text: str, pattern: str, expected: str, errors: list[str]) -> None:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        errors.append(f"{label}: expected declaration was not found")
        return
    require_equal(label, match.group(1), expected, errors)


def main() -> int:
    errors: list[str] = []
    version = read_text(ROOT / "VERSION").strip()
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        print(
            "VERSION must use MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH.devN form.",
            file=sys.stderr,
        )
        return 1

    major, minor, patch = (int(part) for part in match.groups()[:3])
    development_version = match.group(4) is not None
    if not (0 <= major <= 9 and 0 <= minor <= 9 and 0 <= patch <= 99):
        print("VERSION must use one-digit major/minor and a patch number from 0 through 99.", file=sys.stderr)
        return 1
    usb_bcd = f"0x{major:X}{minor:X}{patch:02d}"

    require_match(
        "python/pyproject.toml project.version",
        read_text(ROOT / "python/pyproject.toml"),
        r'^version\s*=\s*"([^"]+)"\s*$',
        version,
        errors,
    )
    require_match(
        "python/src/rp2350_remote_display/__init__.py __version__",
        read_text(ROOT / "python/src/rp2350_remote_display/__init__.py"),
        r'^__version__\s*=\s*"([^"]+)"\s*$',
        version,
        errors,
    )
    require_equal(
        "functional-test/VERSION",
        read_text(ROOT / "functional-test/VERSION").strip(),
        version,
        errors,
    )

    cmake = read_text(ROOT / "firmware/CMakeLists.txt")
    if 'file(READ "${CMAKE_CURRENT_LIST_DIR}/../VERSION" RPD_RELEASE_VERSION)' not in cmake:
        errors.append("firmware/CMakeLists.txt: firmware version is not read from VERSION")
    if 'pico_set_program_version(rp2350_remote_display "${RPD_RELEASE_VERSION}")' not in cmake:
        errors.append("firmware/CMakeLists.txt: program version is not derived from VERSION")
    if 'set(RPD_USB_BCD_DEVICE_DEFAULT "0x${RPD_USB_BCD_MAJOR}${RPD_USB_BCD_MINOR}${RPD_USB_BCD_PATCH}")' not in cmake:
        errors.append("firmware/CMakeLists.txt: USB bcdDevice is not derived from VERSION")
    if 'set(RPD_USB_BCD_DEVICE "${RPD_USB_BCD_DEVICE_DEFAULT}" CACHE STRING' not in cmake or '"USB bcdDevice release code derived from VERSION" FORCE)' not in cmake:
        errors.append("firmware/CMakeLists.txt: USB bcdDevice cache value is not forced from VERSION")
    if 'project(rp2350_remote_display_firmware VERSION "${RPD_RELEASE_VERSION_CORE}"' not in cmake:
        errors.append("firmware/CMakeLists.txt: CMake project version is not derived from the numeric VERSION core")

    firmware_protocol_text = read_text(ROOT / "firmware/firmware/remote_protocol.h")
    firmware_protocol = re.search(r'^#define RPD_PROTOCOL_VERSION ([0-9]+)u$', firmware_protocol_text, re.MULTILINE)
    if firmware_protocol is None:
        errors.append("firmware/firmware/remote_protocol.h: protocol declaration was not found")
        protocol = ""
    else:
        protocol = firmware_protocol.group(1)
    require_match(
        "python/src/rp2350_remote_display/protocol.py PROTOCOL_VERSION",
        read_text(ROOT / "python/src/rp2350_remote_display/protocol.py"),
        r'^PROTOCOL_VERSION\s*=\s*([0-9]+)\s*$',
        protocol,
        errors,
    )
    for label, relative_path, pattern in (
        ("README.md USB protocol", "README.md", r'^\| USB protocol \| ([0-9]+) \|$'),
        ("docs/protocol.md HELLO", "docs/protocol.md", r'Send `HELLO` with protocol ([0-9]+)\.'),
        ("docs/troubleshooting.md protocol mismatch", "docs/troubleshooting.md", r'must both use protocol ([0-9]+)\.'),
        ("firmware/README.md protocol", "firmware/README.md", r'USB protocol \*\*([0-9]+)\*\*'),
        ("python/README.md protocol", "python/README.md", r'USB \*\*protocol ([0-9]+)\*\*'),
    ):
        require_match(label, read_text(ROOT / relative_path), pattern, protocol, errors)

    root_readme = read_text(ROOT / "README.md")
    require_match(
        "README.md project version",
        root_readme,
        (
            r'^\| Project version \| ([^ |]+) \(development\) \|$'
            if development_version
            else r'^\| Project version \| ([^ |]+) \|$'
        ),
        version,
        errors,
    )
    require_match(
        "python/README.md current version",
        read_text(ROOT / "python/README.md"),
        (
            r'This checkout is development version \*\*([^*]+)\*\*'
            if development_version
            else r'This checkout is release \*\*([^*]+)\*\*'
        ),
        version,
        errors,
    )
    require_match(
        "firmware/README.md current version",
        read_text(ROOT / "firmware/README.md"),
        (
            r'The current firmware development version is \*\*([^*]+)\*\*'
            if development_version
            else r'The current firmware release is \*\*([^*]+)\*\*'
        ),
        version,
        errors,
    )
    if not development_version:
        require_match(
            "README.md latest release",
            root_readme,
            r'^\| Latest release \| \[([^]]+)\]\(https://github\.com/Charlie22911/RP2350-Remote-Display/releases/tag/\1\) \|$',
            version,
            errors,
        )

    for changelog in (ROOT / "python/CHANGELOG.md", ROOT / "functional-test/CHANGELOG.md"):
        first_heading = re.search(
            r"^## (Unreleased|[0-9]+\.[0-9]+\.[0-9]+)$",
            read_text(changelog),
            re.MULTILINE,
        )
        if first_heading is None:
            errors.append(f"{changelog.relative_to(ROOT)}: current changelog heading was not found")
        else:
            expected_heading = "Unreleased" if development_version else version
            require_equal(
                f"{changelog.relative_to(ROOT)} current changelog heading",
                first_heading.group(1),
                expected_heading,
                errors,
            )

    if errors:
        print("Release metadata is inconsistent:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        f"Release metadata is consistent: project {version}; protocol {protocol}; USB bcdDevice default {usb_bcd}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
