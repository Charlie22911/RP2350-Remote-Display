from __future__ import annotations

from collections import deque
import errno
import sys
import types
import unittest
from unittest.mock import patch

from rp2350_remote_display.display import (
    EVENT_QUEUE_LIMIT,
    LINE_MAX_WORK,
    PENDING_PACKET_LIMIT,
    DisplayInfo,
    RemoteDisplay,
    RemoteDisplayAccessError,
    RemoteDisplayError,
    RemoteDisplayTimeout,
    RemoteDisplayTransportError,
    RemoteProtocolError,
    TouchEvent,
    _REQUIRED_CAPABILITIES,
    _select_usb_device,
)
from rp2350_remote_display.protocol import (
    CAP_OPTIONAL_PACKET_CRC32,
    CAP_PALETTE64_TILES,
    CAP_RESOURCE_CACHE,
    MAX_PAYLOAD,
    MSG_ACK,
    MSG_ERROR,
    MSG_PONG,
    PACKET_FLAG_CRC32,
    PROTOCOL_VERSION,
    STATUS_BAD_ARGUMENT,
    STATUS_OK,
    Packet,
)


class USBTimeoutError(Exception):
    errno = errno.ETIMEDOUT


class _OutputEndpoint:
    def __init__(self, *, short: bool = False, error: BaseException | None = None) -> None:
        self.short = short
        self.error = error
        self.packets: list[bytes] = []

    def write(self, packet: bytes, timeout: int) -> int:
        if self.error is not None:
            raise self.error
        self.packets.append(bytes(packet))
        return len(packet) - 1 if self.short else len(packet)


class _InputEndpoint:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error if error is not None else USBTimeoutError("timed out")

    def read(self, size: int, timeout: int):
        raise self.error


def _info(*, capabilities: int = _REQUIRED_CAPABILITIES) -> DisplayInfo:
    return DisplayInfo(
        PROTOCOL_VERSION,
        450,
        600,
        18,
        24,
        30,
        40,
        45,
        60,
        MAX_PAYLOAD,
        capabilities,
    )


def _display(
    *,
    output: _OutputEndpoint | None = None,
    input_: _InputEndpoint | None = None,
    strict_packet_crc: bool = False,
) -> RemoteDisplay:
    display = RemoteDisplay(
        object(),
        output or _OutputEndpoint(),
        input_ or _InputEndpoint(),
        timeout_ms=5,
        strict_packet_crc=strict_packet_crc,
    )
    display.info = _info(
        capabilities=_REQUIRED_CAPABILITIES
        | (CAP_OPTIONAL_PACKET_CRC32 if strict_packet_crc else 0)
    )
    return display


