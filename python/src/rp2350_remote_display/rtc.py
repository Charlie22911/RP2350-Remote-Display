"""UTC RTC types plus a small dependency-free SNTP client for host-side sync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import socket
import struct
import time

_NTP_EPOCH_OFFSET = 2_208_988_800
_NTP_PACKET_SIZE = 48


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


def _decode_ntp_timestamp(data: bytes) -> float:
    if len(data) != 8:
        raise ValueError("an NTP timestamp must contain eight bytes")
    seconds, fraction = struct.unpack("!II", data)
    return seconds - _NTP_EPOCH_OFFSET + fraction / 2**32


def _encode_ntp_timestamp(unix_seconds: float) -> bytes:
    ntp_seconds = unix_seconds + _NTP_EPOCH_OFFSET
    seconds = int(ntp_seconds)
    fraction = int((ntp_seconds - seconds) * 2**32) & 0xFFFFFFFF
    return struct.pack("!II", seconds & 0xFFFFFFFF, fraction)


def query_ntp(server: str = "time.cloudflare.com", *, port: int = 123, timeout: float = 2.0) -> NtpSample:
    """Return one UTC sample from an NTP server.

    The query uses the standard unauthenticated NTP client/server exchange.
    It is suitable for setting the board RTC to second-level accuracy on a
    trusted network. It does not implement NTS authentication.
    """

    if not isinstance(server, str) or not server.strip():
        raise ValueError("server must be a non-empty host name or IP address")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be in the range 1..65535")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be positive")

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
                t1_wall = time.time()
                t1_monotonic = time.monotonic()
                request[40:48] = _encode_ntp_timestamp(t1_wall)
                sock.sendto(request, sockaddr)
                response, peer = sock.recvfrom(512)
                t4_wall = time.time()
                t4_monotonic = time.monotonic()
        except OSError as exc:
            errors.append(str(exc))
            continue

        if len(response) < _NTP_PACKET_SIZE:
            errors.append("server returned a truncated NTP packet")
            continue

        leap_indicator = response[0] >> 6
        mode = response[0] & 0x07
        stratum = response[1]
        if leap_indicator == 3:
            errors.append("server reports unsynchronized time")
            continue
        if mode != 4:
            errors.append(f"server returned NTP mode {mode}, expected server mode 4")
            continue
        if not 1 <= stratum <= 15:
            errors.append(f"server returned invalid NTP stratum {stratum}")
            continue
        if response[24:32] != bytes(request[40:48]):
            errors.append("server response did not match this NTP request")
            continue

        t2 = _decode_ntp_timestamp(response[32:40])
        t3 = _decode_ntp_timestamp(response[40:48])
        if t2 == 0.0 or t3 == 0.0:
            errors.append("server omitted NTP receive or transmit timestamps")
            continue

        offset = ((t2 - t1_wall) + (t3 - t4_wall)) / 2.0
        round_trip = (t4_wall - t1_wall) - (t3 - t2)
        utc_now = datetime.fromtimestamp(t4_wall + offset, tz=timezone.utc)
        peer_address = peer[0] if isinstance(peer, tuple) and peer else str(peer)
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
