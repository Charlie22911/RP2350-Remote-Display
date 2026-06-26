from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable, Literal
import zlib

PROTOCOL_VERSION = 16
PACKET_MAGIC = 0x31445052
MAX_PAYLOAD = 4096
SCREEN_WIDTH = 450
SCREEN_HEIGHT = 600

TILE_SMALL_WIDTH = 18
TILE_SMALL_HEIGHT = 24
TILE_MEDIUM_WIDTH = 30
TILE_MEDIUM_HEIGHT = 40
TILE_LARGE_WIDTH = 45
TILE_LARGE_HEIGHT = 60
TILE_MAX_WIDTH = TILE_LARGE_WIDTH
TILE_MAX_HEIGHT = TILE_LARGE_HEIGHT
MAX_ENCODED_TILE_BYTES = TILE_LARGE_WIDTH * TILE_LARGE_HEIGHT * 3

PACKET_FLAG_CRC32 = 1 << 0
PACKET_FLAG_TILE_CONTENT_CRC32 = 1 << 1
PACKET_FLAG_KNOWN = PACKET_FLAG_CRC32 | PACKET_FLAG_TILE_CONTENT_CRC32

TileProfileName = Literal["small", "medium", "large"]


@dataclass(frozen=True)
class TileProfile:
    name: TileProfileName
    width: int
    height: int

    @property
    def columns(self) -> int:
        return SCREEN_WIDTH // self.width

    @property
    def rows(self) -> int:
        return SCREEN_HEIGHT // self.height

    @property
    def tile_count(self) -> int:
        return self.columns * self.rows


TILE_PROFILES: dict[TileProfileName, TileProfile] = {
    "small": TileProfile("small", TILE_SMALL_WIDTH, TILE_SMALL_HEIGHT),
    "medium": TileProfile("medium", TILE_MEDIUM_WIDTH, TILE_MEDIUM_HEIGHT),
    "large": TileProfile("large", TILE_LARGE_WIDTH, TILE_LARGE_HEIGHT),
}

MSG_HELLO = 0x01
MSG_PING = 0x02
MSG_FRAME_BEGIN = 0x03
MSG_FRAME_END = 0x04
MSG_FILL_RECT = 0x05
MSG_STROKE_RECT = 0x06
MSG_LINE = 0x07
MSG_POLYLINE = 0x08
MSG_BLIT_TILE = 0x09
MSG_CLEAR = 0x0A
MSG_SET_BRIGHTNESS = 0x0B
MSG_FRAME_ABORT = 0x0C
MSG_SESSION_CLOSE = 0x0D
MSG_TILE_BEGIN = 0x0E
MSG_TILE_CHUNK = 0x0F
MSG_TILE_END = 0x10
MSG_CANVAS_CRC = 0x11
MSG_RESOURCE_BEGIN = 0x12
MSG_RESOURCE_CHUNK = 0x13
MSG_RESOURCE_END = 0x14
MSG_DRAW_RESOURCE = 0x15
MSG_RESOURCE_RELEASE = 0x16
MSG_RESOURCE_CLEAR = 0x17
MSG_RESOURCE_INFO = 0x18
MSG_FONT_INFO = 0x19
MSG_MEASURE_TEXT = 0x1A
MSG_DRAW_TEXT = 0x1B
MSG_COPY_RECT = 0x1C
MSG_SCROLL_RECT = 0x1D
MSG_RTC_READ = 0x1E
MSG_RTC_SET = 0x1F

MSG_HELLO_REPLY = 0x81
MSG_PONG = 0x82
MSG_ACK = 0x83
MSG_ERROR = 0x84
MSG_CANVAS_CRC_REPLY = 0x85
MSG_RESOURCE_INFO_REPLY = 0x86
MSG_FONT_INFO_REPLY = 0x87
MSG_MEASURE_TEXT_REPLY = 0x88
MSG_RTC_READ_REPLY = 0x89
MSG_TOUCH = 0x90

STATUS_OK = 0
STATUS_BAD_PACKET = 1
STATUS_BAD_COMMAND = 2
STATUS_BAD_ARGUMENT = 3
STATUS_DECODE_ERROR = 4
STATUS_OUT_OF_MEMORY = 5
STATUS_NOT_READY = 6
STATUS_FRAME_STATE = 7
STATUS_BAD_CRC = 8
STATUS_TIMEOUT = 9
STATUS_DISPLAY_ERROR = 10
STATUS_TILE_STATE = 11
STATUS_RESOURCE_STATE = 12
STATUS_RESOURCE_NOT_FOUND = 13
STATUS_RTC_ERROR = 14

