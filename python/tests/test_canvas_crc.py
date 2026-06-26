from __future__ import annotations

import struct
import unittest

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay
from rp2350_remote_display.protocol import (
    CAP_CANVAS_CRC32,
    MSG_CANVAS_CRC,
    MSG_CANVAS_CRC_REPLY,
    Packet,
)


class CanvasCrcTests(unittest.TestCase):
    def test_canvas_crc_uses_a_diagnostic_request_outside_a_frame(self) -> None:
        display = RemoteDisplay.__new__(RemoteDisplay)
        display.info = DisplayInfo(6, 450, 600, 18, 24, 30, 40, 45, 60, 4096, CAP_CANVAS_CRC32)
        display._active_frame_id = None
        display.timeout_ms = 1000
        sent: list[tuple[int, bytes]] = []

        def write(message_type: int, payload: bytes = b"") -> int:
            sent.append((message_type, payload))
            return 19

        def wait_for(sequence: int, expected_type: int, timeout_ms=None) -> Packet:
            self.assertEqual(sequence, 19)
            self.assertEqual(expected_type, MSG_CANVAS_CRC_REPLY)
            self.assertGreaterEqual(timeout_ms, 5000)
            return Packet(MSG_CANVAS_CRC_REPLY, 0, sequence, struct.pack("<I", 0xA1B2C3D4))

        display._write = write
        display._wait_for = wait_for
        self.assertEqual(display.canvas_crc32(), 0xA1B2C3D4)
        self.assertEqual(sent, [(MSG_CANVAS_CRC, b"")])


if __name__ == "__main__":
    unittest.main()
