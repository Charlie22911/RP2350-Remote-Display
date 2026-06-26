"""Focused resilience checks for the interactive system dashboard example."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "dirty_dashboard.py"


def load_dashboard_module():
    spec = importlib.util.spec_from_file_location("dirty_dashboard_example", EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ip_command_returns_ipv4_address(monkeypatch) -> None:
    dashboard = load_dashboard_module()
    monkeypatch.setattr(dashboard.shutil, "which", lambda command: "/usr/bin/ip")
    monkeypatch.setattr(
        dashboard.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout="2: eth0    inet 192.0.2.25/24 brd 192.0.2.255 scope global eth0\n",
            stderr="",
        ),
    )

    assert dashboard.interface_ipv4_from_ip_command("eth0") == "192.0.2.25"


def test_ip_command_failure_falls_back_cleanly(monkeypatch) -> None:
    dashboard = load_dashboard_module()
    monkeypatch.setattr(dashboard.shutil, "which", lambda command: "/usr/bin/ip")
    monkeypatch.setattr(
        dashboard.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr=""),
    )

    assert dashboard.interface_ipv4_from_ip_command("eth0") is None


def test_memory_snapshot_uses_older_kernel_fallback(monkeypatch) -> None:
    dashboard = load_dashboard_module()
    monkeypatch.setattr(
        dashboard,
        "safe_read_text",
        lambda path: """MemTotal:        1000 kB\nMemFree:          100 kB\nBuffers:          200 kB\nCached:           300 kB\nSReclaimable:      50 kB\n""",
    )

    assert dashboard.read_memory_snapshot_kib() == (1000, 650)


def test_interface_ip_handles_missing_interface() -> None:
    dashboard = load_dashboard_module()
    assert dashboard.interface_ip(None) is None


def test_ioctl_fallback_uses_full_ifreq_buffer(monkeypatch) -> None:
    dashboard = load_dashboard_module()
    requests: list[bytes] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def fileno(self) -> int:
            return 7

    class FakeFcntl:
        @staticmethod
        def ioctl(fd: int, request_code: int, request: bytes) -> bytes:
            assert fd == 7
            assert request_code == 0x8915
            requests.append(request)
            return b"\0" * 20 + bytes((192, 0, 2, 99)) + b"\0" * 232

    monkeypatch.setattr(dashboard, "interface_ipv4_from_ip_command", lambda iface: None)
    monkeypatch.setattr(dashboard, "fcntl", FakeFcntl())
    monkeypatch.setattr(dashboard.socket, "socket", lambda *args, **kwargs: FakeSocket())

    assert dashboard.interface_ip("eth0") == "192.0.2.99"
    assert len(requests) == 1
    assert len(requests[0]) == 256