PIXEL_RGB565 = 0
PIXEL_ALPHA8 = 1
PIXEL_INDEX4 = 2
PIXEL_INDEX6 = 3
PIXEL_RGB565_SCALE2 = 4
PIXEL_INDEX4_SCALE2 = 5
PIXEL_INDEX6_SCALE2 = 6

CODEC_RAW = 0
CODEC_RLE = 1
CODEC_PALETTE4 = 2
CODEC_PALETTE64 = 3

CAP_RGB565_TILES = 1 << 0
CAP_ALPHA8_TILES = 1 << 1
CAP_RLE = 1 << 2
CAP_TOUCH_EVENTS = 1 << 3
CAP_PRIMITIVES = 1 << 4
CAP_OPTIONAL_PACKET_CRC32 = 1 << 5
# Compatibility name for older host-side capability displays.
CAP_PACKET_CRC32 = CAP_OPTIONAL_PACKET_CRC32
CAP_FRAME_TRANSACTIONS = 1 << 6
CAP_WAITING_SCREEN = 1 << 7
CAP_BRIGHTNESS = 1 << 8
CAP_SESSION_REATTACH = 1 << 9
CAP_TILE_PROFILES = 1 << 10
CAP_SEGMENTED_TILES = 1 << 11
CAP_CANVAS_CRC32 = 1 << 12
CAP_OPTIONAL_TILE_CRC32 = 1 << 13
CAP_DIRTY_TILE_PRESENT = 1 << 14
CAP_RESOURCE_CACHE = 1 << 15
CAP_PALETTE4_TILES = 1 << 16
CAP_ASYNC_PRESENT = 1 << 17
CAP_TOUCH_COALESCING = 1 << 18
CAP_DEVICE_TEXT = 1 << 19
CAP_COPY_RECT = 1 << 20
CAP_SCROLL_RECT = 1 << 21
CAP_PALETTE64_TILES = 1 << 22
CAP_RTC_PCF85063 = 1 << 23
CAP_RGB565_SCALE2 = 1 << 24
CAP_PALETTE4_SCALE2 = 1 << 25
CAP_PALETTE64_SCALE2 = 1 << 26

_HEADER = struct.Struct("<IBBHI")
_CHECKSUM = struct.Struct("<I")
HELLO_REPLY_STRUCT = struct.Struct("<HHHHHHHHHHI")
BLIT_TILE_STRUCT = struct.Struct("<HHHHHBB")
TILE_BEGIN_STRUCT = struct.Struct("<IHHHHHBBH")
TILE_BEGIN_CRC_STRUCT = struct.Struct("<I")
TILE_CHUNK_PREFIX_STRUCT = struct.Struct("<IH")
TILE_END_STRUCT = struct.Struct("<I")
RESOURCE_BEGIN_STRUCT = struct.Struct("<IHHBBH")
RESOURCE_CHUNK_PREFIX_STRUCT = struct.Struct("<IH")
RESOURCE_END_STRUCT = struct.Struct("<I")
DRAW_RESOURCE_STRUCT = struct.Struct("<IHHH")
RESOURCE_RELEASE_STRUCT = struct.Struct("<I")
RESOURCE_INFO_REPLY_STRUCT = struct.Struct("<HHII")
FONT_INFO_REPLY_STRUCT = struct.Struct("<BBBBBBHIH")
MEASURE_TEXT_PREFIX_STRUCT = struct.Struct("<BB")
MEASURE_TEXT_REPLY_STRUCT = struct.Struct("<HHHH")
DRAW_TEXT_PREFIX_STRUCT = struct.Struct("<HHHBB")
COPY_RECT_STRUCT = struct.Struct("<HHHHHH")
SCROLL_RECT_STRUCT = struct.Struct("<HHHHhhH")
RTC_SET_STRUCT = struct.Struct("<HBBBBBB")
RTC_READ_REPLY_STRUCT = struct.Struct("<HBBBBBBB")

RTC_FLAG_OSCILLATOR_VALID = 1 << 0
RTC_FLAG_RUNNING = 1 << 1
RTC_FLAG_24_HOUR = 1 << 2


