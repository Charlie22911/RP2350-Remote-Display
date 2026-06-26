from __future__ import annotations

from dataclasses import dataclass
import time

from .display import RemoteDisplay, RemoteDisplayError, TileTransferStats
from .protocol import CAP_DIRTY_TILE_PRESENT, SCREEN_HEIGHT, SCREEN_WIDTH, TileProfile, TileProfileName


@dataclass(frozen=True)
class DirtyTilePresentStats:
    profile: TileProfile
    frame_sent: bool
    changed_tiles: int
    total_tiles: int
    raw_changed_bytes: int
    changed_regions: int
    transfer: TileTransferStats
    elapsed_seconds: float

    @property
    def unchanged_tiles(self) -> int:
        return self.total_tiles - self.changed_tiles


class DirtyTilePresenter:
    """Presents lossless RGB565 framebuffers using changed tiles or changed sub-rectangles."""

    def __init__(
        self,
        display: RemoteDisplay,
        *,
        tile_profile: TileProfileName | TileProfile = "small",
        compression: str = "auto",
        region_mode: str = "tile",
    ) -> None:
        if display.info is None:
            raise RemoteDisplayError("HELLO must complete before creating a DirtyTilePresenter")
        if not display.info.capabilities & CAP_DIRTY_TILE_PRESENT:
            raise RemoteDisplayError("connected firmware does not advertise dirty-tile presentation")
        if compression not in {"auto", "raw", "rle"}:
            raise ValueError("compression must be 'auto', 'raw', or 'rle'")
        if region_mode not in {"tile", "rect"}:
            raise ValueError("region_mode must be 'tile' or 'rect'")

        self._display = display
        self._profile = display._resolve_tile_profile(tile_profile)
        self._compression = compression
        self._region_mode = region_mode
        self._previous: bytes | None = None

    @property
    def tile_profile(self) -> TileProfile:
        return self._profile

    @property
    def region_mode(self) -> str:
        """Return ``tile`` or ``rect`` for the current delta strategy."""
        return self._region_mode

    def reset(self) -> None:
        """Forget the prior host frame so the next present sends the complete canvas."""
        self._previous = None

    @staticmethod
    def _validate_frame(frame: bytes | bytearray | memoryview) -> bytes:
        raw = bytes(frame)
        required = SCREEN_WIDTH * SCREEN_HEIGHT * 2
        if len(raw) != required:
            raise ValueError(f"RGB565 canvas must contain exactly {required} bytes")
        return raw

    @staticmethod
    def _extract_tile(frame: bytes, x: int, y: int, width: int, height: int) -> bytes:
        row_bytes = width * 2
        stride = SCREEN_WIDTH * 2
        start = y * stride + x * 2
        if width == SCREEN_WIDTH:
            return frame[start:start + height * stride]
        return b"".join(
            frame[start + row * stride:start + row * stride + row_bytes]
            for row in range(height)
        )

    @staticmethod
    def _changed_bounds(current: bytes, previous: bytes, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int] | None:
        """Return the smallest changed rectangle inside one tile in screen coordinates."""
        stride = SCREEN_WIDTH * 2
        min_x = width
        min_y = height
        max_x = -1
        max_y = -1
        for row in range(height):
            offset = (y + row) * stride + x * 2
            current_row = current[offset:offset + width * 2]
            previous_row = previous[offset:offset + width * 2]
            if current_row == previous_row:
                continue
            for column in range(width):
                pixel = column * 2
                if current_row[pixel:pixel + 2] != previous_row[pixel:pixel + 2]:
                    min_x = min(min_x, column)
                    min_y = min(min_y, row)
                    max_x = max(max_x, column)
                    max_y = max(max_y, row)
        if max_x < 0:
            return None
        return x + min_x, y + min_y, max_x - min_x + 1, max_y - min_y + 1

    @staticmethod
    def _extract_rect(frame: bytes, x: int, y: int, width: int, height: int) -> bytes:
        return DirtyTilePresenter._extract_tile(frame, x, y, width, height)

    @staticmethod
    def _transfer_delta(before: TileTransferStats, after: TileTransferStats) -> TileTransferStats:
        return TileTransferStats(
            direct_tiles=after.direct_tiles - before.direct_tiles,
            segmented_tiles=after.segmented_tiles - before.segmented_tiles,
            encoded_bytes=after.encoded_bytes - before.encoded_bytes,
            transfer_payload_bytes=after.transfer_payload_bytes - before.transfer_payload_bytes,
            packet_count=after.packet_count - before.packet_count,
            packet_header_bytes=after.packet_header_bytes - before.packet_header_bytes,
            wire_bytes=after.wire_bytes - before.wire_bytes,
        )

    def present(
        self,
        frame: bytes | bytearray | memoryview,
        *,
        force_frame: bool = False,
        timeout_ms: int | None = None,
    ) -> DirtyTilePresentStats:
        """Compare a full RGB565 canvas with the prior frame and send changed tile regions.

        ``region_mode="tile"`` sends whole changed profile tiles. ``region_mode="rect"``
        sends the smallest changed rectangle inside each changed tile. Both paths remain
        lossless RGB565 and support RAW or RLE transport compression.

        ``force_frame=True`` emits an empty frame transaction when no tiles differ. It is
        useful for protocol testing, but normal callers should leave it disabled.
        """
        current = self._validate_frame(frame)
        profile = self._profile
        changed: list[tuple[int, int, int, int, bytes]] = []
        changed_tiles = 0

        for y in range(0, SCREEN_HEIGHT, profile.height):
            for x in range(0, SCREEN_WIDTH, profile.width):
                tile = self._extract_tile(current, x, y, profile.width, profile.height)
                if self._previous is None:
                    changed.append((x, y, profile.width, profile.height, tile))
                    changed_tiles += 1
                    continue
                previous_tile = self._extract_tile(self._previous, x, y, profile.width, profile.height)
                if tile == previous_tile:
                    continue
                changed_tiles += 1
                if self._region_mode == "tile":
                    changed.append((x, y, profile.width, profile.height, tile))
                    continue
                bounds = self._changed_bounds(current, self._previous, x, y, profile.width, profile.height)
                if bounds is None:
                    continue
                region_x, region_y, region_width, region_height = bounds
                changed.append((region_x, region_y, region_width, region_height,
                                self._extract_rect(current, region_x, region_y, region_width, region_height)))

        started = time.monotonic()
        before = self._display.tile_transfer_stats
        frame_sent = bool(changed) or force_frame
        if frame_sent:
            with self._display.frame(timeout_ms=timeout_ms):
                for x, y, width, height, pixels in changed:
                    self._display.blit_rgb565(x, y, width, height, pixels, compression=self._compression)
        elapsed = time.monotonic() - started
        after = self._display.tile_transfer_stats
        self._previous = current

        return DirtyTilePresentStats(
            profile=profile,
            frame_sent=frame_sent,
            changed_tiles=changed_tiles,
            total_tiles=profile.tile_count,
            raw_changed_bytes=sum(width * height * 2 for _, _, width, height, _ in changed),
            changed_regions=len(changed),
            transfer=self._transfer_delta(before, after),
            elapsed_seconds=elapsed,
        )
