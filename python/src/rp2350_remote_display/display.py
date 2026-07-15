from __future__ import annotations

from collections import deque
import errno
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import struct
import sys
import time
from typing import Iterable, Iterator, Sequence

from .protocol import (
    BLIT_TILE_STRUCT,
    CAP_ALPHA8_TILES,
    CAP_BRIGHTNESS,
    CAP_CANVAS_CRC32,
    CAP_DIRTY_TILE_PRESENT,
    CAP_RESOURCE_CACHE,
    CAP_PALETTE4_TILES,
    CAP_PALETTE64_TILES,
    CAP_ASYNC_PRESENT,
    CAP_TOUCH_COALESCING,
    CAP_DEVICE_TEXT,
    CAP_COPY_RECT,
    CAP_SCROLL_RECT,
    CAP_RTC_PCF85063,
    CAP_RGB565_SCALE2,
    CAP_PALETTE4_SCALE2,
    CAP_PALETTE64_SCALE2,
    CAP_OPTIONAL_PACKET_CRC32,
    CAP_OPTIONAL_TILE_CRC32,
    CAP_FRAME_TRANSACTIONS,
    CAP_PRIMITIVES,
    CAP_RGB565_TILES,
    CAP_RLE,
    CAP_SEGMENTED_TILES,
    CAP_SESSION_REATTACH,
    CAP_TILE_PROFILES,
    CAP_TOUCH_EVENTS,
    CODEC_RAW,
    CODEC_RLE,
    CODEC_PALETTE4,
    CODEC_PALETTE64,
    HELLO_REPLY_STRUCT,
    MAX_ENCODED_TILE_BYTES,
    MAX_PAYLOAD,
    PACKET_FLAG_CRC32,
    PACKET_FLAG_TILE_CONTENT_CRC32,
    MSG_ACK,
    MSG_BLIT_TILE,
    MSG_CLEAR,
    MSG_CANVAS_CRC,
    MSG_CANVAS_CRC_REPLY,
    MSG_RESOURCE_BEGIN,
    MSG_RESOURCE_CHUNK,
    MSG_RESOURCE_END,
    MSG_DRAW_RESOURCE,
    MSG_RESOURCE_RELEASE,
    MSG_RESOURCE_CLEAR,
    MSG_RESOURCE_INFO,
    MSG_RESOURCE_INFO_REPLY,
    MSG_FONT_INFO,
    MSG_FONT_INFO_REPLY,
    MSG_MEASURE_TEXT,
    MSG_MEASURE_TEXT_REPLY,
    MSG_DRAW_TEXT,
    MSG_COPY_RECT,
    MSG_SCROLL_RECT,
    MSG_RTC_READ,
    MSG_RTC_READ_REPLY,
    MSG_RTC_SET,
    MSG_ERROR,
    MSG_FILL_RECT,
    MSG_FRAME_ABORT,
    MSG_FRAME_BEGIN,
    MSG_FRAME_END,
    MSG_HELLO,
    MSG_HELLO_REPLY,
    MSG_LINE,
    MSG_PING,
    MSG_POLYLINE,
    MSG_PONG,
    MSG_SESSION_CLOSE,
    MSG_SET_BRIGHTNESS,
    MSG_STROKE_RECT,
    MSG_TILE_BEGIN,
    MSG_TILE_CHUNK,
    MSG_TILE_END,
    MSG_TOUCH,
    PIXEL_ALPHA8,
    PIXEL_RGB565,
    PIXEL_INDEX4,
    PIXEL_INDEX6,
    PIXEL_RGB565_SCALE2,
    PIXEL_INDEX4_SCALE2,
    PIXEL_INDEX6_SCALE2,
    PROTOCOL_VERSION,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    STATUS_OK,
    TILE_MAX_HEIGHT,
    TILE_MAX_WIDTH,
    TILE_CHUNK_PREFIX_STRUCT,
    TILE_BEGIN_STRUCT,
    TILE_BEGIN_CRC_STRUCT,
    TILE_END_STRUCT,
    RESOURCE_BEGIN_STRUCT,
    RESOURCE_CHUNK_PREFIX_STRUCT,
    RESOURCE_END_STRUCT,
    DRAW_RESOURCE_STRUCT,
    RESOURCE_RELEASE_STRUCT,
    RESOURCE_INFO_REPLY_STRUCT,
    FONT_INFO_REPLY_STRUCT,
    MEASURE_TEXT_PREFIX_STRUCT,
    MEASURE_TEXT_REPLY_STRUCT,
    DRAW_TEXT_PREFIX_STRUCT,
    COPY_RECT_STRUCT,
    SCROLL_RECT_STRUCT,
    RTC_SET_STRUCT,
    RTC_READ_REPLY_STRUCT,
    RTC_FLAG_OSCILLATOR_VALID,
    RTC_FLAG_RUNNING,
    RTC_FLAG_24_HOUR,
    TileProfile,
    TileProfileName,
    Packet,
    PacketParser,
    data_crc32,
    get_tile_profile,
    pack_packet,
    rgb565,
    rle_encode_alpha8,
    rle_encode_rgb565,
)
from .rtc import (
    NtpSample,
    RtcNtpSyncResult,
    RtcReading,
    current_utc_from_sample,
    nearest_second,
    query_ntp,
)

DEFAULT_VID = 0xCAFE
DEFAULT_PID = 0x4010
SCALE2_SOURCE_WIDTH = SCREEN_WIDTH // 2
SCALE2_SOURCE_HEIGHT = SCREEN_HEIGHT // 2
SCALE2_TILE_WIDTH = 15
SCALE2_TILE_HEIGHT = 20
SCALE2_MAX_ENCODED_BYTES = SCALE2_TILE_WIDTH * SCALE2_TILE_HEIGHT * 3
PING_MAX_PAYLOAD = 64
LINE_MAX_THICKNESS = 32
LINE_MAX_WORK = 1_000_000
PENDING_PACKET_LIMIT = 128
EVENT_QUEUE_LIMIT = 256

_REQUIRED_CAPABILITIES = (
    CAP_RGB565_TILES
    | CAP_ALPHA8_TILES
    | CAP_RLE
    | CAP_PRIMITIVES
    | CAP_FRAME_TRANSACTIONS
    | CAP_SESSION_REATTACH
    | CAP_TILE_PROFILES
)


class RemoteDisplayError(RuntimeError):
    pass


class RemoteDisplayTimeout(RemoteDisplayError):
    pass


class RemoteDisplayAccessError(RemoteDisplayError):
    """Raised when the operating system denies access to the USB interface."""


class RemoteDisplayTransportError(RemoteDisplayError):
    """Raised when a USB transfer fails for a reason other than access denial."""


def _is_access_denied(error: BaseException) -> bool:
    return (
        getattr(error, "errno", None) in {errno.EACCES, errno.EPERM}
        or getattr(error, "winerror", None) == 5
        or "access denied" in str(error).lower()
        or "insufficient permissions" in str(error).lower()
    )


def _transport_exception(action: str, error: BaseException) -> RemoteDisplayError:
    if _is_access_denied(error):
        return RemoteDisplayAccessError(f"USB access was denied while {action}: {error}")
    return RemoteDisplayTransportError(f"USB transport failed while {action}: {error}")


def _windows_usb_backend():
    """Return the packaged libusb backend used with the Windows WinUSB driver."""
    if sys.platform != "win32":
        return None
    try:
        import libusb_package
    except ImportError as exc:
        raise RuntimeError(
            "native Windows USB support requires libusb-package on AMD64/x64; Windows ARM64 is not "
            "currently supported. On AMD64/x64, reinstall the host package dependencies"
        ) from exc
    backend = libusb_package.get_libusb1_backend()
    if backend is None:
        raise RuntimeError("the packaged Windows libusb backend could not be loaded")
    return backend


def _usb_access_guidance() -> str:
    if sys.platform == "win32":
        return (
            "access to the RP2350 vendor interface was denied; close other applications using the display "
            "and make sure usbipd has not attached it to WSL"
        )
    return (
        "access to the RP2350 vendor interface was denied; on Linux install the supplied udev rule "
        "and reconnect the board"
    )


def _is_transport_timeout(error: BaseException) -> bool:
    return (
        error.__class__.__name__ == "USBTimeoutError"
        or getattr(error, "errno", None) in {errno.ETIMEDOUT, 10060}
    )


def _usb_device_serial(device, usb_util) -> str | None:
    try:
        serial = getattr(device, "serial_number", None)
    except Exception as exc:
        raise _transport_exception("reading a USB serial number", exc) from exc
    if serial:
        return str(serial)

    serial_index = getattr(device, "iSerialNumber", 0)
    if not serial_index:
        return None
    try:
        value = usb_util.get_string(device, serial_index)
    except Exception as exc:
        raise _transport_exception("reading a USB serial number", exc) from exc
    return str(value) if value else None


