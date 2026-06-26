#!/usr/bin/env python3
"""Read the board RTC or synchronize it from a host-side NTP query."""

from __future__ import annotations

import argparse

from rp2350_remote_display import NtpQueryError, RemoteDisplay, RemoteDisplayError


def format_rtc(prefix: str, rtc) -> None:
    print(f"{prefix}: {rtc.datetime_utc.isoformat()}")
    print(f"  weekday (Sunday=0): {rtc.weekday}")
    print(f"  oscillator valid: {rtc.oscillator_valid}")
    print(f"  running: {rtc.running}")
    print(f"  24-hour mode: {rtc.twenty_four_hour}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--read", action="store_true", help="read the RTC without using the network")
    action.add_argument("--sync-ntp", action="store_true", help="query NTP on this host, then write the board RTC")
    parser.add_argument("--server", default="time.cloudflare.com", help="NTP server for --sync-ntp")
    parser.add_argument("--timeout", type=float, default=2.0, help="NTP timeout in seconds")
    args = parser.parse_args()

    try:
        with RemoteDisplay.open(timeout_ms=3000) as display:
            if args.sync_ntp:
                result = display.sync_rtc_from_ntp(args.server, timeout=args.timeout)
                print(f"NTP server: {result.sample.server} ({result.sample.server_address})")
                print(f"NTP stratum: {result.sample.stratum}")
                print(f"NTP round trip: {result.sample.round_trip_seconds:.4f} s")
                print(f"RTC target: {result.target_datetime_utc.isoformat()}")
                format_rtc("RTC readback", result.rtc)
            else:
                format_rtc("RTC", display.read_rtc())
    except (NtpQueryError, RemoteDisplayError, ValueError) as exc:
        print(f"RTC operation failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
