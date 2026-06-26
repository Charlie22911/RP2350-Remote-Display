"""Interactive host-side system dashboard demo.

This example samples Linux host metrics and renders them on the remote display
with a host-composed ``Canvas`` presented through ``DirtyTilePresenter``.
Touch a graph card to expand it. In the fullscreen graph view, use the Back
button to return to the dashboard.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import time
from typing import Callable, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux-only fallback
    fcntl = None

from rp2350_remote_display import Canvas, DirtyTilePresenter, RemoteDisplay, rgb565

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

PADDING = 18
CARD_GAP = 18
HEADER_H = 82
CARD_W = (450 - PADDING * 2 - CARD_GAP) // 2
CARD_H = 178
FOOTER_H = 88
SAMPLE_INTERVAL_S = 0.5
MAX_HISTORY = 90


Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class Snapshot:
    timestamp: datetime
    uptime_s: float
    cpu_usage_percent: float
    cpu_temp_c: float | None
    cpu_freq_mhz: float | None
    cpu_max_freq_mhz: float | None
    ram_used_percent: float
    ram_used_gib: float
    ram_total_gib: float
    disk_used_percent: float
    disk_used_gib: float
    disk_total_gib: float
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
    summary_lines: tuple[str, str]
    series: tuple[SeriesSpec, ...]


class CpuSampler:
    def __init__(self) -> None:
        self._previous_total: int | None = None
        self._previous_idle: int | None = None
        self.max_freq_mhz = self._read_max_freq_mhz()

    def sample_usage_percent(self) -> float:
        contents = safe_read_text("/proc/stat")
        if not contents:
            return 0.0
        try:
            fields = [int(field) for field in contents.splitlines()[0].split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            total = sum(fields)
        except (IndexError, ValueError):
            return 0.0
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
        busy = 1.0 - (idle_delta / total_delta)
        return max(0.0, min(100.0, busy * 100.0))

    def sample_freq_mhz(self) -> float | None:
        candidates = [
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
            "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq",
        ]
        for candidate in candidates:
            value = safe_read_text(candidate)
            if value is None:
                continue
            try:
                return float(value.strip()) / 1000.0
            except ValueError:
                continue
        mhz_values: list[float] = []
        cpuinfo = safe_read_text("/proc/cpuinfo")
        if cpuinfo is None:
            return None
        for line in cpuinfo.splitlines():
            if line.lower().startswith("cpu mhz"):
                try:
                    mhz_values.append(float(line.split(":", 1)[1].strip()))
                except (IndexError, ValueError):
                    pass
        if mhz_values:
            return sum(mhz_values) / len(mhz_values)
        return None

    def sample_temp_c(self) -> float | None:
        zones = Path("/sys/class/thermal")
        if not zones.is_dir():
            return None
        preferred: list[float] = []
        fallback: list[float] = []
        for zone in sorted(zones.glob("thermal_zone*")):
            temp_path = zone / "temp"
            if not temp_path.is_file():
                continue
            raw_text = safe_read_text(temp_path)
            if raw_text is None:
                continue
            try:
                raw = float(raw_text.strip())
            except ValueError:
                continue
            temp_c = raw / 1000.0 if raw > 1000 else raw
            if not (0.0 <= temp_c <= 150.0):
                continue
            zone_type = safe_read_text(zone / "type")
            zone_type = zone_type.strip().lower() if zone_type is not None else ""
            if any(token in zone_type for token in ("cpu", "package", "soc", "x86_pkg_temp", "tctl", "core")):
                preferred.append(temp_c)
            else:
                fallback.append(temp_c)
        if preferred:
            return max(preferred)
        if fallback:
            return max(fallback)
        return None

    @staticmethod
    def _read_max_freq_mhz() -> float | None:
        candidates = [
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq",
            "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq",
        ]
        for candidate in candidates:
            value = safe_read_text(candidate)
            if value is None:
                continue
            try:
                return float(value.strip()) / 1000.0
            except ValueError:
                continue
        return None


class NetworkSampler:
    def __init__(self) -> None:
        self._previous_rx: int | None = None
        self._previous_tx: int | None = None
        self._previous_time: float | None = None

    def sample(self) -> tuple[str | None, str | None, float, float]:
        iface = primary_interface()
        ip = interface_ip(iface)
        if iface is None:
            self._previous_rx = None
            self._previous_tx = None
            self._previous_time = None
            return None, ip, 0.0, 0.0
        stats_root = Path("/sys/class/net") / iface / "statistics"
        rx_text = safe_read_text(stats_root / "rx_bytes")
        tx_text = safe_read_text(stats_root / "tx_bytes")
        try:
            rx = int(rx_text) if rx_text is not None else 0
            tx = int(tx_text) if tx_text is not None else 0
        except ValueError:
            return iface, ip, 0.0, 0.0
        now = time.monotonic()
        if self._previous_time is None or self._previous_rx is None or self._previous_tx is None:
            self._previous_rx = rx
            self._previous_tx = tx
            self._previous_time = now
            return iface, ip, 0.0, 0.0
        elapsed = max(now - self._previous_time, 1e-6)
        rx_bps = max(0.0, (rx - self._previous_rx) * 8.0 / elapsed)
        tx_bps = max(0.0, (tx - self._previous_tx) * 8.0 / elapsed)
        self._previous_rx = rx
        self._previous_tx = tx
        self._previous_time = now
        return iface, ip, rx_bps, tx_bps


class SystemSampler:
    def __init__(self) -> None:
        self.cpu = CpuSampler()
        self.network = NetworkSampler()

    def sample(self) -> Snapshot:
        timestamp = datetime.now().astimezone()
        uptime_s = read_uptime_seconds()
        ram_total_kib, ram_available_kib = read_memory_snapshot_kib()
        ram_used_kib = max(0, ram_total_kib - ram_available_kib)
        ram_total_gib = kib_to_gib(ram_total_kib)
        ram_used_gib = kib_to_gib(ram_used_kib)
        ram_used_percent = percent(ram_used_kib, ram_total_kib)

        try:
            stat = os.statvfs("/")
            disk_total_bytes = stat.f_frsize * stat.f_blocks
            disk_free_bytes = stat.f_frsize * stat.f_bavail
        except OSError:
            disk_total_bytes = 0
            disk_free_bytes = 0
        disk_used_bytes = max(0, disk_total_bytes - disk_free_bytes)
        disk_total_gib = bytes_to_gib(disk_total_bytes)
        disk_used_gib = bytes_to_gib(disk_used_bytes)
        disk_used_percent = percent(disk_used_bytes, disk_total_bytes)

        iface, ip, rx_bps, tx_bps = self.network.sample()

        return Snapshot(
            timestamp=timestamp,
            uptime_s=uptime_s,
            cpu_usage_percent=self.cpu.sample_usage_percent(),
            cpu_temp_c=self.cpu.sample_temp_c(),
            cpu_freq_mhz=self.cpu.sample_freq_mhz(),
            cpu_max_freq_mhz=self.cpu.max_freq_mhz,
            ram_used_percent=ram_used_percent,
            ram_used_gib=ram_used_gib,
            ram_total_gib=ram_total_gib,
            disk_used_percent=disk_used_percent,
            disk_used_gib=disk_used_gib,
            disk_total_gib=disk_total_gib,
            net_iface=iface,
            net_ip=ip,
            net_rx_bps=rx_bps,
            net_tx_bps=tx_bps,
        )


class DashboardModel:
    def __init__(self) -> None:
        self.sampler = SystemSampler()
        self.snapshot = self.sampler.sample()
        self.history: dict[str, deque[float]] = {
            "cpu_usage": deque([self.snapshot.cpu_usage_percent], maxlen=MAX_HISTORY),
            "cpu_temp": deque([self.snapshot.cpu_temp_c if self.snapshot.cpu_temp_c is not None else 0.0], maxlen=MAX_HISTORY),
            "cpu_freq": deque([self.snapshot.cpu_freq_mhz if self.snapshot.cpu_freq_mhz is not None else 0.0], maxlen=MAX_HISTORY),
            "ram_used_percent": deque([self.snapshot.ram_used_percent], maxlen=MAX_HISTORY),
            "disk_used_percent": deque([self.snapshot.disk_used_percent], maxlen=MAX_HISTORY),
            "net_rx": deque([self.snapshot.net_rx_bps], maxlen=MAX_HISTORY),
            "net_tx": deque([self.snapshot.net_tx_bps], maxlen=MAX_HISTORY),
        }
        self.selected_category: str | None = None

    def update(self) -> None:
        self.snapshot = self.sampler.sample()
        self.history["cpu_usage"].append(self.snapshot.cpu_usage_percent)
        self.history["cpu_temp"].append(self.snapshot.cpu_temp_c if self.snapshot.cpu_temp_c is not None else 0.0)
        self.history["cpu_freq"].append(self.snapshot.cpu_freq_mhz if self.snapshot.cpu_freq_mhz is not None else 0.0)
        self.history["ram_used_percent"].append(self.snapshot.ram_used_percent)
        self.history["disk_used_percent"].append(self.snapshot.disk_used_percent)
        self.history["net_rx"].append(self.snapshot.net_rx_bps)
        self.history["net_tx"].append(self.snapshot.net_tx_bps)

    def categories(self) -> tuple[CategorySpec, ...]:
        top = PADDING + HEADER_H + CARD_GAP
        left = PADDING
        right = PADDING + CARD_W + CARD_GAP
        bottom = top + CARD_H + CARD_GAP
        snap = self.snapshot
        freq_limit = snap.cpu_max_freq_mhz or max(1000.0, max(self.history["cpu_freq"], default=0.0) * 1.15)
        net_peak = max(1_000_000.0, max(self.history["net_rx"], default=0.0), max(self.history["net_tx"], default=0.0)) * 1.2
        return (
            CategorySpec(
                key="cpu",
                title="CPU",
                rect=(left, top, CARD_W, CARD_H),
                summary_lines=(
                    f"Usage {snap.cpu_usage_percent:4.1f}%",
                    f"Temp {fmt_optional_celsius(snap.cpu_temp_c)}   Freq {fmt_optional_freq(snap.cpu_freq_mhz)}",
                ),
                series=(
                    SeriesSpec("cpu_usage", "Usage", ACCENT, 0.0, 100.0, lambda value: f"{value:4.1f}%"),
                    SeriesSpec("cpu_temp", "Temp", ORANGE, 0.0, 100.0, fmt_celsius),
                    SeriesSpec("cpu_freq", "Freq", GREEN, 0.0, freq_limit, fmt_mhz_or_ghz),
                ),
            ),
            CategorySpec(
                key="memory",
                title="Memory",
                rect=(right, top, CARD_W, CARD_H),
                summary_lines=(
                    f"Used {fmt_storage_gib(snap.ram_used_gib)} / {fmt_storage_gib(snap.ram_total_gib)}",
                    f"Pressure {snap.ram_used_percent:4.1f}%",
                ),
                series=(
                    SeriesSpec("ram_used_percent", "RAM used", PURPLE, 0.0, 100.0, lambda value: f"{value:4.1f}%"),
                ),
            ),
            CategorySpec(
                key="disk",
                title="Disk",
                rect=(left, bottom, CARD_W, CARD_H),
                summary_lines=(
                    f"Root usage {snap.disk_used_percent:4.1f}%",
                    f"Used {fmt_storage_gib(snap.disk_used_gib)} / {fmt_storage_gib(snap.disk_total_gib)}",
                ),
                series=(
                    SeriesSpec("disk_used_percent", "Disk used", YELLOW, 0.0, 100.0, lambda value: f"{value:4.1f}%"),
                ),
            ),
            CategorySpec(
                key="network",
                title="Network",
                rect=(right, bottom, CARD_W, CARD_H),
                summary_lines=(
                    shorten_text(f"{snap.net_iface or 'net'}  {snap.net_ip or 'offline'}", 25),
                    f"RX {fmt_bps(snap.net_rx_bps)}   TX {fmt_bps(snap.net_tx_bps)}",
                ),
                series=(
                    SeriesSpec("net_rx", "RX", BLUE, 0.0, net_peak, fmt_bps),
                    SeriesSpec("net_tx", "TX", RED, 0.0, net_peak, fmt_bps),
                ),
            ),
        )


def safe_read_text(path: str | Path) -> str | None:
    """Return UTF-8 file contents, or ``None`` when a Linux metric is unavailable."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_uptime_seconds() -> float:
    contents = safe_read_text("/proc/uptime")
    if not contents:
        return 0.0
    try:
        return float(contents.split()[0])
    except (IndexError, ValueError):
        return 0.0


