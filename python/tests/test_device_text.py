from __future__ import annotations

import struct
import unittest

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay, RemoteDisplayError
from rp2350_remote_display.protocol import (
    CAP_DEVICE_TEXT,
    DRAW_TEXT_PREFIX_STRUCT,
    FONT_INFO_REPLY_STRUCT,
    MEASURE_TEXT_PREFIX_STRUCT,
    MSG_DRAW_TEXT,
    MSG_FONT_INFO,
    MSG_FONT_INFO_REPLY,
    MSG_MEASURE_TEXT,
    MSG_MEASURE_TEXT_REPLY,
    PROTOCOL_VERSION,
    Packet,
)


class DeviceTextTests(unittest.TestCase):
    def make_display(self) -> RemoteDisplay:
        display = object.__new__(RemoteDisplay)
        display.info = DisplayInfo(
            PROTOCOL_VERSION,
            450,
            600,
            18,
            24,
            30,
            40,
            45,
            60,
            4096,
            CAP_DEVICE_TEXT,
        )
        display._active_frame_id = None
        display._writes = []

        def write(message_type: int, payload: bytes = b"", flags: int = 0) -> int:
            display._writes.append((message_type, payload, flags))
            return len(display._writes)

        def wait_for(sequence: int, expected_type: int, timeout_ms: int | None = None) -> Packet:
            if expected_type == MSG_FONT_INFO_REPLY:
                payload = FONT_INFO_REPLY_STRUCT.pack(0, 8, 16, 14, 2, 0, 0x003F, 127011, 2)
            elif expected_type == MSG_MEASURE_TEXT_REPLY:
                payload = struct.pack("<HHHH", 56, 16, 7, 0)
            else:
                raise AssertionError(f"unexpected reply type: {expected_type}")
            return Packet(expected_type, 0, sequence, payload)

        display._write = write
        display._wait_for = wait_for
        return display

    def test_font_information_uses_the_device_query(self) -> None:
        display = self.make_display()
        info = display.device_font_info()
        self.assertEqual((info.font_id, info.cell_width, info.cell_height), (0, 8, 16))
        self.assertEqual((info.fallback_codepoint, info.glyph_count, info.coverage_version), (0x003F, 127011, 2))
        self.assertEqual(display._writes, [(MSG_FONT_INFO, b"\x00", 0)])

    def test_measurement_uses_utf8_and_device_metrics(self) -> None:
        display = self.make_display()
        metrics = display.measure_device_text("CPU 42%", scale=1)
        self.assertEqual((metrics.width, metrics.height, metrics.glyph_count, metrics.missing_glyph_count), (56, 16, 7, 0))
        message_type, payload, flags = display._writes[0]
        self.assertEqual((message_type, flags), (MSG_MEASURE_TEXT, 0))
        self.assertEqual(payload[:MEASURE_TEXT_PREFIX_STRUCT.size], MEASURE_TEXT_PREFIX_STRUCT.pack(0, 1))
        self.assertEqual(payload[MEASURE_TEXT_PREFIX_STRUCT.size:], b"CPU 42%")

    def test_draw_command_uses_a_compact_prefix_and_utf8_payload(self) -> None:
        display = self.make_display()
        display._active_frame_id = 7
        display.draw_device_text("CPU Ω", 12, 34, 0xFFFF, scale=2)
        self.assertEqual(display._writes[0][0], MSG_DRAW_TEXT)
        payload = display._writes[0][1]
        self.assertEqual(DRAW_TEXT_PREFIX_STRUCT.unpack_from(payload), (12, 34, 0xFFFF, 0, 2))
        self.assertEqual(payload[DRAW_TEXT_PREFIX_STRUCT.size:], "CPU Ω".encode("utf-8"))

    def test_font_queries_require_the_capability(self) -> None:
        display = self.make_display()
        display.info = DisplayInfo(
            PROTOCOL_VERSION, 450, 600, 18, 24, 30, 40, 45, 60, 4096, 0
        )
        with self.assertRaises(RemoteDisplayError):
            display.device_font_info()

    def test_scale_and_frame_rules_are_checked_before_transmission(self) -> None:
        display = self.make_display()
        with self.assertRaises(ValueError):
            display.measure_device_text("x", scale=0)
        with self.assertRaises(RemoteDisplayError):
            display.draw_device_text("x", 0, 0, 0xFFFF)


if __name__ == "__main__":
    unittest.main()
