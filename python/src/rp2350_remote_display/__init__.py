"""Python host library for RP2350 Remote Display firmware protocol 16."""

from .canvas import Canvas, rgb565_to_rgb888
from .dirty_tiles import DirtyTilePresenter, DirtyTilePresentStats
from .display import (
    DEFAULT_PID,
    DEFAULT_VID,
    DisplayInfo,
    DeviceFontInfo,
    DeviceTextMetrics,
    RemoteDisplay,
    RemoteDisplayAccessError,
    RemoteDisplayError,
    RemoteDisplayTimeout,
    RemoteDisplayTransportError,
    RemoteProtocolError,
    ResourceCacheInfo,
    ResourceUploadStats,
    TileTransferStats,
    TextMetrics,
    TouchEvent,
)
from .layout import CoordinateSpace, DebugOverlay, Layout, Rect
from .rtc import NtpQueryError, NtpSample, RtcNtpSyncResult, RtcReading, query_ntp
from .protocol import PROTOCOL_VERSION, TILE_PROFILES, TileProfile, rgb565

__version__ = "1.2.18.dev0"

__all__ = [
    "__version__",
    "Canvas",
    "CoordinateSpace",
    "DEFAULT_PID",
    "DEFAULT_VID",
    "DebugOverlay",
    "DirtyTilePresenter",
    "DirtyTilePresentStats",
    "DisplayInfo",
    "DeviceFontInfo",
    "DeviceTextMetrics",
    "Layout",
    "PROTOCOL_VERSION",
    "Rect",
    "RemoteDisplay",
    "RemoteDisplayAccessError",
    "RemoteDisplayError",
    "RemoteDisplayTimeout",
    "RemoteDisplayTransportError",
    "RemoteProtocolError",
    "NtpQueryError",
    "NtpSample",
    "RtcNtpSyncResult",
    "RtcReading",
    "ResourceCacheInfo",
    "ResourceUploadStats",
    "TILE_PROFILES",
    "TileProfile",
    "TileTransferStats",
    "TextMetrics",
    "TouchEvent",
    "query_ntp",
    "rgb565",
    "rgb565_to_rgb888",
]