def read_memory_snapshot_kib() -> tuple[int, int]:
    """Return total and available Linux memory, with an older-kernel fallback."""
    contents = safe_read_text("/proc/meminfo")
    if not contents:
        return 0, 0
    fields: dict[str, int] = {}
    for line in contents.splitlines():
        name, separator, remainder = line.partition(":")
        if not separator:
            continue
        parts = remainder.split()
        if not parts:
            continue
        try:
            fields[name] = int(parts[0])
        except ValueError:
            continue
    total = fields.get("MemTotal", 0)
    available = fields.get("MemAvailable")
    if available is None:
        available = sum(
            fields.get(name, 0)
            for name in ("MemFree", "Buffers", "Cached", "SReclaimable")
        )
    return max(0, total), max(0, min(available, total))


def primary_interface() -> str | None:
    route_contents = safe_read_text("/proc/net/route")
    if route_contents:
        for line in route_contents.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4 or fields[1] != "00000000":
                continue
            try:
                route_flags = int(fields[3], 16)
            except ValueError:
                continue
            if route_flags & 2:
                return fields[0]

    net_class = Path("/sys/class/net")
    if not net_class.is_dir():
        return None
    for iface in sorted(net_class.iterdir()):
        if iface.name == "lo":
            continue
        state = safe_read_text(iface / "operstate")
        if state is not None and state.strip() == "up":
            return iface.name
    return None