@dataclass(frozen=True)
class Packet:
    message_type: int
    flags: int
    sequence: int
    payload: bytes


def packet_crc32(message_type: int, flags: int, sequence: int, payload: bytes) -> int:
    metadata = struct.pack("<BBHI", message_type, flags, len(payload), sequence)
    crc = 0xFFFFFFFF
    for byte in metadata + payload:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return (~crc) & 0xFFFFFFFF


def data_crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def pack_packet(
    message_type: int,
    sequence: int,
    payload: bytes = b"",
    flags: int = 0,
    *,
    packet_crc: bool = False,
) -> bytes:
    if not 0 <= message_type <= 0xFF:
        raise ValueError("message type must fit in one byte")
    if not 0 <= flags <= 0xFF:
        raise ValueError("flags must fit in one byte")
    if flags & ~PACKET_FLAG_KNOWN:
        raise ValueError("packet contains unknown flags")
    if packet_crc:
        flags |= PACKET_FLAG_CRC32
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence must fit in 32 bits")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload exceeds {MAX_PAYLOAD} bytes")

    header = _HEADER.pack(PACKET_MAGIC, message_type, flags, len(payload), sequence)
    if flags & PACKET_FLAG_CRC32:
        checksum = _CHECKSUM.pack(packet_crc32(message_type, flags, sequence, payload))
        return header + checksum + payload
    return header + payload


class PacketParser:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self.bad_packets = 0

    def feed(self, data: bytes | bytearray | memoryview) -> list[Packet]:
        self._buffer.extend(data)
        packets: list[Packet] = []

        while len(self._buffer) >= _HEADER.size:
            magic, message_type, flags, payload_length, sequence = _HEADER.unpack_from(self._buffer)
            if magic != PACKET_MAGIC or payload_length > MAX_PAYLOAD or flags & ~PACKET_FLAG_KNOWN:
                del self._buffer[0]
                self.bad_packets += 1
                continue

            checksum_size = _CHECKSUM.size if flags & PACKET_FLAG_CRC32 else 0
            total = _HEADER.size + checksum_size + payload_length
            if len(self._buffer) < total:
                break

            payload_offset = _HEADER.size + checksum_size
            payload = bytes(self._buffer[payload_offset:total])
            if flags & PACKET_FLAG_CRC32:
                (checksum,) = _CHECKSUM.unpack_from(self._buffer, _HEADER.size)
                if checksum != packet_crc32(message_type, flags, sequence, payload):
                    del self._buffer[0]
                    self.bad_packets += 1
                    continue

            del self._buffer[:total]
            packets.append(Packet(message_type, flags, sequence, payload))

        return packets


def get_tile_profile(profile: TileProfileName | TileProfile) -> TileProfile:
    if isinstance(profile, TileProfile):
        return profile
    try:
        return TILE_PROFILES[profile]
    except KeyError as exc:
        names = ", ".join(TILE_PROFILES)
        raise ValueError(f"tile_profile must be one of: {names}") from exc


def rgb565(red: int, green: int, blue: int) -> int:
    for value in (red, green, blue):
        if not 0 <= value <= 255:
            raise ValueError("RGB components must be in the range 0..255")
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


def rgb888_to_rgb565_bytes(pixels: Iterable[tuple[int, int, int]]) -> bytes:
    output = bytearray()
    for red, green, blue in pixels:
        output.extend(struct.pack("<H", rgb565(red, green, blue)))
    return bytes(output)


def rle_encode_rgb565(raw_pixels: bytes) -> bytes:
    if len(raw_pixels) % 2:
        raise ValueError("RGB565 data must contain whole 16-bit pixels")

    output = bytearray()
    pixel_count = len(raw_pixels) // 2
    index = 0
    while index < pixel_count:
        value = raw_pixels[index * 2:index * 2 + 2]
        run = 1
        while index + run < pixel_count and run < 255:
            next_value = raw_pixels[(index + run) * 2:(index + run) * 2 + 2]
            if next_value != value:
                break
            run += 1
        output.append(run)
        output.extend(value)
        index += run
    return bytes(output)


def rle_encode_alpha8(alpha: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(alpha):
        value = alpha[index]
        run = 1
        while index + run < len(alpha) and run < 255 and alpha[index + run] == value:
            run += 1
        output.extend((run, value))
        index += run
    return bytes(output)
