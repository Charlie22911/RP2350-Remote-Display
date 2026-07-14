#!/usr/bin/env python3
"""Pico-rendered interactive Linux system dashboard.

The Linux host samples metrics and calculates line-graph points. The Pico draws
primitives and its firmware-resident font into the framebuffer from compact
commands. Touch a category card for a fullscreen graph; touch Back to return.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import select
import socket
import struct
import subprocess
import sys
import time
from typing import Callable, Iterator, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by Windows imports
    fcntl = None

from rp2350_remote_display import RemoteDisplay, rgb565

MIN_REFRESH_HZ = 1.0
MAX_REFRESH_HZ = 15.0
MIN_HISTORY_SECONDS = 10.0
MAX_HISTORY_SECONDS = 60.0
MAX_HISTORY = int(MAX_HISTORY_SECONDS * MAX_REFRESH_HZ) + 1
USB_SATURATION_BYTES_PER_S = 55 * 1024
NETWORK_FULL_SCALE_BPS = 24_000.0

BLACK = rgb565(5, 7, 13)
SURFACE = rgb565(13, 17, 27)
PANEL = rgb565(20, 29, 48)
PANEL_ALT = rgb565(14, 23, 39)
BORDER = rgb565(58, 81, 118)
GRID = rgb565(40, 55, 79)
WHITE = rgb565(243, 247, 255)
MUTED = rgb565(150, 168, 194)
MUTED_DARK = rgb565(104, 121, 146)
ACCENT = rgb565(84, 217, 255)
GREEN = rgb565(84, 216, 156)
ORANGE = rgb565(255, 170, 76)
RED = rgb565(255, 108, 108)
YELLOW = rgb565(249, 219, 99)
PURPLE = rgb565(194, 133, 255)
BLUE = rgb565(109, 169, 255)

# Layout contract. Rectangles are x, y, width, height with exclusive right and
# bottom edges. Device text uses an 8x16 cell grid.
PANEL_FRAME_RECT = (16, 16, 416, 568)
HEADER_RECT = (16, 16, 416, 64)
GRID_RECT = (16, 80, 416, 472)
FOOTER_RECT = (16, 552, 416, 32)
VERTICAL_DIVIDER_X = 223
HORIZONTAL_DIVIDER_Y = 316

# Cards share the structural walls at x=223 and y=316. Their content begins
# one pixel inside those walls so incremental updates never overwrite borders.
CARD_RECTS = {
    "cpu": (17, 81, 206, 235),
    "memory": (224, 81, 207, 235),
    "disk": (17, 317, 206, 235),
    "network": (224, 317, 207, 235),
}
CARD_PLOT_RECTS = {
    "cpu": (25, 153, 190, 155),
    "memory": (232, 153, 190, 155),
    "disk": (25, 389, 190, 155),
    "network": (232, 389, 190, 155),
}
CARD_TITLE_RECTS = {
    "cpu": (24, 96, 192, 16),
    "memory": (232, 96, 192, 16),
    "disk": (24, 332, 192, 16),
    "network": (232, 332, 192, 16),
}
CARD_TEXT_RECTS = {
    "cpu": ((24, 112, 192, 16), (24, 128, 192, 16)),
    "memory": ((232, 112, 192, 16), (232, 128, 192, 16)),
    "disk": ((24, 348, 192, 16), (24, 364, 192, 16)),
    "network": ((232, 348, 192, 16), (232, 364, 192, 16)),
}
HEADER_DYNAMIC_RECTS = {
    "date": (24, 40, 88, 16),
    "time": (360, 24, 64, 16),
    "uptime": (304, 40, 120, 16),
    "network": (24, 56, 232, 16),
    "performance": (264, 56, 160, 16),
}
FULLSCREEN_PLOT_RECT = (24, 112, 400, 440)
FULLSCREEN_LEGEND_RECT = (16, 552, 416, 32)
FULLSCREEN_SUMMARY_RECTS = ((24, 64, 272, 16), (24, 80, 272, 16))
FULLSCREEN_HEADER_RECT = (16, 16, 416, 96)
# The Back button is right-aligned with a 16 px panel margin and has an
# explicit 8 px clearance above and below inside the fullscreen header.
BACK_BUTTON_RECT = (304, 24, 112, 80)
FULLSCREEN_LEGEND_VALUE_RECTS = ((24, 560, 128, 16), (152, 560, 128, 16), (280, 560, 128, 16))

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class DiskTarget:
    name: str
    device_path: str
    model: str
    size_bytes: int
    mountpoint: str | None


@dataclass(frozen=True)
class MonitorConfig:
    network_iface: str | None
    disk: DiskTarget
    refresh_hz: float
    history_seconds: float = 30.0

    @property
    def sample_interval_s(self) -> float:
        return 1.0 / self.refresh_hz

    def history_sample_count(self) -> int:
        return max(2, min(MAX_HISTORY, int(round(self.history_seconds * self.refresh_hz)) + 1))


@dataclass(frozen=True)
class Snapshot:
    timestamp: datetime
    uptime_s: float
    cpu_usage_percent: float
    cpu_temp_c: float | None
    cpu_freq_mhz: float | None
    cpu_max_freq_mhz: float | None
    ram_used_percent: float
    ram_available_percent: float
    swap_used_percent: float
    ram_used_gib: float
    ram_total_gib: float
    disk_name: str
    disk_mountpoint: str | None
    disk_used_percent: float | None
    disk_used_gib: float | None
    disk_total_gib: float | None
    disk_activity_bps: float | None
    disk_temp_c: float | None
    net_iface: str | None
    net_ip: str | None
    net_rx_bps: float
    net_tx_bps: float


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    label: str
    color: int
    min_value: float
    max_value: float | None
    formatter: Callable[[float], str]


@dataclass(frozen=True)
class CategorySpec:
    key: str
    title: str
    rect: Rect
    plot_rect: Rect
    summary_lines: tuple[str, str]
    series: tuple[SeriesSpec, ...]


@dataclass(frozen=True)
class PerformanceStats:
    fps: float = 0.0
    usb_bytes_per_s: float = 0.0

    @property
    def usb_percent(self) -> float:
        return max(0.0, min(100.0, 100.0 * self.usb_bytes_per_s / USB_SATURATION_BYTES_PER_S))


class CpuSampler:
    def __init__(self) -> None:
        self._previous_total: int | None = None
        self._previous_idle: int | None = None
        self.max_freq_mhz = self._read_max_freq_mhz()

    def sample_usage_percent(self) -> float:
        try:
            line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
            fields = [int(field) for field in line.split()[1:]]
        except (OSError, ValueError, IndexError):
            return 0.0
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        if self._previous_total is None or self._previous_idle is None:
            self._previous_total = total
            self._previous_idle = idle
            return 0.0
        total_delta = total - self._previous_total
        idle_delta = idle - self._previous_idle
        self._previous_total = total
        self._previous_idle = idle
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))

    def sample_freq_mhz(self) -> float | None:
        for candidate in (
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
            "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq",
        ):
            try:
                return float(Path(candidate).read_text(encoding="utf-8").strip()) / 1000.0
            except (OSError, ValueError):
                pass
        values: list[float] = []
        try:
            lines = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return None
        for line in lines:
            if line.lower().startswith("cpu mhz"):
                try:
                    values.append(float(line.split(":", 1)[1].strip()))
                except (ValueError, IndexError):
                    pass
        return sum(values) / len(values) if values else None

    def sample_temp_c(self) -> float | None:
        root = Path("/sys/class/thermal")
        if not root.is_dir():
            return None
        preferred: list[float] = []
        fallback: list[float] = []
        for zone in sorted(root.glob("thermal_zone*")):
            try:
                raw = float((zone / "temp").read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            temp_c = raw / 1000.0 if raw > 1000 else raw
            if not 0.0 <= temp_c <= 150.0:
                continue
            try:
                name = (zone / "type").read_text(encoding="utf-8").strip().lower()
            except OSError:
                name = ""
            if any(token in name for token in ("cpu", "package", "soc", "x86_pkg_temp", "tctl", "core")):
                preferred.append(temp_c)
            else:
                fallback.append(temp_c)
        return max(preferred) if preferred else (max(fallback) if fallback else None)

    @staticmethod
    def _read_max_freq_mhz() -> float | None:
        for candidate in (
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq",
            "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq",
        ):
            try:
                return float(Path(candidate).read_text(encoding="utf-8").strip()) / 1000.0
            except (OSError, ValueError):
                pass
        return None


class NetworkSampler:
    """Sample raw byte-counter rates for the selected network interface.

    The rate is the exact byte-counter delta divided by its measured interval.
    No smoothing or decay is applied. The dashboard uses a fixed 24 kbps graph
    scale so raw traffic does not force history rescaling or graph replotting.
    """

    def __init__(self, selected_iface: str | None) -> None:
        self.selected_iface = selected_iface
        self._previous: tuple[int, int, float] | None = None

    def sample(self) -> tuple[str | None, str | None, float, float]:
        iface = self.selected_iface or primary_interface()
        ip_value = interface_ip(iface) if iface else None
        if not iface:
            self._reset()
            return None, ip_value, 0.0, 0.0
        stats_root = Path("/sys/class/net") / iface / "statistics"
        try:
            rx_bytes = int((stats_root / "rx_bytes").read_text(encoding="utf-8").strip())
            tx_bytes = int((stats_root / "tx_bytes").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            self._reset()
            return iface, ip_value, 0.0, 0.0
        now = time.monotonic()
        if self._previous is None:
            self._previous = (rx_bytes, tx_bytes, now)
            return iface, ip_value, 0.0, 0.0
        old_rx, old_tx, old_time = self._previous
        self._previous = (rx_bytes, tx_bytes, now)
        elapsed = max(now - old_time, 1e-6)
        raw_rx_bps = max(0.0, (rx_bytes - old_rx) * 8.0 / elapsed)
        raw_tx_bps = max(0.0, (tx_bytes - old_tx) * 8.0 / elapsed)
        return iface, ip_value, raw_rx_bps, raw_tx_bps

    def _reset(self) -> None:
        self._previous = None


class DiskSampler:
    def __init__(self, target: DiskTarget) -> None:
        self.target = target
        self._previous: tuple[int, int, float] | None = None
        self._temp_c: float | None = None
        self._next_temp_at = 0.0

    def sample(self) -> tuple[float | None, float | None, float | None, float | None, float | None]:
        usage = disk_usage(self.target.mountpoint)
        activity_bps = self._read_activity_bps()
        now = time.monotonic()
        if now >= self._next_temp_at:
            self._temp_c = read_disk_temperature_c(self.target.device_path)
            self._next_temp_at = now + 30.0
        return (*usage, activity_bps, self._temp_c)

    def _read_activity_bps(self) -> float | None:
        fields = read_diskstats(self.target.name)
        now = time.monotonic()
        if fields is None:
            self._previous = None
            return None
        read_sectors, write_sectors = fields
        current = (read_sectors, write_sectors, now)
        if self._previous is None:
            self._previous = current
            return None
        old_read_sectors, old_write_sectors, old_time = self._previous
        self._previous = current
        elapsed_s = max(now - old_time, 1e-6)
        transferred_sectors = (read_sectors - old_read_sectors) + (write_sectors - old_write_sectors)
        return transferred_sectors * 512.0 / elapsed_s if transferred_sectors >= 0 else None


class SystemSampler:
    def __init__(self, config: MonitorConfig) -> None:
        self.cpu = CpuSampler()
        self.network = NetworkSampler(config.network_iface)
        self.disk = DiskSampler(config.disk)

    def sample(self) -> Snapshot:
        timestamp = datetime.now().astimezone()
        meminfo = read_meminfo()
        ram_total_kib = meminfo.get("MemTotal", 0)
        ram_available_kib = available_memory_kib(meminfo)
        ram_used_kib = max(0, ram_total_kib - ram_available_kib)
        swap_total_kib = meminfo.get("SwapTotal", 0)
        swap_free_kib = meminfo.get("SwapFree", 0)
        disk_used_percent, disk_used_gib, disk_total_gib, disk_activity_bps, disk_temp_c = self.disk.sample()
        iface, ip_value, rx_bps, tx_bps = self.network.sample()
        return Snapshot(
            timestamp=timestamp,
            uptime_s=read_uptime_seconds(),
            cpu_usage_percent=self.cpu.sample_usage_percent(),
            cpu_temp_c=self.cpu.sample_temp_c(),
            cpu_freq_mhz=self.cpu.sample_freq_mhz(),
            cpu_max_freq_mhz=self.cpu.max_freq_mhz,
            ram_used_percent=percent(ram_used_kib, ram_total_kib),
            ram_available_percent=percent(ram_available_kib, ram_total_kib),
            swap_used_percent=percent(max(0, swap_total_kib - swap_free_kib), swap_total_kib),
            ram_used_gib=kib_to_gib(ram_used_kib),
            ram_total_gib=kib_to_gib(ram_total_kib),
            disk_name=self.disk.target.name,
            disk_mountpoint=self.disk.target.mountpoint,
            disk_used_percent=disk_used_percent,
            disk_used_gib=disk_used_gib,
            disk_total_gib=disk_total_gib,
            disk_activity_bps=disk_activity_bps,
            disk_temp_c=disk_temp_c,
            net_iface=iface,
            net_ip=ip_value,
            net_rx_bps=rx_bps,
            net_tx_bps=tx_bps,
        )


class DashboardModel:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config
        self.sampler = SystemSampler(config)
        self.snapshot = self.sampler.sample()
        self.history: dict[str, deque[float]] = {
            "cpu_usage": deque([self.snapshot.cpu_usage_percent], maxlen=MAX_HISTORY),
            "cpu_temp": deque([self.snapshot.cpu_temp_c or 0.0], maxlen=MAX_HISTORY),
            "cpu_freq": deque([self.snapshot.cpu_freq_mhz or 0.0], maxlen=MAX_HISTORY),
            "ram_used_percent": deque([self.snapshot.ram_used_percent], maxlen=MAX_HISTORY),
            "ram_available_percent": deque([self.snapshot.ram_available_percent], maxlen=MAX_HISTORY),
            "swap_used_percent": deque([self.snapshot.swap_used_percent], maxlen=MAX_HISTORY),
            "disk_used_percent": deque([self.snapshot.disk_used_percent or 0.0], maxlen=MAX_HISTORY),
            "disk_activity_bps": deque(maxlen=MAX_HISTORY),
            "disk_temp": deque(maxlen=MAX_HISTORY),
            "net_rx": deque([self.snapshot.net_rx_bps], maxlen=MAX_HISTORY),
            "net_tx": deque([self.snapshot.net_tx_bps], maxlen=MAX_HISTORY),
        }
        self._seen_optional = {"disk_activity_bps": False, "disk_temp": False}
        self._scale_ceilings: dict[str, float] = {}
        self.selected_category: str | None = None
        self.sample_id = 0

    def update(self) -> None:
        self.snapshot = self.sampler.sample()
        self.sample_id += 1
        self.history["cpu_usage"].append(self.snapshot.cpu_usage_percent)
        self.history["cpu_temp"].append(self.snapshot.cpu_temp_c or self.history["cpu_temp"][-1])
        self.history["cpu_freq"].append(self.snapshot.cpu_freq_mhz or self.history["cpu_freq"][-1])
        self.history["ram_used_percent"].append(self.snapshot.ram_used_percent)
        self.history["ram_available_percent"].append(self.snapshot.ram_available_percent)
        self.history["swap_used_percent"].append(self.snapshot.swap_used_percent)
        self.history["disk_used_percent"].append(self.snapshot.disk_used_percent if self.snapshot.disk_used_percent is not None else self.history["disk_used_percent"][-1])
        self._append_optional("disk_activity_bps", self.snapshot.disk_activity_bps)
        self._append_optional("disk_temp", self.snapshot.disk_temp_c)
        self.history["net_rx"].append(self.snapshot.net_rx_bps)
        self.history["net_tx"].append(self.snapshot.net_tx_bps)

    def _append_optional(self, key: str, value: float | None) -> None:
        history = self.history[key]
        if value is None:
            if history:
                history.append(history[-1])
            return
        if not self._seen_optional[key]:
            history.clear()
            history.append(value)
            self._seen_optional[key] = True
        else:
            history.append(value)

    def stable_ceiling(self, key: str, observed: float, *, minimum: float) -> float:
        """Promote an adaptive disk-metric range only when it is exceeded.

        Network charts deliberately do not use this path: their scale is fixed
        at 24 kbps so their existing history never needs rescaling.
        """
        current = self._scale_ceilings.get(key)
        if current is None:
            current = stable_rate_ceiling(max(minimum, observed) * 1.25)
        elif observed > current:
            current = stable_rate_ceiling(observed * 1.25)
        self._scale_ceilings[key] = current
        return current

    def categories(self) -> tuple[CategorySpec, ...]:
        snap = self.snapshot
        freq_limit = snap.cpu_max_freq_mhz or max(1000.0, max(self.history["cpu_freq"], default=0.0) * 1.15)
        net_peak = NETWORK_FULL_SCALE_BPS
        network_percent = network_load_percent(snap.net_rx_bps, snap.net_tx_bps)

        disk_series: list[SeriesSpec] = []
        if snap.disk_used_percent is not None:
            disk_series.append(SeriesSpec("disk_used_percent", "Used", YELLOW, 0.0, 100.0, lambda value: f"{value:4.1f}%"))
        if self._seen_optional["disk_activity_bps"]:
            activity_peak = self.stable_ceiling(
                "disk_activity_bps",
                max(self.history["disk_activity_bps"], default=0.0),
                minimum=1_024.0,
            )
            disk_series.append(SeriesSpec("disk_activity_bps", "Activity", GREEN, 0.0, activity_peak, fmt_bytes_per_second))
        if self._seen_optional["disk_temp"]:
            disk_series.append(SeriesSpec("disk_temp", "Temp", ORANGE, 0.0, 100.0, fmt_celsius))

        disk_line2 = f"ACT {fmt_optional_bytes_per_second(snap.disk_activity_bps)}"

        return (
            CategorySpec(
                "cpu", f"CPU: {snap.cpu_usage_percent:.0f}%", CARD_RECTS["cpu"], CARD_PLOT_RECTS["cpu"],
                (f"TMP {fmt_optional_celsius_compact(snap.cpu_temp_c)}", f"FRQ {fmt_optional_freq_compact(snap.cpu_freq_mhz)}"),
                (
                    SeriesSpec("cpu_usage", "Usage", ACCENT, 0.0, 100.0, lambda value: f"{value:4.1f}%"),
                    SeriesSpec("cpu_temp", "Temp", ORANGE, 0.0, 100.0, fmt_celsius),
                    SeriesSpec("cpu_freq", "Freq", GREEN, 0.0, freq_limit, fmt_mhz_or_ghz),
                ),
            ),
            CategorySpec(
                "memory", f"MEMORY: {snap.ram_used_percent:.0f}%", CARD_RECTS["memory"], CARD_PLOT_RECTS["memory"],
                (f"USE {fmt_storage_compact(snap.ram_used_gib)} / {fmt_storage_compact(snap.ram_total_gib)}", f"AVL {snap.ram_available_percent:4.1f}% SWP {snap.swap_used_percent:3.1f}%"),
                (
                    SeriesSpec("ram_used_percent", "Used", PURPLE, 0.0, 100.0, lambda value: f"{value:4.1f}%"),
                    SeriesSpec("ram_available_percent", "Available", GREEN, 0.0, 100.0, lambda value: f"{value:4.1f}%"),
                    SeriesSpec("swap_used_percent", "Swap", ORANGE, 0.0, 100.0, lambda value: f"{value:4.1f}%"),
                ),
            ),
            CategorySpec(
                "disk", f"DISK: {snap.disk_name}"[:24], CARD_RECTS["disk"], CARD_PLOT_RECTS["disk"],
                (fmt_optional_percent(snap.disk_used_percent), disk_line2[:24]), tuple(disk_series),
            ),
            CategorySpec(
                "network", f"NETWORK: {network_percent:.0f}%", CARD_RECTS["network"], CARD_PLOT_RECTS["network"],
                (f"RX {fmt_bps_one_decimal(snap.net_rx_bps)}", f"TX {fmt_bps_one_decimal(snap.net_tx_bps)}"),
                (
                    SeriesSpec("net_rx", "RX", BLUE, 0.0, net_peak, fmt_bps_one_decimal),
                    SeriesSpec("net_tx", "TX", RED, 0.0, net_peak, fmt_bps_one_decimal),
                ),
            ),
        )


# Interactive configuration

def default_monitor_config() -> MonitorConfig:
    targets = list_disk_targets()
    target = next((candidate for candidate in targets if candidate.mountpoint == "/"), None)
    if target is None:
        target = targets[0] if targets else DiskTarget("unknown", "", "", 0, "/")
    return MonitorConfig(None, target, 2.0, 30.0)


def configure_dashboard(current: MonitorConfig) -> MonitorConfig:
    """Edit live-monitor settings from the terminal and return a new config."""
    selected_iface = current.network_iface
    selected_disk = current.disk
    refresh_hz = current.refresh_hz
    history_seconds = current.history_seconds

    while True:
        sample_count = max(2, min(MAX_HISTORY, int(round(history_seconds * refresh_hz)) + 1))
        print("\n=== Remote dashboard settings ===")
        print(f"  1) Network interface: {selected_iface or 'Automatic/default route'}")
        print(f"  2) Disk:              {selected_disk.name} ({selected_disk.mountpoint or 'not mounted'})")
        print(f"  3) Update target:     {refresh_hz:.2f} FPS")
        print(f"  4) History range:     {history_seconds:.0f} s ({sample_count} samples at target)")
        print("  5) Apply settings")
        print("  0) Cancel")
        choice = choose_index("Select setting", 5, default=5, minimum=0)
        if choice == 0:
            print("Settings unchanged.")
            return current
        if choice == 1:
            selected_iface = choose_network_interface(selected_iface)
        elif choice == 2:
            selected_disk = choose_disk_target(selected_disk)
        elif choice == 3:
            refresh_hz = choose_refresh_rate_hz(refresh_hz)
        elif choice == 4:
            history_seconds = choose_history_seconds(history_seconds)
        else:
            config = MonitorConfig(selected_iface, selected_disk, refresh_hz, history_seconds)
            print(
                f"Monitoring {selected_iface or 'automatic network'}, {selected_disk.name}, "
                f"at {refresh_hz:.2f} FPS with {history_seconds:.0f} s history.\n"
            )
            return config


def choose_history_seconds(current_seconds: float) -> float:
    while True:
        raw = input(f"History range in seconds, {MIN_HISTORY_SECONDS:.0f} to {MAX_HISTORY_SECONDS:.0f} [{current_seconds:.0f}]: ").strip()
        if not raw:
            return current_seconds
        try:
            value = float(raw)
        except ValueError:
            print(f"Enter a numeric range from {MIN_HISTORY_SECONDS:.0f} through {MAX_HISTORY_SECONDS:.0f} seconds.")
            continue
        if MIN_HISTORY_SECONDS <= value <= MAX_HISTORY_SECONDS:
            return value
        print(f"Use a history range from {MIN_HISTORY_SECONDS:.0f} through {MAX_HISTORY_SECONDS:.0f} seconds.")


def choose_network_interface(current_iface: str | None) -> str | None:
    default_iface = primary_interface()
    interfaces = list_network_interfaces()
    print("\nNetwork interface:")
    print(f"  0) Automatic/default route ({default_iface or 'none'})")
    for index, iface in enumerate(interfaces, start=1):
        ip_value = interface_ip(iface) or "no address"
        marker = " *" if iface == current_iface else ""
        print(f"  {index}) {iface} ({ip_value}){marker}")
    default = 0 if current_iface is None else (interfaces.index(current_iface) + 1 if current_iface in interfaces else 0)
    choice = choose_index("Select network interface", len(interfaces), default=default)
    return None if choice == 0 else interfaces[choice - 1]


def choose_disk_target(current_disk: DiskTarget) -> DiskTarget:
    targets = list_disk_targets()
    if not targets:
        print("No disks were discovered. Keeping the current disk selection.")
        return current_disk
    default = next((index for index, candidate in enumerate(targets, start=1) if candidate.name == current_disk.name), 1)
    print("\nDisk to monitor:")
    for index, target in enumerate(targets, start=1):
        mount = target.mountpoint or "not mounted"
        model = f" {target.model}" if target.model else ""
        print(f"  {index}) {target.name} {human_bytes(target.size_bytes)}{model} [{mount}]")
    choice = choose_index("Select disk", len(targets), default=default, minimum=1)
    return targets[choice - 1]


def choose_refresh_rate_hz(current_hz: float) -> float:
    while True:
        raw = input(f"Update target in FPS, {MIN_REFRESH_HZ:.2f} to {MAX_REFRESH_HZ:.2f} [{current_hz:.2f}]: ").strip()
        if not raw:
            return current_hz
        try:
            value = float(raw)
        except ValueError:
            print(f"Enter a numeric FPS target from {MIN_REFRESH_HZ:.2f} through {MAX_REFRESH_HZ:.2f}.")
            continue
        if MIN_REFRESH_HZ <= value <= MAX_REFRESH_HZ:
            return value
        print(f"Use an FPS target from {MIN_REFRESH_HZ:.2f} through {MAX_REFRESH_HZ:.2f}.")


def choose_index(prompt: str, maximum: int, *, default: int, minimum: int = 0) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Enter a number from the displayed menu.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"Enter a number from {minimum} through {maximum}.")


def read_console_command() -> str | None:
    """Return one complete terminal command without blocking the dashboard loop."""
    if not sys.stdin.isatty():
        return None
    try:
        readable, _, _ = select.select([sys.stdin], [], [], 0.0)
    except (OSError, ValueError):
        return None
    if not readable:
        return None
    line = sys.stdin.readline()
    if not line:
        return "q"
    return line.strip().lower()


def print_console_controls() -> None:
    print("Console controls: m + Enter opens settings, s + Enter prints status, q + Enter exits, Ctrl+C exits.")


def print_monitor_status(config: MonitorConfig, model: DashboardModel) -> None:
    snapshot = model.snapshot
    print(
        f"Settings: network={config.network_iface or 'automatic'}, disk={config.disk.name}, "
        f"target={config.refresh_hz:.2f} FPS, history={config.history_seconds:.0f}s | "
        f"active={snapshot.net_iface or 'none'}, IP={snapshot.net_ip or 'offline'}"
    )


def list_network_interfaces() -> list[str]:
    root = Path("/sys/class/net")
    if not root.is_dir():
        return []
    return [entry.name for entry in sorted(root.iterdir()) if entry.name != "lo"]


def list_disk_targets() -> list[DiskTarget]:
    lsblk = shutil.which("lsblk")
    if lsblk:
        try:
            result = subprocess.run(
                [lsblk, "-J", "-b", "-o", "NAME,TYPE,SIZE,MODEL,MOUNTPOINTS"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                targets = []
                for node in data.get("blockdevices", []):
                    if node.get("type") != "disk":
                        continue
                    name = str(node.get("name", ""))
                    if not name:
                        continue
                    targets.append(DiskTarget(
                        name=name,
                        device_path=f"/dev/{name}",
                        model=str(node.get("model") or "").strip(),
                        size_bytes=int(node.get("size") or 0),
                        mountpoint=find_first_mountpoint(node),
                    ))
                if targets:
                    return targets
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
            pass
    targets: list[DiskTarget] = []
    for entry in sorted(Path("/sys/block").glob("*")):
        name = entry.name
        if name.startswith(("loop", "ram", "zram", "dm-")):
            continue
        try:
            sectors = int((entry / "size").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            sectors = 0
        targets.append(DiskTarget(name, f"/dev/{name}", "", sectors * 512, None))
    return targets


def find_first_mountpoint(node: dict) -> str | None:
    mountpoints = node.get("mountpoints")
    if isinstance(mountpoints, list):
        for mountpoint in mountpoints:
            if mountpoint:
                return str(mountpoint)
    mountpoint = node.get("mountpoint")
    if mountpoint:
        return str(mountpoint)
    for child in node.get("children") or []:
        found = find_first_mountpoint(child)
        if found:
            return found
    return None


# Sampling helpers

def read_uptime_seconds() -> float:
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        try:
            key, rest = line.split(":", 1)
            values[key] = int(rest.split()[0])
        except (ValueError, IndexError):
            pass
    return values


def available_memory_kib(meminfo: dict[str, int]) -> int:
    if "MemAvailable" in meminfo:
        return meminfo["MemAvailable"]
    return meminfo.get("MemFree", 0) + meminfo.get("Buffers", 0) + meminfo.get("Cached", 0)


def disk_usage(mountpoint: str | None) -> tuple[float | None, float | None, float | None]:
    if not mountpoint:
        return None, None, None
    try:
        stat = os.statvfs(mountpoint)
    except OSError:
        return None, None, None
    total = stat.f_frsize * stat.f_blocks
    free = stat.f_frsize * stat.f_bavail
    used = max(0, total - free)
    return percent(used, total), bytes_to_gib(used), bytes_to_gib(total)


def read_diskstats(name: str) -> tuple[int, int] | None:
    """Return read and write sector counters from /proc/diskstats."""
    if not name:
        return None
    try:
        lines = Path("/proc/diskstats").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) < 11 or fields[2] != name:
            continue
        try:
            return int(fields[5]), int(fields[9])
        except ValueError:
            return None
    return None


def read_disk_temperature_c(device_path: str) -> float | None:
    smartctl = shutil.which("smartctl")
    if not smartctl or not device_path:
        return None
    try:
        result = subprocess.run(
            [smartctl, "-A", "-j", device_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    candidates: list[float] = []
    temperature = data.get("temperature")
    if isinstance(temperature, dict) and isinstance(temperature.get("current"), (int, float)):
        candidates.append(float(temperature["current"]))
    nvme = data.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict) and isinstance(nvme.get("temperature"), (int, float)):
        candidates.append(float(nvme["temperature"]))
    table = data.get("ata_smart_attributes", {}).get("table", [])
    if isinstance(table, list):
        for row in table:
            name = str(row.get("name", "")).lower()
            raw = row.get("raw", {})
            value = raw.get("value") if isinstance(raw, dict) else None
            if "temperature" in name and isinstance(value, (int, float)):
                candidates.append(float(value))
    valid = [value for value in candidates if 0.0 <= value <= 150.0]
    return valid[0] if valid else None


def primary_interface() -> str | None:
    route = Path("/proc/net/route")
    if route.is_file():
        try:
            lines = route.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            lines = []
        for line in lines:
            fields = line.split()
            try:
                if len(fields) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 2:
                    return fields[0]
            except ValueError:
                pass
    for iface in list_network_interfaces():
        try:
            if (Path("/sys/class/net") / iface / "operstate").read_text(encoding="utf-8").strip() == "up":
                return iface
        except OSError:
            pass
    return None


def interface_ip(iface: str | None) -> str | None:
    if not iface:
        return None
    return interface_ipv4_from_ip_command(iface) or interface_ipv4_from_ioctl(iface) or interface_ipv6_from_proc(iface)


def interface_ipv4_from_ip_command(iface: str) -> str | None:
    ip_path = shutil.which("ip")
    if not ip_path:
        return None
    try:
        result = subprocess.run(
            [ip_path, "-o", "-4", "addr", "show", "dev", iface, "scope", "global"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        if "inet" in fields:
            index = fields.index("inet")
            if index + 1 < len(fields):
                return fields[index + 1].split("/", 1)[0]
    return None


def interface_ipv4_from_ioctl(iface: str) -> str | None:
    if fcntl is None:
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ifreq = struct.pack("256s", iface.encode("utf-8")[:15])
        try:
            result = fcntl.ioctl(sock.fileno(), 0x8915, ifreq)
        except OSError:
            return None
        return socket.inet_ntoa(result[20:24])
    finally:
        sock.close()


def interface_ipv6_from_proc(iface: str) -> str | None:
    path = Path("/proc/net/if_inet6")
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) >= 6 and fields[5] == iface:
            raw = fields[0]
            return ":".join(raw[index:index + 4] for index in range(0, 32, 4))
    return None


# Formatting helpers

def bytes_to_gib(value: int) -> float:
    return value / (1024 ** 3)


def kib_to_gib(value: int) -> float:
    return value / (1024 ** 2)


def percent(part: int | float, total: int | float) -> float:
    return 0.0 if total <= 0 else max(0.0, min(100.0, part * 100.0 / total))


def network_load_percent(rx_bits_per_s: float, tx_bits_per_s: float) -> float:
    """Return combined RX+TX load relative to the fixed 24 kbps graph range."""
    return percent(max(0.0, rx_bits_per_s) + max(0.0, tx_bits_per_s), NETWORK_FULL_SCALE_BPS)


def human_bytes(value: int) -> str:
    if value >= 1024 ** 4:
        return f"{value / 1024 ** 4:.1f} TiB"
    if value >= 1024 ** 3:
        return f"{value / 1024 ** 3:.1f} GiB"
    return f"{value / 1024 ** 2:.0f} MiB"


def fmt_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}" if days else f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def fmt_bps_one_decimal(bits_per_second: float) -> str:
    value = max(0.0, bits_per_second)
    units = ("bps", "kbps", "Mbps", "Gbps")
    index = 0
    while value >= 1000.0 and index < len(units) - 1:
        value /= 1000.0
        index += 1
    return f"{value:.1f}{units[index]}"


def stable_rate_ceiling(value: float) -> float:
    """Return a rounded rate ceiling so normal traffic variation does not rescale charts every sample."""
    value = max(1_000.0, value)
    exponent = 10.0 ** math.floor(math.log10(value))
    for multiplier in (1.0, 2.0, 5.0, 10.0):
        ceiling = multiplier * exponent
        if value <= ceiling:
            return ceiling
    return 10.0 * exponent


def fmt_bytes_per_second(bytes_per_second: float) -> str:
    value = max(0.0, bytes_per_second)
    units = ("B/s", "KiB/s", "MiB/s", "GiB/s")
    index = 0
    while value >= 1024.0 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    return f"{value:.1f}{units[index]}"


def fmt_optional_bytes_per_second(value: float | None) -> str:
    return "---" if value is None else fmt_bytes_per_second(value)


def fmt_optional_percent(value: float | None) -> str:
    return "USE ---" if value is None else f"USE {value:4.1f}%"


def fmt_celsius(value: float) -> str:
    return f"{value:4.1f} C"


def fmt_optional_celsius_compact(value: float | None) -> str:
    return "---" if value is None else f"{value:4.1f}C"


def fmt_mhz_or_ghz(value: float) -> str:
    return f"{value / 1000.0:4.2f} GHz" if value >= 1000.0 else f"{value:4.0f} MHz"


def fmt_optional_freq_compact(value: float | None) -> str:
    if value is None:
        return "---"
    return f"{value / 1000.0:4.2f}GHz" if value >= 1000.0 else f"{value:4.0f}MHz"


def fmt_storage_compact(value_gib: float) -> str:
    return f"{value_gib / 1024.0:4.1f}T" if value_gib >= 1024.0 else f"{value_gib:4.1f}G"


def short_interface_line(iface: str | None, ip_value: str | None) -> str:
    return f"{iface or 'net'} {ip_value or 'offline'}"[:29]


def device_text_pixel_width(text: str, *, scale: int = 1) -> int:
    columns = 0
    maximum = 0
    for char in text:
        if char == "\n":
            maximum = max(maximum, columns)
            columns = 0
        elif char == "\t":
            columns += 4
        else:
            columns += 1
    return max(maximum, columns) * 8 * scale


def align8(value: int) -> int:
    return value - value % 8


# Rendering and transfer accounting

class TransferMeter:
    def __init__(self) -> None:
        self._current_bytes = 0
        self._samples: deque[tuple[float, int]] = deque()

    def begin_frame(self) -> None:
        self._current_bytes = 0
        self.record_payload(4)

    def record_payload(self, payload_bytes: int) -> None:
        self._current_bytes += 12 + payload_bytes

    def end_frame(self) -> None:
        self.record_payload(4)
        now = time.monotonic()
        self._samples.append((now, self._current_bytes))
        while self._samples and now - self._samples[0][0] > 2.0:
            self._samples.popleft()

    def stats(self) -> PerformanceStats:
        now = time.monotonic()
        while self._samples and now - self._samples[0][0] > 2.0:
            self._samples.popleft()
        if not self._samples:
            return PerformanceStats()
        oldest = self._samples[0][0]
        duration = max(0.25, min(2.0, now - oldest + 0.25))
        return PerformanceStats(len(self._samples) / duration, sum(value for _, value in self._samples) / duration)


class MeteredDisplay:
    """Small drawing proxy that estimates host-to-device command bandwidth."""

    def __init__(self, display: RemoteDisplay) -> None:
        self._display = display
        self._meter = TransferMeter()

    @contextmanager
    def frame(self, **kwargs) -> Iterator["MeteredDisplay"]:
        self._meter.begin_frame()
        try:
            with self._display.frame(**kwargs):
                yield self
        finally:
            self._meter.end_frame()

    def performance_stats(self) -> PerformanceStats:
        return self._meter.stats()

    def clear(self, color: int) -> None:
        self._meter.record_payload(2)
        self._display.clear(color)

    def fill_rect(self, x: int, y: int, width: int, height: int, color: int) -> None:
        self._meter.record_payload(10)
        self._display.fill_rect(x, y, width, height, color)

    def stroke_rect(self, x: int, y: int, width: int, height: int, color: int, thickness: int = 1) -> None:
        self._meter.record_payload(12)
        self._display.stroke_rect(x, y, width, height, color, thickness)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: int, thickness: int = 1) -> None:
        self._meter.record_payload(12)
        self._display.line(x0, y0, x1, y1, color, thickness)

    def polyline(self, points: Sequence[tuple[int, int]], color: int, thickness: int = 1) -> None:
        self._meter.record_payload(4 + 4 * len(points))
        self._display.polyline(points, color, thickness)

    def scroll_rect(self, x: int, y: int, width: int, height: int, delta_x: int, delta_y: int, fill_color: int) -> None:
        self._meter.record_payload(14)
        self._display.scroll_rect(x, y, width, height, delta_x, delta_y, fill_color)

    def draw_device_text(self, text: str, x: int, y: int, color: int, *, font_id: int = 0, scale: int = 1) -> None:
        self._meter.record_payload(8 + len(text.encode("utf-8")))
        self._display.draw_device_text(text, x, y, color, font_id=font_id, scale=scale)


@dataclass
class ChartState:
    scale_signature: tuple[tuple[str, float, float], ...]
    history_seconds: float
    refresh_hz: float
    sample_id: int


class RemoteDashboardRenderer:
    def __init__(self, display: MeteredDisplay) -> None:
        self.display = display
        self.screen_key: str | None = None
        self.chart_states: dict[tuple[str, str], ChartState] = {}

    def render(self, model: DashboardModel) -> None:
        target = model.selected_category or "dashboard"
        screen_changed = target != self.screen_key
        with self.display.frame(timeout_ms=3000):
            if screen_changed:
                self.chart_states.clear()
                if target == "dashboard":
                    self._draw_dashboard_static()
                    self._draw_dashboard_dynamic(model, full_graphs=True)
                else:
                    category = category_by_key(model, target)
                    self._draw_fullscreen_static(category)
                    self._draw_fullscreen_dynamic(model, category, full_graph=True)
                self.screen_key = target
            elif target == "dashboard":
                self._draw_dashboard_dynamic(model, full_graphs=False)
            else:
                self._draw_fullscreen_dynamic(model, category_by_key(model, target), full_graph=False)

    def _draw_dashboard_static(self) -> None:
        display = self.display
        display.clear(BLACK)
        display.fill_rect(*PANEL_FRAME_RECT, PANEL)
        display.stroke_rect(*PANEL_FRAME_RECT, BORDER, 1)
        display.fill_rect(*FOOTER_RECT, PANEL_ALT)
        display.line(16, 80, 431, 80, BORDER, 1)
        display.line(16, HORIZONTAL_DIVIDER_Y, 431, HORIZONTAL_DIVIDER_Y, BORDER, 1)
        display.line(16, FOOTER_RECT[1], 431, FOOTER_RECT[1], BORDER, 1)
        display.line(VERTICAL_DIVIDER_X, 80, VERTICAL_DIVIDER_X, FOOTER_RECT[1] - 1, BORDER, 1)
        display.draw_device_text("SYSTEM DASHBOARD", 24, 24, WHITE)
        display.draw_device_text("TAP A CARD TO EXPAND", 24, 560, WHITE)

    def _draw_dashboard_dynamic(self, model: DashboardModel, *, full_graphs: bool) -> None:
        display = self.display
        snapshot = model.snapshot
        update_text(display, HEADER_DYNAMIC_RECTS["time"], snapshot.timestamp.strftime("%H:%M:%S"), WHITE, PANEL)
        update_text(display, HEADER_DYNAMIC_RECTS["date"], snapshot.timestamp.strftime("%Y-%m-%d"), MUTED, PANEL)
        update_text(display, HEADER_DYNAMIC_RECTS["uptime"], f"UP {fmt_duration(snapshot.uptime_s)}", MUTED, PANEL, align="right")
        update_text(display, HEADER_DYNAMIC_RECTS["network"], short_interface_line(snapshot.net_iface, snapshot.net_ip), WHITE, PANEL)
        perf = display.performance_stats()
        update_text(display, HEADER_DYNAMIC_RECTS["performance"], f"FPS {perf.fps:3.1f} USB {perf.usb_percent:3.1f}%", MUTED, PANEL, align="right")
        for category in model.categories():
            update_text(display, CARD_TITLE_RECTS[category.key], category.title, WHITE, PANEL)
            line1, line2 = CARD_TEXT_RECTS[category.key]
            update_text(display, line1, category.summary_lines[0], WHITE, PANEL)
            update_text(display, line2, category.summary_lines[1], MUTED, PANEL)
            self._update_chart("dashboard", category, category.plot_rect, model, full_graphs=full_graphs)

    def _draw_fullscreen_static(self, category: CategorySpec) -> None:
        display = self.display
        display.clear(BLACK)
        display.fill_rect(*PANEL_FRAME_RECT, PANEL)
        display.stroke_rect(*PANEL_FRAME_RECT, BORDER, 1)
        display.draw_device_text(f"{category.key.upper()} GRAPH", 24, 24, WHITE, scale=2)
        x, y, width, height = BACK_BUTTON_RECT
        display.fill_rect(x, y, width, height, PANEL_ALT)
        display.stroke_rect(x, y, width, height, BORDER, 1)
        display.draw_device_text("BACK", x + (width - device_text_pixel_width("BACK")) // 2, y + (height - 16) // 2, WHITE)
        display.fill_rect(*FULLSCREEN_LEGEND_RECT, PANEL_ALT)
        display.line(16, FULLSCREEN_LEGEND_RECT[1], 431, FULLSCREEN_LEGEND_RECT[1], BORDER, 1)

    def _draw_fullscreen_dynamic(self, model: DashboardModel, category: CategorySpec, *, full_graph: bool) -> None:
        line1, line2 = FULLSCREEN_SUMMARY_RECTS
        update_text(self.display, line1, category.summary_lines[0], WHITE, PANEL)
        update_text(self.display, line2, category.summary_lines[1], MUTED, PANEL)
        self._update_chart(category.key, category, FULLSCREEN_PLOT_RECT, model, full_graphs=full_graph)
        draw_fullscreen_legend(self.display, model, category.series)

    def _update_chart(self, screen_key: str, category: CategorySpec, plot_rect: Rect, model: DashboardModel, *, full_graphs: bool) -> None:
        if not category.series:
            draw_plot_empty(self.display, plot_rect)
            return
        state_key = (screen_key, category.key)
        signature = chart_scale_signature(category.series)
        previous = self.chart_states.get(state_key)
        needs_full = (
            full_graphs
            or previous is None
            or previous.scale_signature != signature
            or not math.isclose(previous.history_seconds, model.config.history_seconds)
            or not math.isclose(previous.refresh_hz, model.config.refresh_hz)
            or previous.sample_id != model.sample_id - 1
        )
        if needs_full:
            draw_plot_full(self.display, plot_rect, category.series, model)
        else:
            scroll = history_scroll_pixels(previous.sample_id, model.sample_id, plot_rect, model.config)
            # A newly sampled value can map to the existing rightmost pixel when
            # the selected history range has more samples than horizontal pixels.
            # Redraw the tail even when no whole-pixel scroll was due.
            draw_plot_incremental(self.display, plot_rect, category.series, model, scroll)
        self.chart_states[state_key] = ChartState(signature, model.config.history_seconds, model.config.refresh_hz, model.sample_id)


def category_by_key(model: DashboardModel, key: str) -> CategorySpec:
    for category in model.categories():
        if category.key == key:
            return category
    raise KeyError(key)


def update_text(display, rect: Rect, text: str, color: int, background: int, *, align: str = "left") -> None:
    x, y, width, height = rect
    display.fill_rect(x, y, width, height, background)
    text_x = x + width - device_text_pixel_width(text) if align == "right" else x
    display.draw_device_text(text[: width // 8], max(x, align8(text_x)), y, color)


def draw_fullscreen_legend(display, model: DashboardModel, series: Sequence[SeriesSpec]) -> None:
    # Fixed columns prevent a changing RX value width from moving the TX column.
    for rect in FULLSCREEN_LEGEND_VALUE_RECTS:
        display.fill_rect(*rect, PANEL_ALT)
    for spec, rect in zip(series, FULLSCREEN_LEGEND_VALUE_RECTS):
        x, y, width, _ = rect
        text = f"{compact_legend_label(spec.label)} {spec.formatter(model.history[spec.key][-1])}"
        display.draw_device_text(text[: width // 8], x, y, spec.color)


def compact_legend_label(label: str) -> str:
    return {
        "Usage": "USE",
        "Used": "USE",
        "Available": "AVL",
        "Swap": "SWP",
        "Activity": "ACT",
        "Temp": "TMP",
        "Freq": "FRQ",
    }.get(label, label.upper())


def chart_scale_signature(series: Sequence[SeriesSpec]) -> tuple[tuple[str, float, float], ...]:
    return tuple((spec.key, float(spec.min_value), float(spec.max_value if spec.max_value is not None else spec.min_value + 1.0)) for spec in series)


def draw_plot_empty(display, rect: Rect) -> None:
    x, y, width, height = rect
    display.fill_rect(x, y, width, height, SURFACE)
    display.stroke_rect(x, y, width, height, GRID, 1)
    display.draw_device_text("NO DISK METRICS", x + 16, y + height // 2 - 8, MUTED_DARK)


def series_points_for_chart(
    model: DashboardModel,
    spec: SeriesSpec,
    rect: Rect,
) -> list[tuple[int, int]]:
    data_x, data_y, data_width, data_height = plot_data_rect(rect)
    return build_series_points(
        history_window_values(model, spec.key),
        spec,
        data_x,
        data_y,
        data_width,
        data_height,
        model.config.history_sample_count(),
    )


def draw_plot_full(display, rect: Rect, series: Sequence[SeriesSpec], model: DashboardModel) -> None:
    x, y, width, height = rect
    display.fill_rect(x, y, width, height, SURFACE)
    display.stroke_rect(x, y, width, height, GRID, 1)
    draw_horizontal_guides(display, rect)
    for spec in series:
        draw_polyline_segments(display, series_points_for_chart(model, spec, rect), spec.color)


def draw_plot_incremental(
    display,
    rect: Rect,
    series: Sequence[SeriesSpec],
    model: DashboardModel,
    scroll: int,
) -> None:
    data_x, data_y, data_width, data_height = plot_data_rect(rect)
    scroll = min(max(0, scroll), data_width)
    right_x = data_x + data_width - 1

    if scroll:
        display.scroll_rect(data_x, data_y, data_width, data_height, -scroll, 0, SURFACE)
        dirty_x = data_x + data_width - scroll
        dirty_width = scroll
    else:
        # No horizontal pixel crossed this sample. The newest point can still
        # replace the value collapsed into the rightmost plot column, so clear
        # and redraw a small tail without shifting the chart.
        dirty_width = min(2, data_width)
        dirty_x = right_x - dirty_width + 1

    display.fill_rect(dirty_x, data_y, dirty_width, data_height, SURFACE)

    # Keep the one-pixel guard rows clean so prior trace pixels cannot survive
    # at either plot edge after an incremental update.
    top_x, top_y, top_width, top_height = plot_top_guard_rect(rect)
    display.fill_rect(top_x, top_y, top_width, top_height, SURFACE)
    bottom_x, bottom_y, bottom_width, bottom_height = plot_bottom_guard_rect(rect)
    display.fill_rect(bottom_x, bottom_y, bottom_width, bottom_height, SURFACE)
    redraw_plot_guide_strip(display, rect, dirty_x, dirty_width)

    for spec in series:
        points = series_points_for_chart(model, spec, rect)
        draw_plot_tail(display, points, spec.color, dirty_x)


def draw_plot_tail(display, points: Sequence[tuple[int, int]], color: int, dirty_x: int) -> None:
    """Redraw the connected part of a trace intersecting the changed tail.

    `build_series_points` collapses multiple samples landing in one pixel column.
    Selecting the predecessor of the first changed column preserves the joining
    segment, including when the newest sample remains in the rightmost column.
    """
    if len(points) < 2:
        return
    start_index = 0
    for index, (point_x, _) in enumerate(points):
        if point_x >= dirty_x:
            start_index = max(0, index - 1)
            break
    else:
        return
    draw_polyline_segments(display, points[start_index:], color)


def draw_polyline_segments(display, points: Sequence[tuple[int, int]], color: int) -> None:
    if len(points) < 2:
        return
    start = 0
    while start < len(points) - 1:
        chunk = points[start:start + 255]
        if len(chunk) >= 2:
            display.polyline(chunk, color, 1)
        start += 254


def history_window_values(model: DashboardModel, key: str) -> list[float]:
    return list(model.history[key])[-model.config.history_sample_count():]


def history_scroll_pixels(previous_sample_id: int, current_sample_id: int, rect: Rect, config: MonitorConfig) -> int:
    _, _, data_width, _ = plot_data_rect(rect)
    span_samples = max(1, config.history_sample_count() - 1)
    previous_offset = math.floor(previous_sample_id * data_width / span_samples)
    current_offset = math.floor(current_sample_id * data_width / span_samples)
    return max(0, current_offset - previous_offset)


def draw_horizontal_guides(display, rect: Rect) -> None:
    x, y, width, height = rect
    for division in range(1, 4):
        guide_y = y + (height * division) // 4
        display.line(x + 1, guide_y, x + width - 2, guide_y, GRID, 1)


def redraw_plot_guide_strip(display, rect: Rect, left: int, width: int) -> None:
    x, y, plot_width, height = rect
    data_x, _, data_width, _ = plot_data_rect(rect)
    strip_left = max(data_x, left)
    strip_right = min(data_x + data_width - 1, left + width - 1)
    if strip_left > strip_right:
        return
    for division in range(1, 4):
        guide_y = y + (height * division) // 4
        display.line(strip_left, guide_y, strip_right, guide_y, GRID, 1)


def plot_inner_rect(rect: Rect) -> Rect:
    x, y, width, height = rect
    if width < 4 or height < 6:
        raise ValueError("plot rectangle must leave a one-pixel border plus top and bottom guard rows")
    return x + 1, y + 1, width - 2, height - 2


def plot_data_rect(rect: Rect) -> Rect:
    x, y, width, height = plot_inner_rect(rect)
    return x, y + 1, width, height - 2


def plot_top_guard_rect(rect: Rect) -> Rect:
    x, y, width, _ = plot_inner_rect(rect)
    return x, y, width, 1


def plot_bottom_guard_rect(rect: Rect) -> Rect:
    x, y, width, height = plot_inner_rect(rect)
    return x, y + height - 1, width, 1


def build_series_points(
    values: Sequence[float],
    spec: SeriesSpec,
    x: int,
    y: int,
    width: int,
    height: int,
    expected_samples: int,
) -> list[tuple[int, int]]:
    if not values:
        return []
    expected_samples = max(2, expected_samples)
    offset = max(0, expected_samples - len(values))
    collapsed: dict[int, float] = {}
    for index, value in enumerate(values):
        sample_index = offset + index
        point_x = x + round((width - 1) * sample_index / (expected_samples - 1))
        collapsed[point_x] = value
    return [(point_x, scale_value_to_y(value, spec, y, height)) for point_x, value in sorted(collapsed.items())]


def scale_value_to_y(value: float, spec: SeriesSpec, y: int, height: int) -> int:
    lower = spec.min_value
    upper = spec.max_value if spec.max_value is not None else max(value, lower + 1.0)
    if math.isclose(lower, upper):
        upper = lower + 1.0
    normalized = max(0.0, min(1.0, (value - lower) / (upper - lower)))
    return y + height - 1 - round(normalized * (height - 1))


def contains(rect: Rect, x: int, y: int) -> bool:
    rect_x, rect_y, rect_w, rect_h = rect
    return rect_x <= x < rect_x + rect_w and rect_y <= y < rect_y + rect_h


def run() -> None:
    if fcntl is None:
        raise SystemExit("This example currently requires Linux.")
    config = default_monitor_config()
    if sys.stdin.isatty():
        config = configure_dashboard(config)
    print("Opening Pico-rendered dashboard.")
    print_console_controls()
    model = DashboardModel(config)
    next_sample = time.monotonic() + config.sample_interval_s
    last_pressed = False

    with RemoteDisplay.open(timeout_ms=2000) as raw_display:
        raw_display.set_brightness(65)
        raw_display.device_font_info()
        renderer = RemoteDashboardRenderer(MeteredDisplay(raw_display))
        renderer.render(model)

        while True:
            command = read_console_command()
            if command:
                if command == "m":
                    config = configure_dashboard(config)
                    model = DashboardModel(config)
                    renderer.screen_key = None
                    renderer.chart_states.clear()
                    next_sample = time.monotonic() + config.sample_interval_s
                    renderer.render(model)
                    print_console_controls()
                    continue
                if command == "s":
                    print_monitor_status(config, model)
                elif command in {"q", "quit", "exit"}:
                    print("Pico-rendered dashboard stopped.")
                    return
                else:
                    print("Unknown command. Use m, s, q, or Ctrl+C.")

            now = time.monotonic()
            wait_s = max(0.0, min(0.010, next_sample - now))
            event = raw_display.poll_latest_touch(timeout_ms=max(0, round(wait_s * 1000)))
            if event is not None:
                if event.pressed and not last_pressed:
                    if model.selected_category is None:
                        for category in model.categories():
                            if contains(category.rect, event.x, event.y):
                                model.selected_category = category.key
                                renderer.render(model)
                                break
                    elif contains(BACK_BUTTON_RECT, event.x, event.y):
                        model.selected_category = None
                        renderer.render(model)
                last_pressed = event.pressed

            now = time.monotonic()
            if now >= next_sample:
                model.update()
                while next_sample <= now:
                    next_sample += config.sample_interval_s
                renderer.render(model)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nPico-rendered dashboard stopped.")