def interface_ip(iface: str | None) -> str | None:
    """Return a primary address while tolerating minimal Linux installations.

    Arch and Debian-family systems normally provide ``ip`` through iproute2,
    which gives the most reliable result in containers and network namespaces.
    The ioctl and procfs fallbacks keep the dashboard useful when that command
    is absent or unavailable.
    """
    if not iface:
        return None

    ipv4 = interface_ipv4_from_ip_command(iface)
    if ipv4 is not None:
        return ipv4

    if fcntl is not None:
        try:
            encoded_name = iface.encode("utf-8")[:15]
            # SIOCGIFADDR expects a full ifreq-sized buffer. Supplying only the
            # 16-byte name is accepted by some Python/Linux combinations but
            # raises SystemError: buffer overflow on others.
            ifreq = struct.pack("256s", encoded_name)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                result = fcntl.ioctl(sock.fileno(), 0x8915, ifreq)
            if len(result) >= 24:
                return socket.inet_ntoa(result[20:24])
        except (OSError, SystemError, UnicodeError, ValueError):
            pass

    return interface_ipv6(iface)


def interface_ipv4_from_ip_command(iface: str) -> str | None:
    ip_command = shutil.which("ip")
    if ip_command is None:
        return None
    try:
        result = subprocess.run(
            [ip_command, "-4", "-o", "addr", "show", "dev", iface, "scope", "global"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        try:
            address = fields[fields.index("inet") + 1].split("/", 1)[0]
            socket.inet_aton(address)
        except (IndexError, ValueError, OSError):
            continue
        return address
    return None


def interface_ipv6(iface: str) -> str | None:
    """Use the first non-link-local IPv6 address as a last-resort display value."""
    contents = safe_read_text("/proc/net/if_inet6")
    if not contents:
        return None
    candidates: list[str] = []
    for line in contents.splitlines():
        fields = line.split()
        if len(fields) != 6 or fields[5] != iface:
            continue
        hex_address = fields[0]
        if len(hex_address) != 32:
            continue
        try:
            groups = [hex_address[index:index + 4] for index in range(0, 32, 4)]
            address = ":".join(groups)
            packed = socket.inet_pton(socket.AF_INET6, address)
            formatted = socket.inet_ntop(socket.AF_INET6, packed)
        except OSError:
            continue
        if not formatted.lower().startswith("fe80:"):
            return formatted
        candidates.append(formatted)
    return candidates[0] if candidates else None


def bytes_to_gib(value: int) -> float:
    return value / (1024 ** 3)


def kib_to_gib(value: int) -> float:
    return value / (1024 ** 2)


def percent(part: int | float, total: int | float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (part / total) * 100.0))


def shorten_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 3)] + "..."