class SequenceAndRecoveryTests(unittest.TestCase):
    def test_unmatched_reply_is_queued_and_later_demultiplexed(self) -> None:
        display = _display()
        reply = Packet(MSG_PONG, 0, 11, b"later")
        self.assertIsNone(display._process_wait_packet(reply, 10, MSG_PONG))
        self.assertEqual(list(display._pending), [reply])
        self.assertIs(display._process_wait_packet(display._pending.popleft(), 11, MSG_PONG), reply)

    def test_wait_preserves_packets_after_the_target_in_one_usb_read(self) -> None:
        display = _display()
        target = Packet(MSG_PONG, 0, 10, b"target")
        trailing = Packet(MSG_PONG, 0, 11, b"trailing")
        display._read_once = lambda timeout_ms: [target, trailing]
        self.assertIs(display._wait_for(10, MSG_PONG, timeout_ms=50), target)
        self.assertEqual(list(display._pending), [trailing])

    def test_async_error_for_fire_and_forget_command_is_not_hidden(self) -> None:
        display = _display()
        error = Packet(MSG_ERROR, 0, 9, bytes((STATUS_BAD_ARGUMENT, 0x07)))
        with self.assertRaises(RemoteProtocolError) as raised:
            display._process_wait_packet(error, 10, MSG_ACK)
        self.assertEqual((raised.exception.status, raised.exception.command, raised.exception.sequence), (3, 7, 9))
        self.assertIsNone(display.info)

    def test_explicitly_expired_error_is_discarded(self) -> None:
        display = _display()
        display._expired_sequences.append(9)
        error = Packet(MSG_ERROR, 0, 9, bytes((STATUS_BAD_ARGUMENT, 0x07)))
        self.assertIsNone(display._process_wait_packet(error, 10, MSG_ACK))
        self.assertEqual(list(display._pending), [])
        self.assertIsNotNone(display.info)

    def test_timeout_invalidates_uncertain_session_state(self) -> None:
        display = _display()
        display._active_frame_id = 12
        with self.assertRaises(RemoteDisplayTimeout):
            display._wait_for(7, MSG_PONG, timeout_ms=0)
        self.assertIsNone(display.info)
        self.assertIsNone(display._active_frame_id)
        self.assertIn(7, display._expired_sequences)

    def test_late_error_from_timed_out_request_is_quarantined(self) -> None:
        display = _display()
        with self.assertRaises(RemoteDisplayTimeout):
            display._wait_for(7, MSG_PONG, timeout_ms=0)

        late = Packet(MSG_ERROR, 0, 7, bytes((STATUS_BAD_ARGUMENT, 0x07)))
        self.assertIsNone(display._process_wait_packet(late, 8, MSG_PONG))
        self.assertEqual(list(display._pending), [])

    def test_touch_event_queue_retains_only_the_most_recent_events(self) -> None:
        display = _display()
        for index in range(EVENT_QUEUE_LIMIT + 1):
            display._events.append(TouchEvent(index, 2, True, 1))

        self.assertEqual(len(display._events), EVENT_QUEUE_LIMIT)
        self.assertEqual(display._events[0].x, 1)
        self.assertEqual(display._events[-1].x, EVENT_QUEUE_LIMIT)

    def test_recover_session_clears_state_then_negotiates_again(self) -> None:
        display = _display()
        display._active_frame_id = 12
        display._events.append(TouchEvent(1, 2, True, 1))
        calls: list[tuple[str, int]] = []
        recovered = _info()
        display._drain_input = lambda duration_ms: calls.append(("drain", duration_ms))
        display.hello = lambda retries=1: calls.append(("hello", retries)) or recovered

        self.assertIs(display.recover_session(retries=4, drain_ms=25), recovered)
        self.assertEqual(calls, [("drain", 25), ("hello", 4)])
        self.assertIsNone(display.info)
        self.assertIsNone(display._active_frame_id)
        self.assertEqual(list(display._events), [])

    def test_frame_abort_always_marks_the_session_for_recovery(self) -> None:
        display = _display()
        display._active_frame_id = 3
        display._write = lambda message_type, payload=b"", flags=0: 22
        display._wait_for = lambda sequence, expected_type, timeout_ms=None: Packet(
            MSG_ACK, 0, sequence, bytes((STATUS_OK,))
        )
        display.frame_abort()
        self.assertIsNone(display.info)
        self.assertIsNone(display._active_frame_id)

    def test_staged_resource_failure_invalidates_session(self) -> None:
        display = _display()
        display.info = _info(capabilities=CAP_RESOURCE_CACHE | CAP_PALETTE64_TILES)
        display._write = lambda *args, **kwargs: (_ for _ in ()).throw(
            RemoteDisplayTransportError("transfer failed")
        )
        with self.assertRaises(RemoteDisplayTransportError):
            display.cache_palette64(1, 1, 1, [0x0000], b"\x00")
        self.assertIsNone(display.info)

    def test_pending_reply_overflow_fails_instead_of_dropping_a_reply(self) -> None:
        display = _display()
        display._pending = deque(Packet(MSG_PONG, 0, index + 1, b"") for index in range(PENDING_PACKET_LIMIT))
        with self.assertRaises(RemoteDisplayError):
            display._queue_pending(Packet(MSG_PONG, 0, PENDING_PACKET_LIMIT + 1, b""))
        self.assertIsNone(display.info)


