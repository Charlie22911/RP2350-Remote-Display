from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from rp2350_remote_display.display import DisplayInfo, RemoteDisplay, RemoteDisplayError
from rp2350_remote_display.protocol import (
    CAP_RTC_PCF85063,
    MSG_ACK,
    MSG_RTC_READ,
    MSG_RTC_READ_REPLY,
    MSG_RTC_SET,
    PROTOCOL_VERSION,
    RTC_FLAG_24_HOUR,
    RTC_FLAG_OSCILLATOR_VALID,
    RTC_FLAG_RUNNING,
    RTC_READ_REPLY_STRUCT,
    RTC_SET_STRUCT,
    STATUS_OK,
    Packet,
)
from rp2350_remote_display.rtc import NtpSample, RtcReading


class RtcCommandTests(unittest.TestCase):
    def make_display(self, *, capabilities: int = CAP_RTC_PCF85063) -> RemoteDisplay:
        display = object.__new__(RemoteDisplay)
        display.info = DisplayInfo(
            PROTOCOL_VERSION, 450, 600, 18, 24, 30, 40, 45, 60, 4096, capabilities
        )
        display._active_frame_id = None
        display._writes: list[tuple[int, bytes, int]] = []

        def write(message_type: int, payload: bytes = b"", flags: int = 0) -> int:
            display._writes.append((message_type, payload, flags))
            return len(display._writes)

        display._write = write
        return display

    def test_read_rtc_decodes_calendar_and_status_flags(self) -> None:
        display = self.make_display()
        payload = RTC_READ_REPLY_STRUCT.pack(
            2026, 6, 25, 16, 17, 18, 4,
            RTC_FLAG_OSCILLATOR_VALID | RTC_FLAG_RUNNING | RTC_FLAG_24_HOUR,
        )

        def wait_for(sequence: int, expected_type: int, timeout_ms: int | None = None) -> Packet:
            self.assertEqual(sequence, 1)
            self.assertEqual(expected_type, MSG_RTC_READ_REPLY)
            return Packet(MSG_RTC_READ_REPLY, 0, sequence, payload)

        display._wait_for = wait_for
        reading = display.read_rtc()

        self.assertEqual(display._writes, [(MSG_RTC_READ, b"", 0)])
        self.assertEqual(reading.datetime_utc, datetime(2026, 6, 25, 16, 17, 18, tzinfo=timezone.utc))
        self.assertEqual(reading.weekday, 4)
        self.assertTrue(reading.oscillator_valid)
        self.assertTrue(reading.running)
        self.assertTrue(reading.twenty_four_hour)

    def test_set_rtc_normalizes_to_utc_and_uses_pcf_weekday(self) -> None:
        display = self.make_display()
        requested = datetime(2026, 6, 25, 10, 34, 56, tzinfo=timezone(timedelta(hours=-4)))
        reply_payload = RTC_READ_REPLY_STRUCT.pack(
            2026, 6, 25, 14, 34, 56, 4,
            RTC_FLAG_OSCILLATOR_VALID | RTC_FLAG_RUNNING | RTC_FLAG_24_HOUR,
        )

        def wait_for(sequence: int, expected_type: int, timeout_ms: int | None = None) -> Packet:
            if expected_type == MSG_ACK:
                return Packet(MSG_ACK, 0, sequence, bytes((STATUS_OK,)))
            self.assertEqual(expected_type, MSG_RTC_READ_REPLY)
            return Packet(MSG_RTC_READ_REPLY, 0, sequence, reply_payload)

        display._wait_for = wait_for
        verified = display.set_rtc(requested, verify=True)

        self.assertEqual(
            display._writes[0],
            (MSG_RTC_SET, RTC_SET_STRUCT.pack(2026, 6, 25, 14, 34, 56, 4), 0),
        )
        self.assertEqual(display._writes[1], (MSG_RTC_READ, b"", 0))
        self.assertIsNotNone(verified)
        assert verified is not None
        self.assertEqual(verified.datetime_utc.hour, 14)
        self.assertEqual(verified.weekday, 4)

    def test_set_rtc_can_skip_readback(self) -> None:
        display = self.make_display()
        display._wait_for = lambda sequence, expected_type, timeout_ms=None: Packet(
            MSG_ACK, 0, sequence, bytes((STATUS_OK,))
        )
        result = display.set_rtc(datetime(2026, 1, 4, 0, 0, 0, tzinfo=timezone.utc), verify=False)
        self.assertIsNone(result)
        self.assertEqual(len(display._writes), 1)

    def test_rtc_rejects_naive_values_missing_capability_and_open_frames(self) -> None:
        display = self.make_display()
        with self.assertRaises(ValueError):
            display.set_rtc(datetime(2026, 1, 1, 0, 0, 0), verify=False)

        display = self.make_display(capabilities=0)
        with self.assertRaises(RemoteDisplayError):
            display.read_rtc()

        display = self.make_display()
        display._active_frame_id = 3
        with self.assertRaises(RemoteDisplayError):
            display.read_rtc()

    def test_sync_rtc_from_ntp_writes_host_sample_without_touching_system_clock(self) -> None:
        display = self.make_display()
        sample = NtpSample(
            server="test.ntp",
            server_address="192.0.2.10",
            datetime_utc=datetime(2026, 6, 25, 14, 34, 56, 600_000, tzinfo=timezone.utc),
            offset_seconds=0.0,
            round_trip_seconds=0.02,
            stratum=2,
            leap_indicator=0,
            monotonic_at_measurement=1.0,
        )
        result_reading = RtcReading(
            datetime_utc=datetime(2026, 6, 25, 14, 34, 57, tzinfo=timezone.utc),
            weekday=4,
            oscillator_valid=True,
            running=True,
            twenty_four_hour=True,
        )
        calls: list[datetime] = []
        display.set_rtc = lambda value, verify=True: calls.append(value) or result_reading

        with patch("rp2350_remote_display.display.query_ntp", return_value=sample) as query, patch(
            "rp2350_remote_display.display.current_utc_from_sample", return_value=sample.datetime_utc
        ):
            result = display.sync_rtc_from_ntp("test.ntp", timeout=0.3)

        self.assertEqual(calls, [datetime(2026, 6, 25, 14, 34, 57, tzinfo=timezone.utc)])
        self.assertEqual(result.sample, sample)
        self.assertEqual(result.target_datetime_utc, calls[0])
        self.assertEqual(result.rtc, result_reading)
        query.assert_called_once_with(
            "test.ntp", port=123, timeout=0.3, max_offset_seconds=86_400.0
        )


if __name__ == "__main__":
    unittest.main()