def fmt_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def fmt_bps(bits_per_second: float) -> str:
    value = max(0.0, bits_per_second)
    units = ("bps", "Kbps", "Mbps", "Gbps")
    unit_index = 0
    while value >= 1000.0 and unit_index < len(units) - 1:
        value /= 1000.0
        unit_index += 1
    if unit_index == 0:
        return f"{value:4.0f} {units[unit_index]}"
    if value >= 100:
        return f"{value:4.0f} {units[unit_index]}"
    if value >= 10:
        return f"{value:4.1f} {units[unit_index]}"
    return f"{value:4.2f} {units[unit_index]}"


def fmt_celsius(value: float) -> str:
    return f"{value:4.1f} C"


def fmt_optional_celsius(value: float | None) -> str:
    return "n/a" if value is None else fmt_celsius(value)


def fmt_mhz_or_ghz(value: float) -> str:
    if value >= 1000.0:
        return f"{value / 1000.0:4.2f} GHz"
    return f"{value:4.0f} MHz"


def fmt_storage_gib(value_gib: float) -> str:
    if value_gib >= 1024.0:
        return f"{value_gib / 1024.0:4.1f} TiB"
    return f"{value_gib:4.1f} GiB"


def fmt_optional_freq(value: float | None) -> str:
    return "n/a" if value is None else fmt_mhz_or_ghz(value)