class TransportTests(unittest.TestCase):
    def test_access_error_is_wrapped_and_invalidates_session(self) -> None:
        display = _display(output=_OutputEndpoint(error=PermissionError(errno.EACCES, "denied")))
        with self.assertRaises(RemoteDisplayAccessError):
            display._write(1)
        self.assertIsNone(display.info)

    def test_other_read_error_is_wrapped_and_invalidates_session(self) -> None:
        display = _display(input_=_InputEndpoint(OSError(errno.EIO, "unplugged")))
        with self.assertRaises(RemoteDisplayTransportError):
            display._read_once(5)
        self.assertIsNone(display.info)

    def test_usb_timeout_is_a_normal_empty_poll(self) -> None:
        display = _display()
        self.assertEqual(display._read_once(5), [])
        self.assertIsNotNone(display.info)

    def test_short_write_is_rejected_and_invalidates_session(self) -> None:
        display = _display(output=_OutputEndpoint(short=True))
        with self.assertRaises(RemoteDisplayTransportError):
            display._write(1)
        self.assertIsNone(display.info)

    def test_strict_crc_rejects_an_unprotected_device_packet(self) -> None:
        display = _display(strict_packet_crc=True)
        with self.assertRaises(RemoteDisplayError):
            display._handle_incoming(Packet(MSG_PONG, 0, 1, b"pong"))
        self.assertIsNone(display.info)

    def test_strict_crc_accepts_a_protected_device_packet(self) -> None:
        display = _display(strict_packet_crc=True)
        packet = Packet(MSG_PONG, PACKET_FLAG_CRC32, 1, b"pong")
        self.assertIs(display._handle_incoming(packet), packet)

    def test_failed_open_reattaches_kernel_driver_and_disposes_resources(self) -> None:
        class USBError(Exception):
            pass

        class Device:
            bus = 1
            address = 2

            def __init__(self) -> None:
                self.detached: list[int] = []
                self.attached: list[int] = []

            def is_kernel_driver_active(self, interface: int) -> bool:
                return True

            def detach_kernel_driver(self, interface: int) -> None:
                self.detached.append(interface)

            def attach_kernel_driver(self, interface: int) -> None:
                self.attached.append(interface)

            def set_configuration(self) -> None:
                pass

            def get_active_configuration(self):
                return []

        device = Device()
        disposed: list[object] = []
        core = types.ModuleType("usb.core")
        core.USBError = USBError
        core.find = lambda **kwargs: [device]
        util = types.ModuleType("usb.util")
        util.dispose_resources = lambda value: disposed.append(value)
        util.release_interface = lambda value, interface: None
        usb = types.ModuleType("usb")
        usb.__path__ = []
        usb.core = core
        usb.util = util

        with patch.dict(sys.modules, {"usb": usb, "usb.core": core, "usb.util": util}):
            with self.assertRaises(RemoteDisplayError):
                RemoteDisplay.open()

        self.assertEqual(device.detached, [0])
        self.assertEqual(device.attached, [0])
        self.assertEqual(disposed, [device])

    def test_close_releases_claim_reattaches_and_disposes(self) -> None:
        class Device:
            def __init__(self) -> None:
                self.attached: list[int] = []

            def attach_kernel_driver(self, interface: int) -> None:
                self.attached.append(interface)

        device = Device()
        released: list[tuple[object, int]] = []
        disposed: list[object] = []
        util = types.ModuleType("usb.util")
        util.release_interface = lambda value, interface: released.append((value, interface))
        util.dispose_resources = lambda value: disposed.append(value)
        usb = types.ModuleType("usb")
        usb.__path__ = []
        usb.util = util
        display = RemoteDisplay(
            device,
            _OutputEndpoint(),
            _InputEndpoint(),
            interface_number=2,
            detached_kernel_interface=0,
        )

        with patch.dict(sys.modules, {"usb": usb, "usb.util": util}):
            display.close()

        self.assertEqual(released, [(device, 2)])
        self.assertEqual(device.attached, [0])
        self.assertEqual(disposed, [device])


