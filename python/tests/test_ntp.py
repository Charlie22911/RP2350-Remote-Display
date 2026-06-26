from __future__ import annotations

from datetime import datetime, timezone
import socket
import unittest
from unittest.mock import patch

from rp2350_remote_display.rtc import (
    NtpQueryError,
    NtpSample,
    _decode_ntp_timestamp,
    _encode_ntp_timestamp,
    current_utc_from_sample,
    nearest_second,
    query_ntp,
)


class _FakeSocket:
    def __init__(self, *, bad_originate: bool = False) -> None:
        self.bad_originate = bad_originate
        self.request = b""
        self.timeout: float | None = None

    def __enter__(self) -> "_FakeSocket":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def sendto(self, data: bytes, sockaddr) -> int:
        self.request = bytes(data)
        return len(data)

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        response = bytearray(48)
        response[0] = 0x24  # LI=0, version=4, server mode=4
        response[1] = 2
        response[24:32] = b"\x00" * 8 if self.bad_originate else self.request[40:48]
        response[32:40] = _encode_ntp_timestamp(1000.020)
        response[40:48] = _encode_ntp_timestamp(1000.030)
        return bytes(response), ("192.0.2.10", 123)


class NtpTests(unittest.TestCase):
    def test_timestamp_codec_round_trip_is_sub_microsecond(self) -> None:
        value = 1_700_000_123.125
        self.assertAlmostEqual(_decode_ntp_timestamp(_encode_ntp_timestamp(value)), value, places=6)

    def test_query_ntp_uses_four_timestamp_offset_and_checks_originate(self) -> None:
        fake = _FakeSocket()
        with patch("rp2350_remote_display.rtc.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.10", 123))
        ]), patch("rp2350_remote_display.rtc.socket.socket", return_value=fake), patch(
            "rp2350_remote_display.rtc.time.time", side_effect=[1000.000, 1000.100]
        ), patch("rp2350_remote_display.rtc.time.monotonic", side_effect=[10.000, 10.100]):
            sample = query_ntp("test.ntp", timeout=0.4)

        self.assertEqual(fake.timeout, 0.4)
        self.assertEqual(sample.server_address, "192.0.2.10")
        self.assertEqual(sample.stratum, 2)
        self.assertAlmostEqual(sample.offset_seconds, -0.025, places=6)
        self.assertAlmostEqual(sample.round_trip_seconds, 0.090, places=6)
        self.assertEqual(sample.datetime_utc, datetime.fromtimestamp(1000.075, tz=timezone.utc))

    def test_query_ntp_rejects_unrelated_response(self) -> None:
        fake = _FakeSocket(bad_originate=True)
        with patch("rp2350_remote_display.rtc.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.10", 123))
        ]), patch("rp2350_remote_display.rtc.socket.socket", return_value=fake), patch(
            "rp2350_remote_display.rtc.time.time", side_effect=[1000.000, 1000.100]
        ), patch("rp2350_remote_display.rtc.time.monotonic", side_effect=[10.000, 10.100]):
            with self.assertRaises(NtpQueryError):
                query_ntp("test.ntp")

    def test_sample_advance_and_nearest_second(self) -> None:
        sample = NtpSample(
            server="test.ntp",
            server_address="192.0.2.10",
            datetime_utc=datetime(2026, 6, 25, 14, 34, 56, 400_000, tzinfo=timezone.utc),
            offset_seconds=0.0,
            round_trip_seconds=0.01,
            stratum=2,
            leap_indicator=0,
            monotonic_at_measurement=10.0,
        )
        with patch("rp2350_remote_display.rtc.time.monotonic", return_value=10.75):
            advanced = current_utc_from_sample(sample)
        self.assertEqual(advanced, datetime(2026, 6, 25, 14, 34, 57, 150_000, tzinfo=timezone.utc))
        self.assertEqual(nearest_second(advanced), datetime(2026, 6, 25, 14, 34, 57, tzinfo=timezone.utc))
        self.assertEqual(
            nearest_second(datetime(2026, 6, 25, 14, 34, 57, 500_000, tzinfo=timezone.utc)),
            datetime(2026, 6, 25, 14, 34, 58, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
