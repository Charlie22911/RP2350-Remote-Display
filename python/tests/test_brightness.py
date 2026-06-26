from __future__ import annotations

import unittest

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay
from rp2350_remote_display.protocol import CAP_BRIGHTNESS, MSG_ACK, MSG_SET_BRIGHTNESS, Packet, STATUS_OK


class BrightnessTests(unittest.TestCase):
    def test_brightness_does_not_require_a_frame(self) -> None:
        display = RemoteDisplay.__new__(RemoteDisplay)
        display.info = DisplayInfo(6, 450, 600, 18, 24, 30, 40, 45, 60, 4096, CAP_BRIGHTNESS)
        sent: list[tuple[int, bytes]] = []

        def write(message_type: int, payload: bytes = b"") -> int:
            sent.append((message_type, payload))
            return 77

        def wait_for(sequence: int, expected_type: int, timeout_ms=None) -> Packet:
            self.assertEqual(sequence, 77)
            self.assertEqual(expected_type, MSG_ACK)
            return Packet(MSG_ACK, 0, sequence, bytes((STATUS_OK,)))

        display._write = write
        display._wait_for = wait_for
        display.set_brightness(37)

        self.assertEqual(sent, [(MSG_SET_BRIGHTNESS, bytes((37,)))])


if __name__ == "__main__":
    unittest.main()