def contains(rect: Rect, x: int, y: int) -> bool:
    rect_x, rect_y, rect_w, rect_h = rect
    return rect_x <= x < rect_x + rect_w and rect_y <= y < rect_y + rect_h


def render_dashboard(model: DashboardModel) -> Canvas:
    canvas = Canvas(background=BLACK)
    draw_header(canvas, model.snapshot)
    for category in model.categories():
        draw_card(canvas, model, category)
    draw_footer(canvas)
    return canvas


def draw_header(canvas: Canvas, snapshot: Snapshot) -> None:
    canvas.fill_rect(PADDING, PADDING, 450 - PADDING * 2, HEADER_H, PANEL)
    canvas.stroke_rect(PADDING, PADDING, 450 - PADDING * 2, HEADER_H, BORDER, 2)
    canvas.text("System dashboard", PADDING + 16, PADDING + 12, WHITE, size=18)
    canvas.text(snapshot.timestamp.strftime("%H:%M:%S"), 450 - PADDING - 86, PADDING + 12, WHITE, size=18)
    canvas.text(snapshot.timestamp.strftime("%Y-%m-%d"), PADDING + 16, PADDING + 34, MUTED, size=12)
    canvas.text(f"Uptime {fmt_duration(snapshot.uptime_s)}", PADDING + 128, PADDING + 34, MUTED, size=12)
    iface_text = snapshot.net_iface or "net"
    ip_text = snapshot.net_ip or "offline"
    canvas.text(shorten_text(f"{iface_text}  {ip_text}", 37), PADDING + 16, PADDING + 56, WHITE, size=13)
    canvas.text("Live host metrics", 450 - PADDING - 108, PADDING + 56, MUTED, size=12)