def _select_usb_device(
    devices: Sequence[object],
    usb_util,
    *,
    serial_number: str | None,
    bus: int | None,
    address: int | None,
):
    if serial_number is not None and (not isinstance(serial_number, str) or not serial_number.strip()):
        raise ValueError("serial_number must be a non-empty string")
    for name, value in (("bus", bus), ("address", address)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise ValueError(f"{name} must be a non-negative integer")

    matches = []
    for device in devices:
        if bus is not None and getattr(device, "bus", None) != bus:
            continue
        if address is not None and getattr(device, "address", None) != address:
            continue
        if serial_number is not None and _usb_device_serial(device, usb_util) != serial_number:
            continue
        matches.append(device)

    selector_used = serial_number is not None or bus is not None or address is not None
    if not matches:
        detail = " matching the supplied selector" if selector_used else ""
        raise RemoteDisplayError(f"no RP2350 remote display was found{detail}")
    if len(matches) > 1:
        raise RemoteDisplayError(
            "multiple RP2350 remote displays matched; select one with serial_number, bus, and/or address"
        )
    return matches[0]


def _cleanup_usb_device(
    device,
    usb_util,
    *,
    claimed_interface: int | None,
    detached_interface: int | None,
) -> None:
    """Best-effort release for both failed opens and normal shutdown."""

    if claimed_interface is not None:
        try:
            usb_util.release_interface(device, claimed_interface)
        except Exception:
            pass
    if detached_interface is not None:
        try:
            device.attach_kernel_driver(detached_interface)
        except Exception:
            pass
    try:
        usb_util.dispose_resources(device)
    except Exception:
        pass


class RemoteProtocolError(RemoteDisplayError):
    def __init__(self, status: int, command: int, sequence: int | None = None) -> None:
        suffix = "" if sequence is None else f" (sequence {sequence})"
        super().__init__(f"device rejected command 0x{command:02x} with status {status}{suffix}")
        self.status = status
        self.command = command
        self.sequence = sequence


@dataclass(frozen=True)
class DisplayInfo:
    protocol_version: int
    width: int
    height: int
    small_tile_width: int
    small_tile_height: int
    medium_tile_width: int
    medium_tile_height: int
    large_tile_width: int
    large_tile_height: int
    max_payload: int
    capabilities: int

    def tile_profile(self, name: TileProfileName) -> TileProfile:
        dimensions = {
            "small": (self.small_tile_width, self.small_tile_height),
            "medium": (self.medium_tile_width, self.medium_tile_height),
            "large": (self.large_tile_width, self.large_tile_height),
        }
        width, height = dimensions[name]
        return TileProfile(name, width, height)


@dataclass(frozen=True)
class TouchEvent:
    x: int
    y: int
    pressed: bool
    contacts: int


@dataclass(frozen=True)
class DeviceFontInfo:
    """Metrics and coverage identity for a firmware-resident bitmap font."""

    font_id: int
    cell_width: int
    cell_height: int
    ascent: int
    descent: int
    line_gap: int
    fallback_codepoint: int
    glyph_count: int
    coverage_version: int


@dataclass(frozen=True)
class DeviceTextMetrics:
    """Measured device-text geometry for a UTF-8 string at the requested scale."""

    width: int
    height: int
    glyph_count: int
    missing_glyph_count: int


@dataclass(frozen=True)
class TextMetrics:
    """Rendered text-mask geometry and visible-ink bounds.

    ``mask_*`` describes the alpha tile sent to the Pico. ``ink_*`` describes
    the non-transparent glyph pixels inside that tile. High-level alignment
    APIs center the ink rectangle, while :meth:`draw_text` retains its
    documented mask-origin coordinate behavior.
    """

    mask_width: int
    mask_height: int
    ink_x: int
    ink_y: int
    ink_width: int
    ink_height: int


@dataclass(frozen=True)
class TileTransferStats:
    direct_tiles: int = 0
    segmented_tiles: int = 0
    encoded_bytes: int = 0
    transfer_payload_bytes: int = 0
    packet_count: int = 0
    packet_header_bytes: int = 0
    wire_bytes: int = 0


@dataclass(frozen=True)
class ResourceCacheInfo:
    slot_capacity: int
    slot_used: int
    byte_capacity: int
    byte_used: int


@dataclass(frozen=True)
class ResourceUploadStats:
    resource_id: int
    encoded_bytes: int
    packet_count: int
    wire_bytes: int
    codec: int


class RemoteDisplay:
    """USB client for the generic RP2350 display command protocol."""

    def __init__(
        self,
        device,
        endpoint_out,
        endpoint_in,
        interface_number: int = 0,
        timeout_ms: int = 1000,
        strict_packet_crc: bool = False,
        strict_tile_crc: bool = False,
        detached_kernel_interface: int | None = None,
    ) -> None:
        self._device = device
        self._endpoint_out = endpoint_out
        self._endpoint_in = endpoint_in
        self._interface_number = interface_number
        self._detached_kernel_interface = detached_kernel_interface
        self.timeout_ms = timeout_ms
        self._strict_packet_crc = strict_packet_crc
        self._strict_tile_crc = strict_tile_crc
        self._parser = PacketParser()
        self._pending: deque[Packet] = deque()
        self._expired_sequences: deque[int] = deque(maxlen=64)
        # Touch movement can arrive continuously even when an application does
        # not poll. Keep recent state without allowing an idle client to grow
        # memory indefinitely.
        self._events: deque[TouchEvent] = deque(maxlen=EVENT_QUEUE_LIMIT)
        self._sequence = 1
        self._frame_id = 1
        self._tile_id = 1
        self._active_frame_id: int | None = None
        self._tile_transfer_stats = TileTransferStats()
        self.info: DisplayInfo | None = None
        self._closed = False

    @classmethod
    def open(
        cls,
        vid: int = DEFAULT_VID,
        pid: int = DEFAULT_PID,
        timeout_ms: int = 1000,
        strict_packet_crc: bool = False,
        strict_tile_crc: bool = False,
        *,
        serial_number: str | None = None,
        bus: int | None = None,
        address: int | None = None,
    ) -> "RemoteDisplay":
        try:
            import usb.core
            import usb.util
        except ImportError as exc:
            raise RuntimeError("PyUSB is required. Install the host package dependencies.") from exc

        try:
            find_options = {"find_all": True, "idVendor": vid, "idProduct": pid}
            backend = _windows_usb_backend()
            if backend is not None:
                find_options["backend"] = backend
            devices = list(usb.core.find(**find_options) or ())
        except usb.core.USBError as exc:
            if _is_access_denied(exc):
                raise RemoteDisplayAccessError(f"{_usb_access_guidance()}: {exc}") from exc
            raise RemoteDisplayTransportError(f"could not enumerate USB devices: {exc}") from exc
        try:
            device = _select_usb_device(
                devices,
                usb.util,
                serial_number=serial_number,
                bus=bus,
                address=address,
            )
        except RemoteDisplayError as exc:
            if not devices and serial_number is None and bus is None and address is None:
                raise RemoteDisplayError(f"device {vid:04x}:{pid:04x} was not found") from exc
            raise

        detached_interface: int | None = None
        claimed_interface: int | None = None
        try:
            try:
                if device.is_kernel_driver_active(0):
                    device.detach_kernel_driver(0)
                    detached_interface = 0
            except (NotImplementedError, usb.core.USBError):
                pass

            try:
                device.set_configuration()
            except usb.core.USBError as exc:
                if _is_access_denied(exc):
                    raise RemoteDisplayAccessError(_usb_access_guidance()) from exc
                raise RemoteDisplayTransportError(f"could not configure the USB device: {exc}") from exc
            try:
                configuration = device.get_active_configuration()
            except usb.core.USBError as exc:
                raise _transport_exception("reading the active USB configuration", exc) from exc
            interface = None
            for candidate in configuration:
                if candidate.bInterfaceClass == 0xFF:
                    interface = candidate
                    break
            if interface is None:
                raise RemoteDisplayError("no vendor bulk interface was found")

            endpoint_out = None
            endpoint_in = None
            for endpoint in interface:
                direction = usb.util.endpoint_direction(endpoint.bEndpointAddress)
                if direction == usb.util.ENDPOINT_OUT:
                    endpoint_out = endpoint
                elif direction == usb.util.ENDPOINT_IN:
                    endpoint_in = endpoint

            if endpoint_out is None or endpoint_in is None:
                raise RemoteDisplayError("vendor interface does not expose both bulk endpoints")

            try:
                usb.util.claim_interface(device, interface.bInterfaceNumber)
                claimed_interface = interface.bInterfaceNumber
            except usb.core.USBError as exc:
                if _is_access_denied(exc):
                    raise RemoteDisplayAccessError(_usb_access_guidance()) from exc
                raise RemoteDisplayTransportError(f"could not claim the vendor interface: {exc}") from exc
        except BaseException:
            _cleanup_usb_device(
                device,
                usb.util,
                claimed_interface=claimed_interface,
                detached_interface=detached_interface,
            )
            raise

        try:
            display = cls(
                device,
                endpoint_out,
                endpoint_in,
                interface.bInterfaceNumber,
                timeout_ms,
                strict_packet_crc,
                strict_tile_crc,
                detached_interface,
            )
        except BaseException:
            _cleanup_usb_device(
                device,
                usb.util,
                claimed_interface=claimed_interface,
                detached_interface=detached_interface,
            )
            raise
        try:
            display._drain_input(120)
            display.hello(retries=3)
        except BaseException:
            display.close()
            raise
        return display

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._active_frame_id is not None:
                try:
                    self.frame_abort()
                except Exception:
                    pass
            try:
                self.session_close()
            except Exception:
                pass
        finally:
            try:
                import usb.util
            except ImportError:
                pass
            else:
                _cleanup_usb_device(
                    self._device,
                    usb.util,
                    claimed_interface=self._interface_number,
                    detached_interface=self._detached_kernel_interface,
                )
            self._closed = True

    def __enter__(self) -> "RemoteDisplay":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _drain_input(self, duration_ms: int) -> None:
        """Discard replies/events left by a prior host process before HELLO."""
        self._events.clear()
        deadline = time.monotonic() + max(0, duration_ms) / 1000.0
        while time.monotonic() < deadline:
            packets = self._read_once(min(20, max(1, int((deadline - time.monotonic()) * 1000))))
            if not packets:
                continue
        self._reset_receive_state()
        self._events.clear()

    def _reset_receive_state(self) -> None:
        self._parser = PacketParser()
        self._pending = deque()

    def _invalidate_session(self) -> None:
        self.info = None
        self._active_frame_id = None
        self._reset_receive_state()
        self._events.clear()

    def recover_session(self, *, retries: int = 3, drain_ms: int = 120) -> DisplayInfo:
        """Reset uncertain host state and negotiate a fresh firmware session.

        A new HELLO resets frame, staged-transfer, and resource-cache state on
        the device. Cached resource identifiers must therefore be uploaded again.
        """
        if self._closed:
            raise RemoteDisplayError("cannot recover a closed display")
        if drain_ms < 0:
            raise ValueError("drain_ms must not be negative")
        self._invalidate_session()
        self._drain_input(drain_ms)
        return self.hello(retries=retries)

    def _next_sequence(self) -> int:
        sequence = self._sequence
        self._sequence = 1 if self._sequence == 0xFFFFFFFF else self._sequence + 1
        return sequence

    def _next_tile_id(self) -> int:
        tile_id = self._tile_id
        self._tile_id = 1 if self._tile_id == 0xFFFFFFFF else self._tile_id + 1
        return tile_id

    def _write(self, message_type: int, payload: bytes = b"", flags: int = 0) -> int:
        if self._closed:
            raise RemoteDisplayError("cannot write to a closed display")
        sequence = self._next_sequence()
        packet = pack_packet(
            message_type,
            sequence,
            payload,
            flags=flags,
            packet_crc=getattr(self, "_strict_packet_crc", False),
        )
        try:
            written = self._endpoint_out.write(packet, timeout=self.timeout_ms)
        except Exception as exc:
            self._invalidate_session()
            raise _transport_exception("writing to the display", exc) from exc
        if written != len(packet):
            self._invalidate_session()
            raise RemoteDisplayTransportError(f"short USB write: {written} of {len(packet)} bytes")
        return sequence

    def _read_once(self, timeout_ms: int) -> list[Packet]:
        if self._closed:
            raise RemoteDisplayError("cannot read from a closed display")
        try:
            data = bytes(self._endpoint_in.read(64, timeout=timeout_ms))
        except Exception as exc:
            if _is_transport_timeout(exc):
                return []
            self._invalidate_session()
            raise _transport_exception("reading from the display", exc) from exc
        bad_packets = self._parser.bad_packets
        packets = self._parser.feed(data)
        if self.info is not None and self._strict_packet_crc and self._parser.bad_packets != bad_packets:
            self._invalidate_session()
            raise RemoteDisplayError("incoming USB packet failed framing or CRC validation")
        return packets

    def _decode_event(self, packet: Packet) -> TouchEvent | None:
        if packet.message_type != MSG_TOUCH or len(packet.payload) != 6:
            return None
        x, y, state, contacts = struct.unpack("<HHBB", packet.payload)
        return TouchEvent(x=x, y=y, pressed=bool(state), contacts=contacts)

    def _handle_incoming(self, packet: Packet) -> Packet | None:
        if self._strict_packet_crc and not packet.flags & PACKET_FLAG_CRC32:
            self._invalidate_session()
            raise RemoteDisplayError("strict packet CRC is enabled but the device sent an unprotected packet")
        event = self._decode_event(packet)
        if event is not None:
            self._events.append(event)
            return None
        return packet

    def _raise_protocol_error(self, packet: Packet) -> None:
        self._invalidate_session()
        if len(packet.payload) != 2:
            raise RemoteDisplayError("device sent a malformed error response")
        status, command = packet.payload
        raise RemoteProtocolError(status, command, packet.sequence)

    def _queue_pending(self, packet: Packet) -> None:
        if packet.sequence in self._expired_sequences:
            return
        if len(self._pending) >= PENDING_PACKET_LIMIT:
            self._invalidate_session()
            raise RemoteDisplayError("too many unmatched USB replies; recover the display session")
        self._pending.append(packet)

    def _process_wait_packet(self, packet: Packet, sequence: int, expected_type: int) -> Packet | None:
        packet = self._handle_incoming(packet)
        if packet is None:
            return None
        if packet.sequence != sequence:
            # Drawing and staged-transfer commands are intentionally fire-and-forget.
            # Their sequence-tagged errors must still fail the next synchronization
            # point, while replies for an explicitly expired request are discarded.
            if packet.message_type == MSG_ERROR and packet.sequence not in self._expired_sequences:
                self._raise_protocol_error(packet)
            self._queue_pending(packet)
            return None
        if packet.message_type == MSG_ERROR:
            self._raise_protocol_error(packet)
        if packet.message_type != expected_type:
            self._invalidate_session()
            raise RemoteDisplayError(
                f"device returned message 0x{packet.message_type:02x} while 0x{expected_type:02x} was expected "
                f"for sequence {sequence}"
            )
        return packet

    def _wait_for(self, sequence: int, expected_type: int, timeout_ms: int | None = None) -> Packet:
        timeout = self.timeout_ms if timeout_ms is None else timeout_ms
        if timeout < 0:
            raise ValueError("timeout_ms must not be negative")
        deadline = time.monotonic() + timeout / 1000.0

        while time.monotonic() < deadline:
            pending_count = len(self._pending)
            for _ in range(pending_count):
                packet = self._pending.popleft()
                reply = self._process_wait_packet(packet, sequence, expected_type)
                if reply is not None:
                    return reply

            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            packets = self._read_once(min(remaining_ms, 50))
            for index, packet in enumerate(packets):
                reply = self._process_wait_packet(packet, sequence, expected_type)
                if reply is not None:
                    # One USB read can contain several small protocol packets. Do
                    # not lose trailing touch events or replies when the awaited
                    # response happens to appear first in that batch.
                    for trailing in packets[index + 1:]:
                        trailing = self._handle_incoming(trailing)
                        if trailing is not None:
                            self._queue_pending(trailing)
                    return reply

        # Keep this sequence quarantined until a new HELLO succeeds. A delayed
        # reply from the timed-out request can otherwise be mistaken for an
        # asynchronous failure while session recovery is in progress.
        self._expired_sequences.append(sequence)
        self._invalidate_session()
        raise RemoteDisplayTimeout(f"timed out waiting for response to sequence {sequence}")

    def _validate_hello_info(self, info: DisplayInfo) -> None:
        if info.protocol_version != PROTOCOL_VERSION:
            raise RemoteDisplayError(f"protocol mismatch: device reports {info.protocol_version}")
        if (info.width, info.height) != (SCREEN_WIDTH, SCREEN_HEIGHT):
            raise RemoteDisplayError(
                f"display geometry mismatch: device reports {info.width}x{info.height}, "
                f"expected {SCREEN_WIDTH}x{SCREEN_HEIGHT}"
            )
        for name in ("small", "medium", "large"):
            expected = get_tile_profile(name)
            advertised = info.tile_profile(name)
            if (advertised.width, advertised.height) != (expected.width, expected.height):
                raise RemoteDisplayError(
                    f"{name} tile profile mismatch: device reports {advertised.width}x{advertised.height}, "
                    f"expected {expected.width}x{expected.height}"
                )
        if info.max_payload < MAX_PAYLOAD:
            raise RemoteDisplayError(
                f"device payload limit {info.max_payload} is smaller than the required {MAX_PAYLOAD} bytes"
            )
        missing = _REQUIRED_CAPABILITIES & ~info.capabilities
        if missing:
            raise RemoteDisplayError(f"firmware is missing required capability bits 0x{missing:08x}")
        if self._strict_packet_crc and not info.capabilities & CAP_OPTIONAL_PACKET_CRC32:
            raise RemoteDisplayError("connected firmware does not advertise optional packet CRC")
        if self._strict_tile_crc and not info.capabilities & CAP_OPTIONAL_TILE_CRC32:
            raise RemoteDisplayError("connected firmware does not advertise optional staged-tile CRC")

    def hello(self, retries: int = 1) -> DisplayInfo:
        if retries < 1:
            raise ValueError("retries must be at least one")
        if self._closed:
            raise RemoteDisplayError("cannot negotiate a session on a closed display")
        self.info = None
        self._active_frame_id = None
        self._pending.clear()
        last_error: RemoteDisplayError | None = None
        for attempt in range(retries):
            sequence = self._write(MSG_HELLO, struct.pack("<H", PROTOCOL_VERSION))
            try:
                reply = self._wait_for(sequence, MSG_HELLO_REPLY)
            except RemoteDisplayTimeout as exc:
                last_error = exc
                self._reset_receive_state()
                if attempt + 1 < retries:
                    time.sleep(0.08)
                continue
            if len(reply.payload) != HELLO_REPLY_STRUCT.size:
                self._invalidate_session()
                raise RemoteDisplayError("invalid HELLO reply")
            info = DisplayInfo(*HELLO_REPLY_STRUCT.unpack(reply.payload))
            try:
                self._validate_hello_info(info)
            except RemoteDisplayError:
                self._invalidate_session()
                raise
            self.info = info
            self._pending.clear()
            self._expired_sequences.clear()
            return info
        raise last_error or RemoteDisplayTimeout("device did not reply to HELLO")

    def ping(self, payload: bytes = b"ping") -> bytes:
        if len(payload) > PING_MAX_PAYLOAD:
            raise ValueError(f"PING payload must not exceed {PING_MAX_PAYLOAD} bytes")
        sequence = self._write(MSG_PING, payload)
        reply = self._wait_for(sequence, MSG_PONG)
        return reply.payload

    def canvas_crc32(self) -> int:
        """Return the CRC32 of the current 450x600 canvas in host RGB565 byte order.

        This diagnostic request is valid only when no frame transaction is open.
        It is intended for transfer verification and does not change the canvas.
        """
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before requesting a canvas CRC")
        if self._active_frame_id is not None:
            raise RemoteDisplayError("canvas CRC cannot be requested inside an open frame")
        if not self.info.capabilities & CAP_CANVAS_CRC32:
            raise RemoteDisplayError("connected firmware does not advertise canvas CRC verification")

        sequence = self._write(MSG_CANVAS_CRC)
        reply = self._wait_for(sequence, MSG_CANVAS_CRC_REPLY, max(self.timeout_ms, 5000))
        if len(reply.payload) != 4:
            raise RemoteDisplayError("device returned a malformed canvas CRC response")
        return struct.unpack("<I", reply.payload)[0]

    def _require_rtc_access(self) -> None:
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before accessing the RTC")
        if self._active_frame_id is not None:
            raise RemoteDisplayError("RTC access cannot be requested inside an open frame")
        if not self.info.capabilities & CAP_RTC_PCF85063:
            raise RemoteDisplayError("connected firmware does not advertise the PCF85063 RTC")

    @staticmethod
    def _datetime_to_rtc_fields(value: datetime) -> tuple[datetime, int]:
        if not isinstance(value, datetime):
            raise TypeError("RTC time must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("RTC time must be timezone-aware")
        value = value.astimezone(timezone.utc).replace(microsecond=0)
        if not 2000 <= value.year <= 2099:
            raise ValueError("RTC time year must be in the range 2000..2099")
        # Python uses Monday=0; the PCF85063 uses Sunday=0.
        weekday = (value.weekday() + 1) % 7
        return value, weekday

    def read_rtc(self) -> RtcReading:
        """Read the board's PCF85063 RTC as a timezone-aware UTC value.

        The ``weekday`` field of the returned :class:`RtcReading` follows the
        PCF85063 convention, where Sunday is 0 and Saturday is 6. The
        oscillator-valid flag reflects the RTC's power-loss indicator.
        """
        self._require_rtc_access()
        sequence = self._write(MSG_RTC_READ)
        reply = self._wait_for(sequence, MSG_RTC_READ_REPLY)
        if len(reply.payload) != RTC_READ_REPLY_STRUCT.size:
            raise RemoteDisplayError("device returned a malformed RTC reading")
        year, month, day, hour, minute, second, weekday, flags = RTC_READ_REPLY_STRUCT.unpack(reply.payload)
        try:
            value = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except ValueError as exc:
            raise RemoteDisplayError("device returned an invalid RTC calendar value") from exc
        if weekday > 6:
            raise RemoteDisplayError("device returned an invalid RTC weekday")
        return RtcReading(
            datetime_utc=value,
            weekday=weekday,
            oscillator_valid=bool(flags & RTC_FLAG_OSCILLATOR_VALID),
            running=bool(flags & RTC_FLAG_RUNNING),
            twenty_four_hour=bool(flags & RTC_FLAG_24_HOUR),
        )

    def set_rtc(self, value: datetime, *, verify: bool = True) -> RtcReading | None:
        """Set the board RTC from a timezone-aware datetime, normalized to UTC.

        The PCF85063 stores whole seconds and supports 2000 through 2099. When
        ``verify`` is true, this method immediately returns a fresh RTC reading.
        """
        self._require_rtc_access()
        value, weekday = self._datetime_to_rtc_fields(value)
        payload = RTC_SET_STRUCT.pack(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            weekday,
        )
        sequence = self._write(MSG_RTC_SET, payload)
        reply = self._wait_for(sequence, MSG_ACK)
        if reply.payload != bytes((STATUS_OK,)):
            raise RemoteDisplayError("device rejected RTC_SET")
        return self.read_rtc() if verify else None

    def sync_rtc_from_ntp(
        self,
        server: str = "time.cloudflare.com",
        *,
        port: int = 123,
        timeout: float = 2.0,
        max_offset_seconds: float | None = 86_400.0,
    ) -> RtcNtpSyncResult:
        """Query unauthenticated NTP, set the board RTC in UTC, and read it back.

        The NTP exchange runs on the host. The Pico receives only the resulting
        whole-second UTC calendar value. This method does not change the host
        operating system clock. By default, samples more than one day from the
        host clock are rejected; tune ``max_offset_seconds`` or deliberately
        pass ``None`` to disable that plausibility check.
        """
        self._require_rtc_access()
        sample: NtpSample = query_ntp(
            server,
            port=port,
            timeout=timeout,
            max_offset_seconds=max_offset_seconds,
        )
        target = nearest_second(current_utc_from_sample(sample))
        rtc = self.set_rtc(target, verify=True)
        assert rtc is not None
        return RtcNtpSyncResult(sample=sample, target_datetime_utc=target, rtc=rtc)

    def resource_cache_info(self) -> ResourceCacheInfo:
        """Return session-local Pico resource-cache usage without changing the canvas."""
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before requesting resource-cache information")
        if self._active_frame_id is not None:
            raise RemoteDisplayError("resource-cache information cannot be requested inside an open frame")
        if not self.info.capabilities & CAP_RESOURCE_CACHE:
            raise RemoteDisplayError("connected firmware does not advertise the resource cache")

        sequence = self._write(MSG_RESOURCE_INFO)
        reply = self._wait_for(sequence, MSG_RESOURCE_INFO_REPLY)
        if len(reply.payload) != RESOURCE_INFO_REPLY_STRUCT.size:
            raise RemoteDisplayError("device returned malformed resource-cache information")
        return ResourceCacheInfo(*RESOURCE_INFO_REPLY_STRUCT.unpack(reply.payload))

    @staticmethod
    def _device_text_bytes(text: str, scale: int) -> bytes:
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        if not 1 <= scale <= 4:
            raise ValueError("device font scale must be in the range 1..4")
        try:
            return text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("text must contain valid Unicode scalar values") from exc

    @staticmethod
    def _check_device_font_id(font_id: int) -> int:
        if not isinstance(font_id, int) or not 0 <= font_id <= 0xFF:
            raise ValueError("font_id must be in the range 0..255")
        return font_id

    def device_font_info(self, font_id: int = 0) -> DeviceFontInfo:
        """Return metrics and coverage information for a firmware-resident font.

        Query this outside a frame transaction. The returned dimensions describe
        one base grid cell. Full-width glyphs can occupy two adjacent cells, so
        use :meth:`measure_device_text` for exact mixed-width layout.
        """
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before querying device fonts")
        if self._active_frame_id is not None:
            raise RemoteDisplayError("device font information cannot be requested inside an open frame")
        if not self.info.capabilities & CAP_DEVICE_TEXT:
            raise RemoteDisplayError("connected firmware does not advertise device text")
        font_id = self._check_device_font_id(font_id)
        sequence = self._write(MSG_FONT_INFO, struct.pack("<B", font_id))
        reply = self._wait_for(sequence, MSG_FONT_INFO_REPLY)
        if len(reply.payload) != FONT_INFO_REPLY_STRUCT.size:
            raise RemoteDisplayError("device returned malformed font information")
        return DeviceFontInfo(*FONT_INFO_REPLY_STRUCT.unpack(reply.payload))

    def measure_device_text(self, text: str, *, font_id: int = 0, scale: int = 1) -> DeviceTextMetrics:
        """Measure UTF-8 text using the firmware's own glyph and line metrics.

        This command is intentionally outside frame transactions, so layouts can
        be prepared before any drawing commands are issued.
        """
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before measuring device text")
        if self._active_frame_id is not None:
            raise RemoteDisplayError("device text cannot be measured inside an open frame")
        if not self.info.capabilities & CAP_DEVICE_TEXT:
            raise RemoteDisplayError("connected firmware does not advertise device text")
        font_id = self._check_device_font_id(font_id)
        encoded = self._device_text_bytes(text, scale)
        if len(encoded) > MAX_PAYLOAD - MEASURE_TEXT_PREFIX_STRUCT.size:
            raise ValueError("UTF-8 text exceeds the protocol payload limit")
        sequence = self._write(MSG_MEASURE_TEXT, MEASURE_TEXT_PREFIX_STRUCT.pack(font_id, scale) + encoded)
        reply = self._wait_for(sequence, MSG_MEASURE_TEXT_REPLY)
        if len(reply.payload) != MEASURE_TEXT_REPLY_STRUCT.size:
            raise RemoteDisplayError("device returned malformed device-text metrics")
        return DeviceTextMetrics(*MEASURE_TEXT_REPLY_STRUCT.unpack(reply.payload))

    def draw_device_text(
        self,
        text: str,
        x: int,
        y: int,
        color: int,
        *,
        font_id: int = 0,
        scale: int = 1,
    ) -> None:
        """Draw UTF-8 text with a firmware-resident 1-bit bitmap font.

        The text origin is the top-left corner of the first grid cell. Most
        glyphs occupy one cell; full-width glyphs occupy two adjacent cells.
        Text may include ``\n`` for a new line and ``\t`` for a four-cell tab
        stop. The Pico clips glyph pixels at the panel boundary.
        """
        self._ensure_frame()
        if not isinstance(x, int) or not isinstance(y, int) or not 0 <= x <= 0xFFFF or not 0 <= y <= 0xFFFF:
            raise ValueError("device text coordinates must be in the range 0..65535")
        if self.info is None or not self.info.capabilities & CAP_DEVICE_TEXT:
            raise RemoteDisplayError("connected firmware does not advertise device text")
        font_id = self._check_device_font_id(font_id)
        encoded = self._device_text_bytes(text, scale)
        if len(encoded) > MAX_PAYLOAD - DRAW_TEXT_PREFIX_STRUCT.size:
            raise ValueError("UTF-8 text exceeds the protocol payload limit")
        payload = DRAW_TEXT_PREFIX_STRUCT.pack(x, y, self._check_color(color), font_id, scale) + encoded
        self._write(MSG_DRAW_TEXT, payload)

    def _cache_encoded_resource(
        self,
        resource_id: int,
        width: int,
        height: int,
        pixel_format: int,
        codec: int,
        encoded: bytes,
    ) -> ResourceUploadStats:
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before caching a resource")
        if self._active_frame_id is not None:
            raise RemoteDisplayError("cache resources before opening a frame")
        if not self.info.capabilities & CAP_RESOURCE_CACHE:
            raise RemoteDisplayError("connected firmware does not advertise the resource cache")
        if not 1 <= resource_id <= 0xFFFFFFFF:
            raise ValueError("resource_id must be in the range 1..0xffffffff")
        self._validate_tile(0, 0, width, height)
        if not encoded or len(encoded) > MAX_ENCODED_TILE_BYTES:
            raise ValueError("encoded resource length is outside the supported range")

        payload = RESOURCE_BEGIN_STRUCT.pack(resource_id, width, height, pixel_format, codec, len(encoded))
        flags = 0
        if self._strict_tile_crc:
            payload += TILE_BEGIN_CRC_STRUCT.pack(data_crc32(encoded))
            flags |= PACKET_FLAG_TILE_CONTENT_CRC32
        chunk_capacity = MAX_PAYLOAD - RESOURCE_CHUNK_PREFIX_STRUCT.size
        try:
            self._write(MSG_RESOURCE_BEGIN, payload, flags=flags)
            for offset in range(0, len(encoded), chunk_capacity):
                chunk = encoded[offset:offset + chunk_capacity]
                self._write(MSG_RESOURCE_CHUNK, RESOURCE_CHUNK_PREFIX_STRUCT.pack(resource_id, offset) + chunk)

            sequence = self._write(MSG_RESOURCE_END, RESOURCE_END_STRUCT.pack(resource_id))
            reply = self._wait_for(sequence, MSG_ACK)
            if reply.payload != bytes((STATUS_OK,)):
                raise RemoteDisplayError("device rejected cached resource")
        except BaseException:
            self._invalidate_session()
            raise

        chunk_count = (len(encoded) + chunk_capacity - 1) // chunk_capacity
        packet_count = chunk_count + 2
        header_bytes = packet_count * (12 + (4 if self._strict_packet_crc else 0))
        wire_bytes = len(payload) + len(encoded) + chunk_count * RESOURCE_CHUNK_PREFIX_STRUCT.size + RESOURCE_END_STRUCT.size + header_bytes
        return ResourceUploadStats(resource_id, len(encoded), packet_count, wire_bytes, codec)

    def cache_rgb565(
        self,
        resource_id: int,
        width: int,
        height: int,
        pixels: bytes,
        compression: str = "auto",
    ) -> ResourceUploadStats:
        self._validate_tile(0, 0, width, height)
        if len(pixels) != width * height * 2:
            raise ValueError("RGB565 resource byte length does not match the supplied dimensions")
        encoded, codec = self._compress_rgb565(pixels, compression)
        return self._cache_encoded_resource(resource_id, width, height, PIXEL_RGB565, codec, encoded)

    def cache_alpha(
        self,
        resource_id: int,
        width: int,
        height: int,
        alpha: bytes,
        compression: str = "auto",
    ) -> ResourceUploadStats:
        self._validate_tile(0, 0, width, height)
        if len(alpha) != width * height:
            raise ValueError("alpha resource byte length does not match the supplied dimensions")
        encoded, codec = self._compress_alpha(alpha, compression)
        return self._cache_encoded_resource(resource_id, width, height, PIXEL_ALPHA8, codec, encoded)

    def cache_palette4(
        self,
        resource_id: int,
        width: int,
        height: int,
        palette: Sequence[int],
        indices: bytes | bytearray | memoryview,
    ) -> ResourceUploadStats:
        self._validate_tile(0, 0, width, height)
        if self.info is not None and not self.info.capabilities & CAP_PALETTE4_TILES:
            raise RemoteDisplayError("connected firmware does not advertise Palette4 resources")
        palette_values = tuple(self._check_color(value) for value in palette)
        if not 1 <= len(palette_values) <= 16:
            raise ValueError("palette must contain 1..16 RGB565 colors")
        raw_indices = bytes(indices)
        pixels = width * height
        if len(raw_indices) != pixels or any(index >= len(palette_values) for index in raw_indices):
            raise ValueError("palette indices do not match the dimensions or palette")
        packed = bytearray((pixels + 1) // 2)
        for index, value in enumerate(raw_indices):
            if index & 1:
                packed[index // 2] |= value
            else:
                packed[index // 2] = value << 4
        encoded = bytearray((len(palette_values),))
        for color in palette_values:
            encoded.extend(struct.pack("<H", color))
        encoded.extend(packed)
        return self._cache_encoded_resource(resource_id, width, height, PIXEL_INDEX4, CODEC_PALETTE4, bytes(encoded))

    def cache_palette64(
        self,
        resource_id: int,
        width: int,
        height: int,
        palette: Sequence[int],
        indices: bytes | bytearray | memoryview,
    ) -> ResourceUploadStats:
        """Cache a 1-64 color resource using packed LSB-first six-bit indices."""

        self._validate_tile(0, 0, width, height)
        if self.info is not None and not self.info.capabilities & CAP_PALETTE64_TILES:
            raise RemoteDisplayError("connected firmware does not advertise Palette64 resources")
        palette_values = tuple(self._check_color(value) for value in palette)
        if not 1 <= len(palette_values) <= 64:
            raise ValueError("palette must contain 1..64 RGB565 colors")
        raw_indices = bytes(indices)
        pixel_count = width * height
        if len(raw_indices) != pixel_count:
            raise ValueError("palette index count does not match resource dimensions")
        if any(index >= len(palette_values) for index in raw_indices):
            raise ValueError("palette index is outside the supplied palette")

        packed = bytearray((pixel_count * 6 + 7) // 8)
        for pixel, value in enumerate(raw_indices):
            bit_offset = pixel * 6
            byte_offset = bit_offset // 8
            shift = bit_offset & 7
            packed[byte_offset] |= (value << shift) & 0xFF
            if shift > 2:
                packed[byte_offset + 1] |= value >> (8 - shift)

        encoded = bytearray((len(palette_values),))
        for color in palette_values:
            encoded.extend(struct.pack("<H", color))
        encoded.extend(packed)
        return self._cache_encoded_resource(
            resource_id,
            width,
            height,
            PIXEL_INDEX6,
            CODEC_PALETTE64,
            bytes(encoded),
        )

    def draw_cached(self, resource_id: int, x: int, y: int, color: int = 0) -> None:
        self._ensure_frame()
        if not 1 <= resource_id <= 0xFFFFFFFF:
            raise ValueError("resource_id must be in the range 1..0xffffffff")
        if x < 0 or y < 0 or x >= SCREEN_WIDTH or y >= SCREEN_HEIGHT:
            raise ValueError("cached resource origin must be inside the display")
        self._write(MSG_DRAW_RESOURCE, DRAW_RESOURCE_STRUCT.pack(resource_id, x, y, self._check_color(color)))

    def release_cached(self, resource_id: int) -> None:
        if self.info is None or self._active_frame_id is not None:
            raise RemoteDisplayError("release cached resources outside an open frame")
        sequence = self._write(MSG_RESOURCE_RELEASE, RESOURCE_RELEASE_STRUCT.pack(resource_id))
        reply = self._wait_for(sequence, MSG_ACK)
        if reply.payload != bytes((STATUS_OK,)):
            raise RemoteDisplayError("device rejected resource release")

    def clear_cached(self) -> None:
        if self.info is None or self._active_frame_id is not None:
            raise RemoteDisplayError("clear cached resources outside an open frame")
        sequence = self._write(MSG_RESOURCE_CLEAR)
        reply = self._wait_for(sequence, MSG_ACK)
        if reply.payload != bytes((STATUS_OK,)):
            raise RemoteDisplayError("device rejected resource-cache clear")

    def _ensure_frame(self) -> None:
        if self.info is None:
            raise RemoteDisplayError("no active session; call recover_session() before opening or drawing a frame")
        if self._active_frame_id is None:
            raise RemoteDisplayError("drawing commands must be sent inside 'with display.frame(): ...'")

    def frame_begin(self, frame_id: int | None = None) -> int:
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before opening a frame")
        if self._active_frame_id is not None:
            raise RemoteDisplayError("a frame is already open")
        if frame_id is None:
            frame_id = self._frame_id
        sequence = self._write(MSG_FRAME_BEGIN, struct.pack("<I", frame_id))
        try:
            reply = self._wait_for(sequence, MSG_ACK)
            if reply.payload != bytes((STATUS_OK,)):
                raise RemoteDisplayError("device rejected FRAME_BEGIN")
        except BaseException:
            self._invalidate_session()
            raise
        self._active_frame_id = frame_id
        return frame_id

    def frame_end(self, frame_id: int | None = None, timeout_ms: int | None = None) -> None:
        self._ensure_frame()
        if frame_id is None:
            frame_id = self._active_frame_id
        if frame_id != self._active_frame_id:
            raise RemoteDisplayError("FRAME_END does not match the active frame")
        sequence = self._write(MSG_FRAME_END, struct.pack("<I", frame_id))
        try:
            reply = self._wait_for(sequence, MSG_ACK, timeout_ms)
            if reply.payload != bytes((STATUS_OK,)):
                raise RemoteDisplayError("device returned an invalid frame acknowledgement")
        except BaseException:
            self._invalidate_session()
            raise
        finally:
            self._active_frame_id = None
        self._frame_id = 1 if frame_id == 0xFFFFFFFF else frame_id + 1

    def frame_abort(self, frame_id: int | None = None) -> None:
        if self._active_frame_id is None:
            return
        if frame_id is None:
            frame_id = self._active_frame_id
        sequence = self._write(MSG_FRAME_ABORT, struct.pack("<I", frame_id))
        try:
            reply = self._wait_for(sequence, MSG_ACK)
            if reply.payload != bytes((STATUS_OK,)):
                raise RemoteDisplayError("device rejected FRAME_ABORT")
        finally:
            self._invalidate_session()

    def session_close(self) -> None:
        """End the current host session without altering the displayed canvas."""
        if self.info is None or self._closed:
            return
        try:
            sequence = self._write(MSG_SESSION_CLOSE)
            reply = self._wait_for(sequence, MSG_ACK)
            if reply.payload != bytes((STATUS_OK,)):
                raise RemoteDisplayError("device rejected SESSION_CLOSE")
        finally:
            self._invalidate_session()

    @contextmanager
    def frame(self, timeout_ms: int | None = None) -> Iterator["RemoteDisplay"]:
        frame_id = self.frame_begin()
        try:
            yield self
        except BaseException:
            try:
                self.frame_abort(frame_id)
            except RemoteDisplayError:
                pass
            raise
        else:
            self.frame_end(frame_id, timeout_ms)

    def clear(self, color: int = 0x0000) -> None:
        self._ensure_frame()
        self._write(MSG_CLEAR, struct.pack("<H", self._check_color(color)))

    def set_brightness(self, percent: int) -> None:
        """Set AMOLED brightness from 0 through 100 percent.

        This command is independent of frame transactions and can be called
        immediately after RemoteDisplay.open().
        """
        if not 0 <= percent <= 100:
            raise ValueError("brightness must be in the range 0..100")
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before setting brightness")
        if not self.info.capabilities & CAP_BRIGHTNESS:
            raise RemoteDisplayError("connected firmware does not advertise brightness control")
        sequence = self._write(MSG_SET_BRIGHTNESS, struct.pack("<B", percent))
        reply = self._wait_for(sequence, MSG_ACK)
        if reply.payload != bytes((STATUS_OK,)):
            raise RemoteDisplayError("device rejected brightness update")

    def fill_rect(self, x: int, y: int, width: int, height: int, color: int) -> None:
        self._ensure_frame()
        self._write(MSG_FILL_RECT, struct.pack("<HHHHH", x, y, width, height, self._check_color(color)))

    def stroke_rect(self, x: int, y: int, width: int, height: int, color: int, thickness: int = 1) -> None:
        self._ensure_frame()
        if not 0 <= thickness <= 255:
            raise ValueError("thickness must be in the range 0..255")
        self._write(MSG_STROKE_RECT, struct.pack("<HHHHHBB", x, y, width, height, self._check_color(color), thickness, 0))

    @staticmethod
    def _check_line_coordinate(value: int, name: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"{name} must be in the range 0..65535")
        return value

    @staticmethod
    def _check_line_thickness(thickness: int) -> int:
        if not isinstance(thickness, int) or isinstance(thickness, bool):
            raise TypeError("thickness must be an integer")
        normalized = 1 if thickness == 0 else thickness
        if thickness < 0 or normalized > LINE_MAX_THICKNESS:
            raise ValueError(f"thickness must be in the range 0..{LINE_MAX_THICKNESS}")
        return normalized

    @staticmethod
    def _trunc_div(numerator: int, denominator: int) -> int:
        """Integer division truncated toward zero, matching C99 signed division."""

        quotient = abs(numerator) // abs(denominator)
        return -quotient if (numerator < 0) != (denominator < 0) else quotient

    @staticmethod
    def _line_outcode(x: int, y: int, min_x: int, min_y: int, max_x: int, max_y: int) -> int:
        code = 0
        if x < min_x:
            code |= 1
        elif x > max_x:
            code |= 2
        if y < min_y:
            code |= 4
        elif y > max_y:
            code |= 8
        return code

    @classmethod
    def _line_work(cls, x0: int, y0: int, x1: int, y1: int, thickness: int) -> int:
        x0 = cls._check_line_coordinate(x0, "x0")
        y0 = cls._check_line_coordinate(y0, "y0")
        x1 = cls._check_line_coordinate(x1, "x1")
        y1 = cls._check_line_coordinate(y1, "y1")
        normalized = cls._check_line_thickness(thickness)
        radius = normalized // 2
        min_x = -radius
        min_y = -radius
        max_x = SCREEN_WIDTH - 1 + radius
        max_y = SCREEN_HEIGHT - 1 + radius

        while True:
            code0 = cls._line_outcode(x0, y0, min_x, min_y, max_x, max_y)
            code1 = cls._line_outcode(x1, y1, min_x, min_y, max_x, max_y)
            if not code0 | code1:
                break
            if code0 & code1:
                return 0

            outside = code0 if code0 else code1
            if outside & 4:
                y = min_y
                x = x0 + cls._trunc_div((x1 - x0) * (min_y - y0), y1 - y0)
            elif outside & 8:
                y = max_y
                x = x0 + cls._trunc_div((x1 - x0) * (max_y - y0), y1 - y0)
            elif outside & 2:
                x = max_x
                y = y0 + cls._trunc_div((y1 - y0) * (max_x - x0), x1 - x0)
            else:
                x = min_x
                y = y0 + cls._trunc_div((y1 - y0) * (min_x - x0), x1 - x0)

            if outside == code0:
                x0, y0 = x, y
            else:
                x1, y1 = x, y

        diameter = radius * 2 + 1
        return (max(abs(x1 - x0), abs(y1 - y0)) + 1) * diameter * diameter

    def line(self, x0: int, y0: int, x1: int, y1: int, color: int, thickness: int = 1) -> None:
        self._ensure_frame()
        if self._line_work(x0, y0, x1, y1, thickness) > LINE_MAX_WORK:
            raise ValueError(f"line exceeds the firmware work limit of {LINE_MAX_WORK}")
        self._write(MSG_LINE, struct.pack("<HHHHHBB", x0, y0, x1, y1, self._check_color(color), thickness, 0))

    @staticmethod
    def _validate_canvas_rect(x: int, y: int, width: int, height: int, *, name: str = "rectangle") -> None:
        if not all(isinstance(value, int) for value in (x, y, width, height)):
            raise TypeError(f"{name} coordinates and dimensions must be integers")
        if width <= 0 or height <= 0:
            raise ValueError(f"{name} width and height must be positive")
        if x < 0 or y < 0 or x + width > SCREEN_WIDTH or y + height > SCREEN_HEIGHT:
            raise ValueError(f"{name} must fit fully within the display")

    def copy_rect(
        self,
        source_x: int,
        source_y: int,
        width: int,
        height: int,
        destination_x: int,
        destination_y: int,
    ) -> None:
        """Copy a framebuffer rectangle on the Pico, preserving overlapping moves.

        The copy runs inside the active frame transaction. It transfers only a
        compact command and is suited to scrolling charts, terminal panes, and
        moving cached regions without retransmitting their pixels.
        """
        self._ensure_frame()
        if self.info is None or not self.info.capabilities & CAP_COPY_RECT:
            raise RemoteDisplayError("connected firmware does not advertise COPY_RECT")
        self._validate_canvas_rect(source_x, source_y, width, height, name="copy source")
        self._validate_canvas_rect(destination_x, destination_y, width, height, name="copy destination")
        self._write(
            MSG_COPY_RECT,
            COPY_RECT_STRUCT.pack(source_x, source_y, width, height, destination_x, destination_y),
        )

    def scroll_rect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        delta_x: int,
        delta_y: int,
        fill_color: int = 0x0000,
    ) -> None:
        """Scroll a framebuffer rectangle on the Pico and fill exposed pixels.

        Positive ``delta_x`` moves content right. Positive ``delta_y`` moves
        content down. The command is lossless because it operates on the
        device's RGB565 framebuffer.
        """
        self._ensure_frame()
        if self.info is None or not self.info.capabilities & CAP_SCROLL_RECT:
            raise RemoteDisplayError("connected firmware does not advertise SCROLL_RECT")
        self._validate_canvas_rect(x, y, width, height, name="scroll rectangle")
        if not isinstance(delta_x, int) or not isinstance(delta_y, int):
            raise TypeError("scroll deltas must be integers")
        if not -32768 <= delta_x <= 32767 or not -32768 <= delta_y <= 32767:
            raise ValueError("scroll deltas must fit in signed 16 bits")
        self._write(
            MSG_SCROLL_RECT,
            SCROLL_RECT_STRUCT.pack(x, y, width, height, delta_x, delta_y, self._check_color(fill_color)),
        )

    def polyline(self, points: Sequence[tuple[int, int]], color: int, thickness: int = 1) -> None:
        self._ensure_frame()
        point_values = []
        for point in points:
            point_values.append(point)
            if len(point_values) > 255:
                raise ValueError("polyline requires 2 to 255 points")
        if len(point_values) < 2:
            raise ValueError("polyline requires 2 to 255 points")
        self._check_line_thickness(thickness)
        coordinates: list[tuple[int, int]] = []
        for index, point in enumerate(point_values):
            if not isinstance(point, Sequence) or len(point) != 2:
                raise TypeError(f"polyline point {index} must contain exactly two coordinates")
            x = self._check_line_coordinate(point[0], f"points[{index}].x")
            y = self._check_line_coordinate(point[1], f"points[{index}].y")
            coordinates.append((x, y))

        total_work = 0
        for (x0, y0), (x1, y1) in zip(coordinates, coordinates[1:]):
            total_work += self._line_work(x0, y0, x1, y1, thickness)
            if total_work > LINE_MAX_WORK:
                raise ValueError(f"polyline exceeds the firmware work limit of {LINE_MAX_WORK}")

        payload = bytearray(struct.pack("<HBB", self._check_color(color), thickness, len(coordinates)))
        for x, y in coordinates:
            payload.extend(struct.pack("<HH", x, y))
        self._write(MSG_POLYLINE, bytes(payload))

    def _resolve_tile_profile(self, tile_profile: TileProfileName | TileProfile) -> TileProfile:
        profile = get_tile_profile(tile_profile)
        if self.info is None:
            raise RemoteDisplayError("HELLO must complete before selecting a tile profile")
        if not self.info.capabilities & CAP_TILE_PROFILES:
            raise RemoteDisplayError("connected firmware does not advertise tile profiles")
        advertised = self.info.tile_profile(profile.name)
        if (profile.width, profile.height) != (advertised.width, advertised.height):
            raise RemoteDisplayError(
                f"device profile '{profile.name}' is {advertised.width}x{advertised.height}, "
                f"but the host expects {profile.width}x{profile.height}"
            )
        if self.info.width % profile.width or self.info.height % profile.height:
            raise RemoteDisplayError(f"device profile '{profile.name}' does not divide the canvas exactly")
        return profile

    @property
    def tile_transfer_stats(self) -> TileTransferStats:
        return self._tile_transfer_stats

    def reset_tile_transfer_stats(self) -> None:
        self._tile_transfer_stats = TileTransferStats()

    def _record_tile_transfer(
        self,
        *,
        segmented: bool,
        encoded_bytes: int,
        transfer_payload_bytes: int,
        packet_count: int,
    ) -> None:
        current = self._tile_transfer_stats
        header_bytes = packet_count * (12 + (4 if getattr(self, "_strict_packet_crc", False) else 0))
        self._tile_transfer_stats = TileTransferStats(
            direct_tiles=current.direct_tiles + (0 if segmented else 1),
            segmented_tiles=current.segmented_tiles + (1 if segmented else 0),
            encoded_bytes=current.encoded_bytes + encoded_bytes,
            transfer_payload_bytes=current.transfer_payload_bytes + transfer_payload_bytes,
            packet_count=current.packet_count + packet_count,
            packet_header_bytes=current.packet_header_bytes + header_bytes,
            wire_bytes=current.wire_bytes + transfer_payload_bytes + header_bytes,
        )

    def _validate_tile(self, x: int, y: int, width: int, height: int) -> None:
        if width <= 0 or height <= 0 or width > TILE_MAX_WIDTH or height > TILE_MAX_HEIGHT:
            raise ValueError(f"a tile must be 1..{TILE_MAX_WIDTH} by 1..{TILE_MAX_HEIGHT} pixels")
        if x < 0 or y < 0 or x + width > SCREEN_WIDTH or y + height > SCREEN_HEIGHT:
            raise ValueError("tile must fit fully within the display")

    def _validate_scale2_tile(self, x: int, y: int, width: int, height: int) -> None:
        if width <= 0 or height <= 0 or width > SCALE2_TILE_WIDTH or height > SCALE2_TILE_HEIGHT:
            raise ValueError(
                f"a scale2 source tile must be 1..{SCALE2_TILE_WIDTH} by 1..{SCALE2_TILE_HEIGHT} pixels"
            )
        if x < 0 or y < 0 or x + width * 2 > SCREEN_WIDTH or y + height * 2 > SCREEN_HEIGHT:
            raise ValueError("the upscaled destination rectangle must fit fully within the display")

    def _blit_encoded_tile(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: int,
        pixel_format: int,
        codec: int,
        encoded: bytes,
    ) -> None:
        self._ensure_frame()
        self._validate_tile(x, y, width, height)
        if not encoded or len(encoded) > MAX_ENCODED_TILE_BYTES:
            raise ValueError("encoded tile length is outside the supported range")

        tile_header = BLIT_TILE_STRUCT.pack(x, y, width, height, color, pixel_format, codec)
        if len(tile_header) + len(encoded) <= MAX_PAYLOAD:
            self._write(MSG_BLIT_TILE, tile_header + encoded)
            self._record_tile_transfer(
                segmented=False,
                encoded_bytes=len(encoded),
                transfer_payload_bytes=len(tile_header) + len(encoded),
                packet_count=1,
            )
            return

        if self.info is None or not self.info.capabilities & CAP_SEGMENTED_TILES:
            raise RemoteDisplayError("connected firmware does not advertise segmented tile transfers")

        tile_id = self._next_tile_id()
        begin = TILE_BEGIN_STRUCT.pack(
            tile_id,
            x,
            y,
            width,
            height,
            color,
            pixel_format,
            codec,
            len(encoded),
        )
        verify_tile_crc = getattr(self, "_strict_tile_crc", False)
        chunk_capacity = MAX_PAYLOAD - TILE_CHUNK_PREFIX_STRUCT.size
        try:
            if verify_tile_crc:
                begin += TILE_BEGIN_CRC_STRUCT.pack(data_crc32(encoded))
                self._write(MSG_TILE_BEGIN, begin, flags=PACKET_FLAG_TILE_CONTENT_CRC32)
            else:
                self._write(MSG_TILE_BEGIN, begin)

            for offset in range(0, len(encoded), chunk_capacity):
                chunk = encoded[offset:offset + chunk_capacity]
                self._write(MSG_TILE_CHUNK, TILE_CHUNK_PREFIX_STRUCT.pack(tile_id, offset) + chunk)

            self._write(MSG_TILE_END, TILE_END_STRUCT.pack(tile_id))
        except BaseException:
            self._invalidate_session()
            raise
        chunk_count = (len(encoded) + chunk_capacity - 1) // chunk_capacity
        self._record_tile_transfer(
            segmented=True,
            encoded_bytes=len(encoded),
            transfer_payload_bytes=(len(begin) + TILE_END_STRUCT.size +
                                    len(encoded) + chunk_count * TILE_CHUNK_PREFIX_STRUCT.size),
            packet_count=chunk_count + 2,
        )

    def blit_rgb565(self, x: int, y: int, width: int, height: int, pixels: bytes, compression: str = "auto") -> None:
        self._ensure_frame()
        self._validate_tile(x, y, width, height)
        if len(pixels) != width * height * 2:
            raise ValueError("RGB565 tile byte length does not match the supplied dimensions")
        encoded, codec = self._compress_rgb565(pixels, compression)
        self._blit_encoded_tile(x, y, width, height, 0, PIXEL_RGB565, codec, encoded)

    def blit_rgb565_scale2(self, x: int, y: int, width: int, height: int, pixels: bytes, compression: str = "auto") -> None:
        """Draw RGB565 source pixels upscaled 2x on the Pico.

        ``width`` and ``height`` are source dimensions. The destination rectangle
        on the display is ``width*2`` by ``height*2``. This mode is intended for
        animated half-resolution backgrounds that will be overdrawn with normal
        full-resolution primitives, text, and sprites.
        """
        self._ensure_frame()
        self._validate_scale2_tile(x, y, width, height)
        if self.info is None or not self.info.capabilities & CAP_RGB565_SCALE2:
            raise RemoteDisplayError("connected firmware does not advertise RGB565 scale2 tiles")
        if len(pixels) != width * height * 2:
            raise ValueError("RGB565 tile byte length does not match the supplied source dimensions")
        encoded, codec = self._compress_rgb565(pixels, compression)
        if not encoded or len(encoded) > SCALE2_MAX_ENCODED_BYTES:
            raise ValueError(f"encoded scale2 tile exceeds {SCALE2_MAX_ENCODED_BYTES} bytes")
        payload = BLIT_TILE_STRUCT.pack(x, y, width, height, 0, PIXEL_RGB565_SCALE2, codec) + encoded
        if len(payload) > MAX_PAYLOAD:
            raise ValueError(f"scale2 tile payload exceeds {MAX_PAYLOAD} bytes")
        self._write(MSG_BLIT_TILE, payload)
        self._record_tile_transfer(
            segmented=False,
            encoded_bytes=len(encoded),
            transfer_payload_bytes=len(payload),
            packet_count=1,
        )

    def blit_alpha(self, x: int, y: int, width: int, height: int, alpha: bytes, color: int, compression: str = "auto") -> None:
        self._ensure_frame()
        self._validate_tile(x, y, width, height)
        if len(alpha) != width * height:
            raise ValueError("alpha tile byte length does not match the supplied dimensions")
        encoded, codec = self._compress_alpha(alpha, compression)
        self._blit_encoded_tile(x, y, width, height, self._check_color(color), PIXEL_ALPHA8, codec, encoded)

    def blit_palette4(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        palette: Sequence[int],
        indices: bytes | bytearray | memoryview,
    ) -> None:
        """Draw a 1-16 color RGB565 palette tile using packed 4-bit indices.

        Palette4 is a lossy image mode intended for logos, photographs, and other
        mostly-static imagery. It uses a compact per-tile payload and does not
        require a mutable global palette on the Pico.
        """
        self._ensure_frame()
        self._validate_tile(x, y, width, height)
        if self.info is None or not self.info.capabilities & CAP_PALETTE4_TILES:
            raise RemoteDisplayError("connected firmware does not advertise Palette4 tiles")
        palette_values = tuple(self._check_color(value) for value in palette)
        if not 1 <= len(palette_values) <= 16:
            raise ValueError("palette must contain 1..16 RGB565 colors")
        raw_indices = bytes(indices)
        pixel_count = width * height
        if len(raw_indices) != pixel_count:
            raise ValueError("palette index count does not match tile dimensions")
        if any(index >= len(palette_values) for index in raw_indices):
            raise ValueError("palette index is outside the supplied palette")

        packed = bytearray((pixel_count + 1) // 2)
        for index, value in enumerate(raw_indices):
            if index & 1:
                packed[index // 2] |= value
            else:
                packed[index // 2] = value << 4
        encoded = bytearray((len(palette_values),))
        for color in palette_values:
            encoded.extend(struct.pack("<H", color))
        encoded.extend(packed)
        self._blit_encoded_tile(x, y, width, height, 0, PIXEL_INDEX4, CODEC_PALETTE4, bytes(encoded))

    def blit_palette4_scale2(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        palette: Sequence[int],
        indices: bytes | bytearray | memoryview,
    ) -> None:
        """Draw a Palette4 source tile upscaled 2x on the Pico.

        ``width`` and ``height`` are source dimensions. The destination rectangle
        on the display is ``width*2`` by ``height*2``. This is a lossy half-resolution
        transfer path intended for animated backgrounds that still need sharp
        full-resolution overlays.
        """
        self._ensure_frame()
        self._validate_scale2_tile(x, y, width, height)
        if self.info is None or not self.info.capabilities & CAP_PALETTE4_SCALE2:
            raise RemoteDisplayError("connected firmware does not advertise Palette4 scale2 tiles")
        palette_values = tuple(self._check_color(value) for value in palette)
        if not 1 <= len(palette_values) <= 16:
            raise ValueError("palette must contain 1..16 RGB565 colors")
        raw_indices = bytes(indices)
        pixel_count = width * height
        if len(raw_indices) != pixel_count:
            raise ValueError("palette index count does not match tile dimensions")
        if any(index >= len(palette_values) for index in raw_indices):
            raise ValueError("palette index is outside the supplied palette")

        packed = bytearray((pixel_count + 1) // 2)
        for index, value in enumerate(raw_indices):
            if index & 1:
                packed[index // 2] |= value
            else:
                packed[index // 2] = value << 4
        encoded = bytearray((len(palette_values),))
        for color in palette_values:
            encoded.extend(struct.pack("<H", color))
        encoded.extend(packed)
        payload = BLIT_TILE_STRUCT.pack(x, y, width, height, 0, PIXEL_INDEX4_SCALE2, CODEC_PALETTE4) + bytes(encoded)
        if len(payload) > MAX_PAYLOAD:
            raise ValueError(f"scale2 Palette4 tile payload exceeds {MAX_PAYLOAD} bytes")
        self._write(MSG_BLIT_TILE, payload)
        self._record_tile_transfer(
            segmented=False,
            encoded_bytes=len(encoded),
            transfer_payload_bytes=len(payload),
            packet_count=1,
        )

    def _palette4_image_tiles(self, image, profile: TileProfile, *, dither: str) -> Iterable[tuple[int, int, int, int, tuple[int, ...], bytes]]:
        from PIL import Image

        if dither not in {"none", "floyd-steinberg"}:
            raise ValueError("dither must be 'none' or 'floyd-steinberg'")
        source = image.convert("RGB")
        palette_image = source.quantize(
            colors=16,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
        if dither == "none":
            # Preserve the established Palette4 baseline exactly.
            quantized = palette_image
        else:
            # Pillow ignores dither while it creates a Median Cut palette. Map the
            # original RGB image into the already-selected palette in a separate
            # operation so Floyd-Steinberg always affects the index assignment.
            quantized = source.quantize(
                palette=palette_image,
                dither=Image.Dither.FLOYDSTEINBERG,
            )
        palette_bytes = palette_image.getpalette() or []
        raw_palette: list[int] = []
        for index in range(16):
            offset = index * 3
            raw_palette.append(rgb565(palette_bytes[offset], palette_bytes[offset + 1], palette_bytes[offset + 2]))
        indices = quantized.tobytes()
        width, height = quantized.size
        for tile_y in range(0, height, profile.height):
            for tile_x in range(0, width, profile.width):
                tile_width = min(profile.width, width - tile_x)
                tile_height = min(profile.height, height - tile_y)
                tile_indices = bytearray(tile_width * tile_height)
                used: list[int] = []
                remap: dict[int, int] = {}
                for row in range(tile_height):
                    source = (tile_y + row) * width + tile_x
                    destination = row * tile_width
                    for column in range(tile_width):
                        old_index = indices[source + column]
                        if old_index not in remap:
                            remap[old_index] = len(used)
                            used.append(old_index)
                        tile_indices[destination + column] = remap[old_index]
                tile_palette = tuple(raw_palette[index] for index in used)
                yield tile_x, tile_y, tile_width, tile_height, tile_palette, bytes(tile_indices)

    def blit_palette64(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        palette: Sequence[int],
        indices: bytes | bytearray | memoryview,
    ) -> None:
        """Draw a 1-64 color RGB565 palette tile using packed 6-bit indices.

        The payload contains a compact local palette followed by a continuous
        LSB-first six-bit index stream. Palette64 is intended for mostly-static
        imagery that needs more color detail than Palette4.
        """
        self._ensure_frame()
        self._validate_tile(x, y, width, height)
        if self.info is None or not self.info.capabilities & CAP_PALETTE64_TILES:
            raise RemoteDisplayError("connected firmware does not advertise Palette64 tiles")
        palette_values = tuple(self._check_color(value) for value in palette)
        if not 1 <= len(palette_values) <= 64:
            raise ValueError("palette must contain 1..64 RGB565 colors")
        raw_indices = bytes(indices)
        pixel_count = width * height
        if len(raw_indices) != pixel_count:
            raise ValueError("palette index count does not match tile dimensions")
        if any(index >= len(palette_values) for index in raw_indices):
            raise ValueError("palette index is outside the supplied palette")

        packed = bytearray((pixel_count * 6 + 7) // 8)
        for pixel, value in enumerate(raw_indices):
            bit_offset = pixel * 6
            byte_offset = bit_offset // 8
            shift = bit_offset & 7
            packed[byte_offset] |= (value << shift) & 0xFF
            if shift > 2:
                packed[byte_offset + 1] |= value >> (8 - shift)

        encoded = bytearray((len(palette_values),))
        for color in palette_values:
            encoded.extend(struct.pack("<H", color))
        encoded.extend(packed)
        self._blit_encoded_tile(x, y, width, height, 0, PIXEL_INDEX6, CODEC_PALETTE64, bytes(encoded))

    def blit_palette64_scale2(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        palette: Sequence[int],
        indices: bytes | bytearray | memoryview,
    ) -> None:
        """Draw a Palette64 source tile upscaled 2x on the Pico.

        ``width`` and ``height`` are source dimensions. The destination rectangle
        on the display is ``width*2`` by ``height*2``. This is a lossy half-resolution
        transfer path with better color fidelity than Palette4 scale2.
        """
        self._ensure_frame()
        self._validate_scale2_tile(x, y, width, height)
        if self.info is None or not self.info.capabilities & CAP_PALETTE64_SCALE2:
            raise RemoteDisplayError("connected firmware does not advertise Palette64 scale2 tiles")
        palette_values = tuple(self._check_color(value) for value in palette)
        if not 1 <= len(palette_values) <= 64:
            raise ValueError("palette must contain 1..64 RGB565 colors")
        raw_indices = bytes(indices)
        pixel_count = width * height
        if len(raw_indices) != pixel_count:
            raise ValueError("palette index count does not match tile dimensions")
        if any(index >= len(palette_values) for index in raw_indices):
            raise ValueError("palette index is outside the supplied palette")

        packed = bytearray((pixel_count * 6 + 7) // 8)
        for pixel, value in enumerate(raw_indices):
            bit_offset = pixel * 6
            byte_offset = bit_offset // 8
            shift = bit_offset & 7
            packed[byte_offset] |= (value << shift) & 0xFF
            if shift > 2:
                packed[byte_offset + 1] |= value >> (8 - shift)

        encoded = bytearray((len(palette_values),))
        for color in palette_values:
            encoded.extend(struct.pack("<H", color))
        encoded.extend(packed)
        payload = BLIT_TILE_STRUCT.pack(x, y, width, height, 0, PIXEL_INDEX6_SCALE2, CODEC_PALETTE64) + bytes(encoded)
        if len(payload) > MAX_PAYLOAD:
            raise ValueError(f"scale2 Palette64 tile payload exceeds {MAX_PAYLOAD} bytes")
        self._write(MSG_BLIT_TILE, payload)
        self._record_tile_transfer(
            segmented=False,
            encoded_bytes=len(encoded),
            transfer_payload_bytes=len(payload),
            packet_count=1,
        )

    def _palette64_image_tiles(self, image, profile: TileProfile, *, dither: str) -> Iterable[tuple[int, int, int, int, tuple[int, ...], bytes]]:
        from PIL import Image

        if dither not in {"none", "floyd-steinberg"}:
            raise ValueError("dither must be 'none' or 'floyd-steinberg'")
        source = image.convert("RGB")
        palette_image = source.quantize(
            colors=64,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
        if dither == "none":
            quantized = palette_image
        else:
            quantized = source.quantize(
                palette=palette_image,
                dither=Image.Dither.FLOYDSTEINBERG,
            )
        palette_bytes = palette_image.getpalette() or []
        raw_palette: list[int] = []
        for index in range(64):
            offset = index * 3
            raw_palette.append(rgb565(palette_bytes[offset], palette_bytes[offset + 1], palette_bytes[offset + 2]))
        indices = quantized.tobytes()
        width, height = quantized.size
        for tile_y in range(0, height, profile.height):
            for tile_x in range(0, width, profile.width):
                tile_width = min(profile.width, width - tile_x)
                tile_height = min(profile.height, height - tile_y)
                tile_indices = bytearray(tile_width * tile_height)
                used: list[int] = []
                remap: dict[int, int] = {}
                for row in range(tile_height):
                    source_offset = (tile_y + row) * width + tile_x
                    destination = row * tile_width
                    for column in range(tile_width):
                        old_index = indices[source_offset + column]
                        if old_index not in remap:
                            remap[old_index] = len(used)
                            used.append(old_index)
                        tile_indices[destination + column] = remap[old_index]
                tile_palette = tuple(raw_palette[index] for index in used)
                yield tile_x, tile_y, tile_width, tile_height, tile_palette, bytes(tile_indices)

    def draw_image(
        self,
        image,
        x: int,
        y: int,
        background: tuple[int, int, int] = (0, 0, 0),
        compression: str = "auto",
        tile_profile: TileProfileName | TileProfile = "medium",
        dither: str = "none",
    ) -> None:
        from PIL import Image

        profile = self._resolve_tile_profile(tile_profile)
        if isinstance(image, (str, Path)):
            image = Image.open(image)
        if image.mode == "RGBA":
            base = Image.new("RGBA", image.size, (*background, 255))
            image = Image.alpha_composite(base, image).convert("RGB")
        else:
            image = image.convert("RGB")

        width, height = image.size
        if x < 0 or y < 0 or x + width > SCREEN_WIDTH or y + height > SCREEN_HEIGHT:
            raise ValueError("image must fit fully within the display")

        if compression == "palette4":
            for tile_x, tile_y, tile_width, tile_height, palette, indices in self._palette4_image_tiles(
                image, profile, dither=dither
            ):
                self.blit_palette4(x + tile_x, y + tile_y, tile_width, tile_height, palette, indices)
            return

        if compression == "palette64":
            for tile_x, tile_y, tile_width, tile_height, palette, indices in self._palette64_image_tiles(
                image, profile, dither=dither
            ):
                self.blit_palette64(x + tile_x, y + tile_y, tile_width, tile_height, palette, indices)
            return

        for tile_x, tile_y, tile_width, tile_height, tile in self._rgb_image_tiles(image, profile):
            self.blit_rgb565(x + tile_x, y + tile_y, tile_width, tile_height, tile, compression)

    def draw_image_scale2(
        self,
        image,
        x: int = 0,
        y: int = 0,
        background: tuple[int, int, int] = (0, 0, 0),
        compression: str = "auto",
        dither: str = "none",
    ) -> None:
        from PIL import Image

        if isinstance(image, (str, Path)):
            image = Image.open(image)
        if image.mode == "RGBA":
            base = Image.new("RGBA", image.size, (*background, 255))
            image = Image.alpha_composite(base, image).convert("RGB")
        else:
            image = image.convert("RGB")

        width, height = image.size
        if x < 0 or y < 0 or x + width * 2 > SCREEN_WIDTH or y + height * 2 > SCREEN_HEIGHT:
            raise ValueError("the upscaled image must fit fully within the display")

        if compression in {"raw", "rle", "auto"}:
            for tile_x, tile_y, tile_width, tile_height, tile in self._rgb_image_tiles_custom(
                image, SCALE2_TILE_WIDTH, SCALE2_TILE_HEIGHT
            ):
                self.blit_rgb565_scale2(x + tile_x * 2, y + tile_y * 2, tile_width, tile_height, tile, compression)
            return

        if compression == "palette4":
            scale2_profile = TileProfile("scale2", SCALE2_TILE_WIDTH, SCALE2_TILE_HEIGHT)
            for tile_x, tile_y, tile_width, tile_height, palette, indices in self._palette4_image_tiles(
                image, scale2_profile, dither=dither
            ):
                self.blit_palette4_scale2(x + tile_x * 2, y + tile_y * 2, tile_width, tile_height, palette, indices)
            return

        if compression == "palette64":
            scale2_profile = TileProfile("scale2", SCALE2_TILE_WIDTH, SCALE2_TILE_HEIGHT)
            for tile_x, tile_y, tile_width, tile_height, palette, indices in self._palette64_image_tiles(
                image, scale2_profile, dither=dither
            ):
                self.blit_palette64_scale2(x + tile_x * 2, y + tile_y * 2, tile_width, tile_height, palette, indices)
            return

        raise ValueError("scale2 compression must be 'auto', 'raw', 'rle', 'palette4', or 'palette64'")

    @staticmethod
    def _font_object(font, size: int):
        from PIL import ImageFont

        if size <= 0:
            raise ValueError("font size must be positive")
        if font is None:
            return ImageFont.load_default()
        if isinstance(font, (str, Path)):
            return ImageFont.truetype(str(font), size=size)
        return font

    @classmethod
    def measure_text(cls, text: str, font=None, size: int = 18) -> TextMetrics:
        """Measure the alpha mask and visible glyph ink for ``text``.

        This method does not require a connected display and is suitable for
        host-side layout preflight.
        """
        from PIL import Image, ImageDraw

        if not text:
            raise ValueError("text must not be empty")
        font_object = cls._font_object(font, size)
        bounds = font_object.getbbox(text)
        mask_width = max(1, bounds[2] - bounds[0])
        mask_height = max(1, bounds[3] - bounds[1])
        mask = Image.new("L", (mask_width, mask_height), 0)
        ImageDraw.Draw(mask).text((-bounds[0], -bounds[1]), text, fill=255, font=font_object)
        ink = mask.getbbox()
        if ink is None:
            raise ValueError("text produced an empty alpha mask")
        ink_x, ink_y, ink_right, ink_bottom = ink
        return TextMetrics(
            mask_width=mask_width,
            mask_height=mask_height,
            ink_x=ink_x,
            ink_y=ink_y,
            ink_width=ink_right - ink_x,
            ink_height=ink_bottom - ink_y,
        )

    def draw_text(
        self,
        text: str,
        x: int,
        y: int,
        color: int,
        font=None,
        size: int = 18,
        compression: str = "auto",
        tile_profile: TileProfileName | TileProfile = "small",
    ) -> tuple[int, int]:
        """Draw text using the top-left alpha-mask origin.

        For aligned text inside a region, prefer :meth:`draw_text_box`.
        """
        from PIL import Image, ImageDraw

        profile = self._resolve_tile_profile(tile_profile)
        font_object = self._font_object(font, size)
        metrics = self.measure_text(text, font_object, size)
        if x < 0 or y < 0 or x + metrics.mask_width > SCREEN_WIDTH or y + metrics.mask_height > SCREEN_HEIGHT:
            raise ValueError("text must fit fully within the display")

        bounds = font_object.getbbox(text)
        mask = Image.new("L", (metrics.mask_width, metrics.mask_height), 0)
        ImageDraw.Draw(mask).text((-bounds[0], -bounds[1]), text, fill=255, font=font_object)
        for tile_x, tile_y, tile_width, tile_height, tile in self._alpha_image_tiles(mask, profile):
            self.blit_alpha(x + tile_x, y + tile_y, tile_width, tile_height, tile, color, compression)
        return metrics.mask_width, metrics.mask_height

    def draw_text_box(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str,
        color: int,
        *,
        font=None,
        size: int = 18,
        align: str = "left",
        valign: str = "top",
        compression: str = "auto",
        tile_profile: TileProfileName | TileProfile = "small",
    ) -> TextMetrics:
        """Draw text inside a box, aligning actual glyph ink.

        The visible letters are positioned within the requested rectangle. The
        full alpha mask is then offset for font side bearings before transfer.
        """
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > SCREEN_WIDTH or y + height > SCREEN_HEIGHT:
            raise ValueError("text box must fit fully within the display")
        metrics = self.measure_text(text, font, size)
        if metrics.ink_width > width or metrics.ink_height > height:
            raise ValueError("visible text does not fit within the text box")
        if align == "left":
            ink_x = x
        elif align == "center":
            ink_x = x + (width - metrics.ink_width) // 2
        elif align == "right":
            ink_x = x + width - metrics.ink_width
        else:
            raise ValueError("align must be left, center, or right")
        if valign == "top":
            ink_y = y
        elif valign == "middle":
            ink_y = y + (height - metrics.ink_height) // 2
        elif valign == "bottom":
            ink_y = y + height - metrics.ink_height
        else:
            raise ValueError("valign must be top, middle, or bottom")
        mask_x = ink_x - metrics.ink_x
        mask_y = ink_y - metrics.ink_y
        if mask_x < 0 or mask_y < 0 or mask_x + metrics.mask_width > SCREEN_WIDTH or mask_y + metrics.mask_height > SCREEN_HEIGHT:
            raise ValueError("text mask would exceed the display canvas")
        self.draw_text(text, mask_x, mask_y, color, font, size, compression, tile_profile)
        return metrics

    def button(self, x: int, y: int, width: int, height: int, text: str, *, background: int, border: int, text_color: int, font=None, font_size: int = 18) -> None:
        self.fill_rect(x, y, width, height, background)
        self.stroke_rect(x, y, width, height, border, 2)
        self.draw_text_box(x + 6, y + 4, max(1, width - 12), max(1, height - 8), text, text_color, font=font, size=font_size, align="center", valign="middle", compression="rle")

    def checkbox(self, x: int, y: int, checked: bool, label: str, *, foreground: int, background: int, font=None, font_size: int = 17) -> None:
        self.fill_rect(x, y, 24, 24, background)
        self.stroke_rect(x, y, 24, 24, foreground, 2)
        if checked:
            self.line(x + 5, y + 12, x + 10, y + 18, foreground, 3)
            self.line(x + 10, y + 18, x + 20, y + 5, foreground, 3)
        self.draw_text_box(x + 33, y, SCREEN_WIDTH - (x + 33), 24, label, foreground, font=font, size=font_size, align="left", valign="middle", compression="rle")

    def line_chart(self, x: int, y: int, width: int, height: int, values: Sequence[float], *, line_color: int, grid_color: int, background: int, min_value: float | None = None, max_value: float | None = None) -> None:
        self.fill_rect(x, y, width, height, background)
        self.stroke_rect(x, y, width, height, grid_color, 1)
        for division in range(1, 4):
            grid_y = y + (height * division) // 4
            self.line(x + 1, grid_y, x + width - 2, grid_y, grid_color, 1)

        if len(values) < 2:
            return
        lower = min(values) if min_value is None else min_value
        upper = max(values) if max_value is None else max_value
        if math.isclose(lower, upper):
            lower -= 0.5
            upper += 0.5
        points = []
        for index, value in enumerate(values):
            px = x + 1 + ((width - 3) * index) // (len(values) - 1)
            normalized = (value - lower) / (upper - lower)
            py = y + height - 2 - round(normalized * (height - 3))
            points.append((px, max(y + 1, min(y + height - 2, py))))
        self.polyline(points, line_color, 2)

    def bar_chart(self, x: int, y: int, width: int, height: int, values: Sequence[float], *, bar_color: int, grid_color: int, background: int) -> None:
        self.fill_rect(x, y, width, height, background)
        self.stroke_rect(x, y, width, height, grid_color, 1)
        if not values:
            return
        maximum = max(max(values), 1e-9)
        gap = max(2, width // (len(values) * 8))
        bar_width = max(1, (width - gap * (len(values) + 1)) // len(values))
        for index, value in enumerate(values):
            bar_height = max(0, min(height - 2, round((value / maximum) * (height - 2))))
            bar_x = x + gap + index * (bar_width + gap)
            self.fill_rect(bar_x, y + height - 1 - bar_height, bar_width, bar_height, bar_color)

    def pie_chart(self, x: int, y: int, diameter: int, values: Sequence[float], colors: Sequence[int], *, background: int = 0x0000, compression: str = "auto") -> None:
        from PIL import Image, ImageDraw

        if diameter <= 0 or len(values) != len(colors) or not values:
            raise ValueError("pie chart needs positive diameter and matching non-empty values/colors")
        total = sum(max(value, 0) for value in values)
        if total <= 0:
            raise ValueError("pie chart values must contain a positive value")

        image = Image.new("RGB", (diameter, diameter), self._rgb888(background))
        draw = ImageDraw.Draw(image)
        start = -90.0
        for value, color in zip(values, colors):
            angle = 360.0 * max(value, 0) / total
            draw.pieslice((0, 0, diameter - 1, diameter - 1), start, start + angle, fill=self._rgb888(color))
            start += angle
        self.draw_image(image, x, y, compression=compression)

    def poll_events(self, timeout_ms: int = 0, max_events: int = 32) -> list[TouchEvent]:
        deadline = time.monotonic() + timeout_ms / 1000.0
        while len(self._events) < max_events:
            for packet in self._read_once(1 if timeout_ms == 0 else max(1, min(20, int((deadline - time.monotonic()) * 1000)))):
                packet = self._handle_incoming(packet)
                if packet is not None:
                    self._queue_pending(packet)
            if timeout_ms == 0 or time.monotonic() >= deadline:
                break

        events: list[TouchEvent] = []
        while self._events and len(events) < max_events:
            events.append(self._events.popleft())
        return events

    def poll_latest_touch(self, timeout_ms: int = 0) -> TouchEvent | None:
        """Drain queued touch input and return only the newest event.

        This is the low-latency path for drag feedback. Press and release events are
        still delivered by the device, while stale movement samples are coalesced.
        """
        events = self.poll_events(timeout_ms=timeout_ms, max_events=256)
        return events[-1] if events else None

    def wait_for_touch(self, timeout_ms: int | None = None) -> TouchEvent:
        timeout = self.timeout_ms if timeout_ms is None else timeout_ms
        deadline = time.monotonic() + timeout / 1000.0
        while time.monotonic() < deadline:
            events = self.poll_events(timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)), max_events=1)
            if events:
                return events[0]
        raise RemoteDisplayTimeout("timed out waiting for touch input")

    @staticmethod
    def _check_color(color: int) -> int:
        if not 0 <= color <= 0xFFFF:
            raise ValueError("RGB565 colors must be in the range 0x0000..0xffff")
        return color

    @staticmethod
    def _rgb888(color: int) -> tuple[int, int, int]:
        color = RemoteDisplay._check_color(color)
        red = ((color >> 11) & 0x1F) * 255 // 31
        green = ((color >> 5) & 0x3F) * 255 // 63
        blue = (color & 0x1F) * 255 // 31
        return red, green, blue

    @staticmethod
    def _compress_rgb565(pixels: bytes, mode: str) -> tuple[bytes, int]:
        if mode not in {"auto", "raw", "rle"}:
            raise ValueError("compression must be 'auto', 'raw', or 'rle'")
        if mode == "raw":
            return pixels, CODEC_RAW
        encoded = rle_encode_rgb565(pixels)
        if mode == "rle" or len(encoded) < len(pixels):
            return encoded, CODEC_RLE
        return pixels, CODEC_RAW

    @staticmethod
    def _compress_alpha(alpha: bytes, mode: str) -> tuple[bytes, int]:
        if mode not in {"auto", "raw", "rle"}:
            raise ValueError("compression must be 'auto', 'raw', or 'rle'")
        if mode == "raw":
            return alpha, CODEC_RAW
        encoded = rle_encode_alpha8(alpha)
        if mode == "rle" or len(encoded) < len(alpha):
            return encoded, CODEC_RLE
        return alpha, CODEC_RAW

    @staticmethod
    def _text_size(text: str, font, size: int) -> tuple[int, int]:
        metrics = RemoteDisplay.measure_text(text, font, size)
        return metrics.mask_width, metrics.mask_height

    @staticmethod
    def _rgb_image_tiles(image, profile: TileProfile) -> Iterable[tuple[int, int, int, int, bytes]]:
        yield from RemoteDisplay._rgb_image_tiles_custom(image, profile.width, profile.height)

    @staticmethod
    def _rgb_image_tiles_custom(image, tile_width_limit: int, tile_height_limit: int) -> Iterable[tuple[int, int, int, int, bytes]]:
        image = image.convert("RGB")
        width, height = image.size
        for y in range(0, height, tile_height_limit):
            for x in range(0, width, tile_width_limit):
                tile = image.crop((x, y, min(x + tile_width_limit, width), min(y + tile_height_limit, height)))
                tile_width, tile_height = tile.size
                output = bytearray(tile_width * tile_height * 2)
                pixels = tile.get_flattened_data() if hasattr(tile, "get_flattened_data") else tile.getdata()
                for index, (red, green, blue) in enumerate(pixels):
                    struct.pack_into("<H", output, index * 2, rgb565(red, green, blue))
                yield x, y, tile_width, tile_height, bytes(output)

    @staticmethod
    def _alpha_image_tiles(mask, profile: TileProfile) -> Iterable[tuple[int, int, int, int, bytes]]:
        mask = mask.convert("L")
        width, height = mask.size
        for y in range(0, height, profile.height):
            for x in range(0, width, profile.width):
                tile = mask.crop((x, y, min(x + profile.width, width), min(y + profile.height, height)))
                tile_width, tile_height = tile.size
                yield x, y, tile_width, tile_height, tile.tobytes()


__all__ = [
    "DEFAULT_PID",
    "DEFAULT_VID",
    "DisplayInfo",
    "RemoteDisplay",
    "RemoteDisplayAccessError",
    "RemoteDisplayError",
    "RemoteDisplayTimeout",
    "RemoteProtocolError",
    "ResourceCacheInfo",
    "ResourceUploadStats",
    "TouchEvent",
    "TileProfile",
    "TileTransferStats",
    "rgb565",
]
