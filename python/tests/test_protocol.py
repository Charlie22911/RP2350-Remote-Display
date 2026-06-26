from __future__ import annotations

import struct
import unittest

from rp2350_remote_display.protocol import (
    CAP_BRIGHTNESS,
    CAP_DEVICE_TEXT,
    CAP_COPY_RECT,
    CAP_SCROLL_RECT,
    CAP_RTC_PCF85063,
    DRAW_TEXT_PREFIX_STRUCT,
    COPY_RECT_STRUCT,
    SCROLL_RECT_STRUCT,
    RTC_SET_STRUCT,
    RTC_READ_REPLY_STRUCT,
    FONT_INFO_REPLY_STRUCT,
    MEASURE_TEXT_PREFIX_STRUCT,
    MEASURE_TEXT_REPLY_STRUCT,
    PACKET_FLAG_CRC32,
    MSG_HELLO,
    PROTOCOL_VERSION,
    PacketParser,
    data_crc32,
    pack_packet,
    rle_encode_alpha8,
    rle_encode_rgb565,
)


class PacketTests(unittest.TestCase):
    def test_packet_parser_handles_fragmentation_and_noise(self) -> None:
        packet = pack_packet(MSG_HELLO, 7, struct.pack("<H", PROTOCOL_VERSION))
        parser = PacketParser()
        self.assertEqual(parser.feed(b"noise" + packet[:7]), [])
        parsed = parser.feed(packet[7:])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].message_type, MSG_HELLO)
        self.assertEqual(parsed[0].sequence, 7)
        self.assertEqual(parsed[0].payload, struct.pack("<H", PROTOCOL_VERSION))

    def test_packet_parser_rejects_bad_crc_and_resynchronizes(self) -> None:
        good = pack_packet(MSG_HELLO, 8, struct.pack("<H", PROTOCOL_VERSION), packet_crc=True)
        corrupt = bytearray(pack_packet(MSG_HELLO, 7, struct.pack("<H", PROTOCOL_VERSION), packet_crc=True))
        corrupt[-1] ^= 0x55
        parser = PacketParser()
        parsed = parser.feed(corrupt + good)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].sequence, 8)
        self.assertGreater(parser.bad_packets, 0)

    def test_default_packets_do_not_include_a_crc_field(self) -> None:
        packet = pack_packet(MSG_HELLO, 1, b"x")
        self.assertEqual(len(packet), 12 + 1)
        parsed = PacketParser().feed(packet)
        self.assertEqual(parsed[0].flags, 0)

    def test_opt_in_packets_include_and_validate_crc(self) -> None:
        packet = pack_packet(MSG_HELLO, 1, b"x", packet_crc=True)
        self.assertEqual(len(packet), 12 + 4 + 1)
        parsed = PacketParser().feed(packet)
        self.assertEqual(parsed[0].flags, PACKET_FLAG_CRC32)

    def test_rgb565_rle(self) -> None:
        raw = struct.pack("<HHHHH", 0x1234, 0x1234, 0xABCD, 0xABCD, 0xABCD)
        self.assertEqual(rle_encode_rgb565(raw), bytes((2, 0x34, 0x12, 3, 0xCD, 0xAB)))

    def test_alpha_rle(self) -> None:
        self.assertEqual(rle_encode_alpha8(bytes((0, 0, 0, 255, 255))), bytes((3, 0, 2, 255)))

    def test_data_crc_matches_standard_crc32(self) -> None:
        self.assertEqual(data_crc32(b"remote display"), 0x3D2A46F8)

    def test_brightness_capability_flag_is_stable(self) -> None:
        self.assertEqual(CAP_BRIGHTNESS, 1 << 8)

    def test_device_text_wire_structures_are_stable(self) -> None:
        self.assertEqual(CAP_DEVICE_TEXT, 1 << 19)
        self.assertEqual(FONT_INFO_REPLY_STRUCT.size, 14)
        self.assertEqual(MEASURE_TEXT_PREFIX_STRUCT.size, 2)
        self.assertEqual(MEASURE_TEXT_REPLY_STRUCT.size, 8)
        self.assertEqual(DRAW_TEXT_PREFIX_STRUCT.size, 8)
        self.assertEqual(CAP_COPY_RECT, 1 << 20)
        self.assertEqual(CAP_SCROLL_RECT, 1 << 21)
        self.assertEqual(COPY_RECT_STRUCT.size, 12)
        self.assertEqual(SCROLL_RECT_STRUCT.size, 14)
        self.assertEqual(CAP_RTC_PCF85063, 1 << 23)
        self.assertEqual(RTC_SET_STRUCT.size, 8)
        self.assertEqual(RTC_READ_REPLY_STRUCT.size, 9)


if __name__ == "__main__":
    unittest.main()