def draw_footer(canvas: Canvas) -> None:
    footer_y = 600 - PADDING - FOOTER_H
    canvas.fill_rect(PADDING, footer_y, 450 - PADDING * 2, FOOTER_H, PANEL_ALT)
    canvas.stroke_rect(PADDING, footer_y, 450 - PADDING * 2, FOOTER_H, BORDER, 2)
    canvas.text("Tap a graph card to expand it", PADDING + 16, footer_y + 16, WHITE, size=14)
    canvas.text("Use Back to return from fullscreen.", PADDING + 16, footer_y + 40, MUTED, size=12)


def draw_card(canvas: Canvas, model: DashboardModel, category: CategorySpec) -> None:
    x, y, width, height = category.rect
    canvas.fill_rect(x, y, width, height, PANEL)
    canvas.stroke_rect(x, y, width, height, BORDER, 2)
    canvas.text(category.title, x + 14, y + 12, WHITE, size=16)
    canvas.text(category.summary_lines[0], x + 14, y + 36, WHITE, size=13)
    canvas.text(category.summary_lines[1], x + 14, y + 54, MUTED, size=12)
    draw_multi_series_chart(
        canvas,
        model,
        category.series,
        x + 12,
        y + 82,
        width - 24,
        height - 116,
        background=SURFACE,
        border=GRID,
        line_thickness=2,
    )
    canvas.text("Touch to expand", x + 14, y + height - 22, MUTED_DARK, size=11)


def render_fullscreen_category(model: DashboardModel, category: CategorySpec) -> Canvas:
    canvas = Canvas(background=BLACK)
    canvas.fill_rect(PADDING, PADDING, 450 - PADDING * 2, 600 - PADDING * 2, PANEL)
    canvas.stroke_rect(PADDING, PADDING, 450 - PADDING * 2, 600 - PADDING * 2, BORDER, 2)

    canvas.text(f"{category.title} graph", PADDING + 16, PADDING + 14, WHITE, size=18)
    canvas.text(category.summary_lines[0], PADDING + 16, PADDING + 40, WHITE, size=13)
    canvas.text(category.summary_lines[1], PADDING + 16, PADDING + 58, MUTED, size=12)

    back_rect = back_button_rect()
    canvas.button(
        back_rect[0],
        back_rect[1],
        back_rect[2],
        back_rect[3],
        "Back",
        background=PANEL_ALT,
        border=BORDER,
        text_color=WHITE,
        font_size=14,
    )

    chart_x = PADDING + 16
    chart_y = PADDING + 92
    chart_w = 450 - PADDING * 2 - 32
    chart_h = 600 - PADDING * 2 - 190
    draw_multi_series_chart(
        canvas,
        model,
        category.series,
        chart_x,
        chart_y,
        chart_w,
        chart_h,
        background=SURFACE,
        border=GRID,
        line_thickness=3,
        show_time_ticks=True,
    )

    legend_y = chart_y + chart_h + 16
    draw_legend(canvas, model, category.series, PADDING + 16, legend_y, chart_w, 74)
    return canvas


