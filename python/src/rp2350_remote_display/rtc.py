"""UTC RTC types plus a small dependency-free SNTP client for host-side sync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import socket
import struct
import time

_NTP_EPOCH_OFFSET = 2_208_988_800
_NTP_ERA_SECONDS = 1 << 32
_NTP_PACKET_SIZE = 48
_NTP_NEGATIVE_DELAY_TOLERANCE_SECONDS = 0.001


class NtpQueryError(RuntimeError):
    """Raised when an NTP server cannot provide a valid synchronization sample."""


@dataclass(frozen=True)
class RtcReading:
    """Calendar reading returned by the board's PCF85063 RTC.

    ``datetime_utc`` is always timezone-aware UTC. ``weekday`` follows the
    PCF85063 convention, where Sunday is 0 and Saturday is 6.
    """

    datetime_utc: datetime
    weekday: int
    oscillator_valid: bool
    running: bool
    twenty_four_hour: bool


@dataclass(frozen=True)
class NtpSample:
    """One unauthenticated SNTP sample, corrected for network delay."""

    server: str
    server_address: str
    datetime_utc: datetime
    offset_seconds: float
    round_trip_seconds: float
    stratum: int
    leap_indicator: int
    monotonic_at_measurement: float


@dataclass(frozen=True)
class RtcNtpSyncResult:
    """Result of requesting NTP time, writing the RTC, and reading it back."""

    sample: NtpSample
    target_datetime_utc: datetime
    rtc: RtcReading


def _decode_ntp_timestamp(data: bytes, *, reference_unix_seconds: float | None = None) -> float:
    """Decode an NTP timestamp in the era nearest a Unix-time reference."""

    if len(data) != 8:
        raise ValueError("an NTP timestamp must contain eight bytes")
    seconds, fraction = struct.unpack("!II", data)
    if reference_unix_seconds is None:
        reference_unix_seconds = time.time()
    era_zero_unix = seconds - _NTP_EPOCH_OFFSET
    era = math.floor((reference_unix_seconds - era_zero_unix) / _NTP_ERA_SECONDS + 0.5)
    return era_zero_unix + era * _NTP_ERA_SECONDS + fraction / 2**32


def _encode_ntp_timestamp(unix_seconds: float) -> bytes:
    ntp_seconds = unix_seconds + _NTP_EPOCH_OFFSET
    seconds = int(ntp_seconds)
    fraction = int((ntp_seconds - seconds) * 2**32) & 0xFFFFFFFF
    return struct.pack("!II", seconds & 0xFFFFFFFF, fraction)


def query_ntp(
    server: str = "time.cloudflare.com",
    *,
    port: int = 123,
    timeout: float = 2.0,
    max_offset_seconds: float | None = 86_400.0,
) -> NtpSample:
    """Return one UTC sample from an NTP server.

    The query uses the standard unauthenticated NTP client/server exchange.
    It is suitable for setting the board RTC to second-level accuracy on a
    trusted network. ``max_offset_seconds`` rejects a response whose corrected
    time differs implausibly from the host clock; pass ``None`` to disable that
    check deliberately. This function does not implement NTS authentication.
    """

    if not isinstance(server, str) or not server.strip():
        raise ValueError("server must be a non-empty host name or IP address")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be in the range 1..65535")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(float(timeout))
        or timeout <= 0
    ):
        raise ValueError("timeout must be positive")
    if max_offset_seconds is not None and (
        not isinstance(max_offset_seconds, (int, float))
        or isinstance(max_offset_seconds, bool)
        or not math.isfinite(float(max_offset_seconds))
        or max_offset_seconds <= 0
    ):
        raise ValueError("max_offset_seconds must be positive and finite, or None")

    request = bytearray(_NTP_PACKET_SIZE)
    request[0] = 0x23  # LI=0, version=4, client mode=3.
    errors: list[str] = []

    try:
        addresses = socket.getaddrinfo(server, port, type=socket.SOCK_DGRAM)
    except OSError as exc:
        raise NtpQueryError(f"could not resolve NTP server {server!r}: {exc}") from exc

    for family, socktype, proto, _canonname, sockaddr in addresses:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(float(timeout))
                # Connect before timestamping the request. Besides filtering peers,
                # this keeps local route selection out of the measured interval.
                sock.connect(sockaddr)
                t1_wall = time.time()
                t1_monotonic = time.monotonic()
                request[40:48] = _encode_ntp_timestamp(t1_wall)
                sock.send(request)
                response = sock.recv(512)
                t4_monotonic = time.monotonic()
        except OSError as exc:
            errors.append(str(exc))
            continue

        if len(response) < _NTP_PACKET_SIZE:
            errors.append("server returned a truncated NTP packet")
            continue

        leap_indicator = response[0] >> 6
        version = (response[0] >> 3) & 0x07
        mode = response[0] & 0x07
        stratum = response[1]
        if leap_indicator == 3:
            errors.append("server reports unsynchronized time")
            continue
        if mode != 4:
            errors.append(f"server returned NTP mode {mode}, expected server mode 4")
            continue
        if version not in {3, 4}:
            errors.append(f"server returned unsupported NTP version {version}")
            continue
        if not 1 <= stratum <= 15:
            errors.append(f"server returned invalid NTP stratum {stratum}")
            continue
        if response[24:32] != bytes(request[40:48]):
            errors.append("server response did not match this NTP request")
            continue

        if response[32:40] == b"\x00" * 8 or response[40:48] == b"\x00" * 8:
            errors.append("server omitted NTP receive or transmit timestamps")
            continue

        elapsed = t4_monotonic - t1_monotonic
        if elapsed < 0.0:
            errors.append("host monotonic clock moved backwards during the NTP query")
            continue
        # Derive the receive wall time from the monotonic interval so a host clock
        # correction during the exchange cannot corrupt the four-timestamp math.
        t4_wall = t1_wall + elapsed
        t2 = _decode_ntp_timestamp(response[32:40], reference_unix_seconds=t4_wall)
        t3 = _decode_ntp_timestamp(response[40:48], reference_unix_seconds=t4_wall)
        if t3 < t2:
            errors.append("server transmit timestamp precedes its receive timestamp")
            continue

        offset = ((t2 - t1_wall) + (t3 - t4_wall)) / 2.0
        round_trip = elapsed - (t3 - t2)
        if not math.isfinite(offset) or not math.isfinite(round_trip):
            errors.append("server produced non-finite NTP timing values")
            continue
        if round_trip < -_NTP_NEGATIVE_DELAY_TOLERANCE_SECONDS:
            errors.append("server timestamps imply a negative network round trip")
            continue
        if max_offset_seconds is not None and abs(offset) > float(max_offset_seconds):
            errors.append(
                f"server time differs from the host by more than {float(max_offset_seconds):g} seconds"
            )
            continue
        utc_now = datetime.fromtimestamp(t4_wall + offset, tz=timezone.utc)
        peer_address = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else str(sockaddr)
        return NtpSample(
            server=server,
            server_address=peer_address,
            datetime_utc=utc_now,
            offset_seconds=offset,
            round_trip_seconds=max(0.0, round_trip),
            stratum=stratum,
            leap_indicator=leap_indicator,
            monotonic_at_measurement=t4_monotonic,
        )

    detail = "; ".join(errors) if errors else "no usable UDP address"
    raise NtpQueryError(f"could not obtain valid NTP time from {server!r}: {detail}")


def current_utc_from_sample(sample: NtpSample) -> datetime:
    """Advance an NTP sample from its capture instant to the current instant."""

    elapsed = max(0.0, time.monotonic() - sample.monotonic_at_measurement)
    return sample.datetime_utc + timedelta(seconds=elapsed)


def nearest_second(value: datetime) -> datetime:
    """Round an aware UTC datetime to the closest whole second."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    value = value.astimezone(timezone.utc)
    if value.microsecond >= 500_000:
        value += timedelta(seconds=1)
    return value.replace(microsecond=0)