class HelloAndInputValidationTests(unittest.TestCase):
    def test_valid_hello_invariants_are_accepted(self) -> None:
        _display()._validate_hello_info(_info())

    def test_hello_rejects_wrong_geometry_payload_limit_and_capabilities(self) -> None:
        display = _display()
        values = list(_info().__dict__.values())
        for field, replacement in (("width", 449), ("max_payload", MAX_PAYLOAD - 1), ("capabilities", 0)):
            changed = dict(_info().__dict__)
            changed[field] = replacement
            with self.subTest(field=field), self.assertRaises(RemoteDisplayError):
                display._validate_hello_info(DisplayInfo(**changed))

    def test_strict_crc_requires_the_firmware_capability(self) -> None:
        display = _display(strict_packet_crc=True)
        with self.assertRaises(RemoteDisplayError):
            display._validate_hello_info(_info())

    def test_ping_rejects_payload_larger_than_firmware_reply_buffer(self) -> None:
        display = _display()
        with self.assertRaises(ValueError):
            display.ping(b"x" * 65)

    def test_line_work_matches_firmware_clipping_and_even_thickness_rules(self) -> None:
        self.assertEqual(RemoteDisplay._line_work(0, 0, 449, 599, 32), 600 * 33 * 33)
        self.assertEqual(RemoteDisplay._line_work(60_000, 60_000, 65_535, 65_535, 32), 0)
        self.assertLess(RemoteDisplay._line_work(65_535, 65_535, 0, 0, 32), LINE_MAX_WORK)

    def test_line_rejects_excess_thickness_and_invalid_coordinates(self) -> None:
        display = _display()
        display._active_frame_id = 1
        display._write = lambda *args, **kwargs: 1
        with self.assertRaises(ValueError):
            display.line(0, 0, 449, 599, 0xFFFF, thickness=33)
        with self.assertRaises(ValueError):
            display.line(-1, 0, 449, 599, 0xFFFF)

    def test_polyline_rejects_total_work_before_sending_any_pixels(self) -> None:
        display = _display()
        display._active_frame_id = 1
        writes: list[object] = []
        display._write = lambda *args, **kwargs: writes.append(args) or 1
        with self.assertRaises(ValueError):
            display.polyline([(0, 0), (449, 599), (0, 0)], 0xFFFF, thickness=32)
        self.assertEqual(writes, [])


class DeviceSelectionTests(unittest.TestCase):
    class Device:
        def __init__(self, serial: str | None, bus: int, address: int) -> None:
            self.serial_number = serial
            self.iSerialNumber = 0
            self.bus = bus
            self.address = address

    class Util:
        @staticmethod
        def get_string(device, index):
            raise AssertionError("serial property should have been used")

    def test_selector_chooses_serial_bus_and_address(self) -> None:
        first = self.Device("ONE", 1, 2)
        second = self.Device("TWO", 1, 3)
        self.assertIs(
            _select_usb_device(
                [first, second], self.Util, serial_number="TWO", bus=1, address=3
            ),
            second,
        )

    def test_selector_refuses_an_ambiguous_first_match(self) -> None:
        with self.assertRaises(RemoteDisplayError):
            _select_usb_device(
                [self.Device("ONE", 1, 2), self.Device("TWO", 1, 3)],
                self.Util,
                serial_number=None,
                bus=None,
                address=None,
            )

    def test_selector_reports_no_matching_device(self) -> None:
        with self.assertRaises(RemoteDisplayError):
            _select_usb_device(
                [self.Device("ONE", 1, 2)],
                self.Util,
                serial_number="MISSING",
                bus=None,
                address=None,
            )


if __name__ == "__main__":
    unittest.main()