def draw_multi_series_chart(
    canvas: Canvas,
    model: DashboardModel,
    series: Sequence[SeriesSpec],
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    background: int,
    border: int,
    line_thickness: int,
    show_time_ticks: bool = False,
) -> None:
    canvas.fill_rect(x, y, width, height, background)
    canvas.stroke_rect(x, y, width, height, border, 1)
    for division in range(1, 4):
        grid_y = y + (height * division) // 4
        canvas.line(x + 1, grid_y, x + width - 2, grid_y, border, 1)
    if show_time_ticks:
        for division in range(1, 4):
            grid_x = x + (width * division) // 4
            canvas.line(grid_x, y + 1, grid_x, y + height - 2, border, 1)

    plot_x0 = x + 4
    plot_y0 = y + 4
    plot_w = width - 8
    plot_h = height - 8

    for spec in series:
        values = list(model.history[spec.key])
        points = build_series_points(values, spec, plot_x0, plot_y0, plot_w, plot_h)
        if len(points) >= 2:
            canvas.polyline(points, spec.color, line_thickness)



def build_series_points(values: Sequence[float], spec: SeriesSpec, x: int, y: int, width: int, height: int) -> list[tuple[int, int]]:
    if len(values) < 2:
        return []
    lower = spec.min_value
    upper = spec.max_value if spec.max_value is not None else max(max(values), lower + 1.0)
    if math.isclose(lower, upper):
        upper = lower + 1.0
    points: list[tuple[int, int]] = []
    for index, value in enumerate(values):
        px = x + (width - 1) * index // max(1, len(values) - 1)
        normalized = (value - lower) / (upper - lower)
        normalized = max(0.0, min(1.0, normalized))
        py = y + height - 1 - round(normalized * (height - 1))
        points.append((px, py))
    return points


def draw_legend(canvas: Canvas, model: DashboardModel, series: Sequence[SeriesSpec], x: int, y: int, width: int, height: int) -> None:
    canvas.fill_rect(x, y, width, height, PANEL_ALT)
    canvas.stroke_rect(x, y, width, height, BORDER, 1)
    row_height = max(22, height // max(1, len(series)))
    for index, spec in enumerate(series):
        row_y = y + 7 + index * row_height
        current = model.history[spec.key][-1]
        canvas.fill_rect(x + 12, row_y + 3, 12, 12, spec.color)
        canvas.text(spec.label, x + 32, row_y, WHITE, size=13)
        canvas.text(spec.formatter(current), x + 160, row_y, MUTED, size=13)
    canvas.text("Newest values at right edge", x + width - 170, y + height - 22, MUTED_DARK, size=11)


def back_button_rect() -> Rect:
    return (450 - PADDING - 88, PADDING + 14, 72, 30)


def run() -> None:
    print("Opening RP2350 Remote Display system dashboard. Press Ctrl+C to stop.")
    model = DashboardModel()
    dirty = True
    next_sample_time = time.monotonic() + SAMPLE_INTERVAL_S
    last_pressed = False

    with RemoteDisplay.open(timeout_ms=2000) as display:
        display.set_brightness(65)
        presenter = DirtyTilePresenter(display, tile_profile="small", compression="auto")

        while True:
            event = display.poll_latest_touch(timeout_ms=20)
            if event is not None:
                if event.pressed and not last_pressed:
                    if model.selected_category is None:
                        for category in model.categories():
                            if contains(category.rect, event.x, event.y):
                                model.selected_category = category.key
                                dirty = True
                                break
                    else:
                        if contains(back_button_rect(), event.x, event.y):
                            model.selected_category = None
                            dirty = True
                last_pressed = event.pressed

            now = time.monotonic()
            if now >= next_sample_time:
                model.update()
                next_sample_time += SAMPLE_INTERVAL_S
                dirty = True

            if not dirty:
                continue

            if model.selected_category is None:
                canvas = render_dashboard(model)
            else:
                category = next(spec for spec in model.categories() if spec.key == model.selected_category)
                canvas = render_fullscreen_category(model, category)
            presenter.present(canvas.rgb565_bytes())
            dirty = False


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
