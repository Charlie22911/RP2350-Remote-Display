# Protocol reference

This reference describes USB display protocol **16**. It is implemented by the RP2350 firmware and the bundled Python library.

The protocol version must match exactly. During `HELLO`, the host sends its version and the firmware rejects a mismatch with status `BAD_ARGUMENT` (`3`). Capability bits describe optional features in an otherwise matching protocol. They do not provide backward compatibility across protocol versions.

For implementation-level definitions, use these files together with this guide:

- `firmware/firmware/remote_protocol.h`
- `firmware/firmware/remote_protocol.c`
- `python/src/rp2350_remote_display/protocol.py`

## Transport and packet format

The firmware uses a USB vendor-bulk interface with one 64-byte IN endpoint and one 64-byte OUT endpoint. Protocol packets may span several USB transfers.

The same USB interface and display protocol are used on Linux and Windows. Linux applications reach the interface through the system libusb library and the project's udev rule. On Windows 11, firmware from the 1.2.18 development line publishes a Microsoft OS 2.0 descriptor set containing the `WINUSB` compatible ID and project device-interface GUID `{70A0597B-D8E4-4580-8201-73B3B5E47581}`. Windows therefore selects its inbox WinUSB driver without a project-specific INF or manual driver association. These enumeration descriptors select the host driver; they do not change the display packet format or require separate firmware for Linux.

Every packet begins with this 12-byte little-endian header:

| Field | Size | Description |
|---|---:|---|
| `magic` | 4 bytes | `0x31445052` |
| `type` | 1 byte | Message type |
| `flags` | 1 byte | Integrity flags |
| `payload_length` | 2 bytes | Payload size, up to 4096 bytes |
| `sequence` | 4 bytes | Host-selected request sequence |

All multi-byte fields and RGB565 values are little-endian.

Two optional integrity checks exist for diagnostic and test use:

- Packet CRC32, indicated by flag `0x01`. A 4-byte CRC follows the header and covers the message metadata and payload.
- Tile or resource content CRC32, indicated by flag `0x02` on the corresponding begin command. It validates the encoded content before the firmware accepts it.

USB already supplies link-layer error detection and retry. Enable the optional checks when validating a transport path or reproducing a suspected corruption issue.

A CRC-protected `HELLO` enables CRC protection on firmware replies for that session. The Python `strict_packet_crc=True` mode protects its requests and rejects any incoming packet that does not also carry a valid packet CRC.

## Session and frame lifecycle

A normal session follows this sequence:

1. Send `HELLO` with protocol 16.
2. Read `HELLO_REPLY` and validate geometry, payload limits, tile profiles, and required capability bits.
3. Send `FRAME_BEGIN`.
4. Send drawing commands.
5. Send `FRAME_END`.
6. Wait for its `ACK`, which follows display presentation.

`HELLO` can be used to establish a clean new session after an interrupted host. It resets any frame, segmented transfer, and resource-cache state on the device. `SESSION_CLOSE` ends the session while leaving the visible framebuffer unchanged.

Every synchronous reply or error carries the sequence of the request that produced it. A host must match both sequence and expected reply type; it must not apply a delayed error from an expired request to a newer request. `TOUCH` remains asynchronous and should be routed independently.

### Command-state rules

| Command group | Allowed state |
|---|---|
| `FRAME_BEGIN`, `FRAME_END`, `FRAME_ABORT` | Established session |
| Primitives, direct tiles, text, `COPY_RECT`, `SCROLL_RECT`, `DRAW_RESOURCE` | Active frame |
| Segmented tile commands | Active frame |
| Resource upload, release, clear, and inspection | Outside a frame |
| Font inspection, text measurement, framebuffer CRC, RTC read/write | Outside a frame |
| Brightness | Established session with no pending presentation |

Malformed data, an invalid command state, a transfer timeout, or a decode failure can invalidate the active session. Treat an `ERROR` response as a failed operation and restore a known session state before continuing. The Python host invalidates its negotiated `DisplayInfo` after protocol or transport uncertainty. Call `recover_session()` to drain stale input and perform a new `HELLO`; upload all cached resources again afterward.

The firmware discards an incomplete packet after 250 ms without progress. A segmented tile or resource upload expires after 1,000 ms without transfer activity. Either staged-transfer timeout invalidates the session and clears cached resources; a tile timeout also returns the display to its waiting state. Perform a new `HELLO` and upload required resources again.

## Message groups

| Group | Requests |
|---|---|
| Session and diagnostics | `HELLO`, `PING`, `FRAME_BEGIN`, `FRAME_END`, `FRAME_ABORT`, `SESSION_CLOSE`, `CANVAS_CRC` |
| Primitives | `CLEAR`, `FILL_RECT`, `STROKE_RECT`, `LINE`, `POLYLINE`, `SET_BRIGHTNESS` |
| Direct image transfer | `BLIT_TILE` |
| Segmented full-resolution tile transfer | `TILE_BEGIN`, `TILE_CHUNK`, `TILE_END` |
| Resource cache | `RESOURCE_BEGIN`, `RESOURCE_CHUNK`, `RESOURCE_END`, `DRAW_RESOURCE`, `RESOURCE_RELEASE`, `RESOURCE_CLEAR`, `RESOURCE_INFO` |
| Device text | `FONT_INFO`, `MEASURE_TEXT`, `DRAW_TEXT` |
| Framebuffer movement | `COPY_RECT`, `SCROLL_RECT` |
| RTC | `RTC_READ`, `RTC_SET` |

Replies include `HELLO_REPLY`, `PONG`, `ACK`, `ERROR`, framebuffer CRC, resource information, font information, text metrics, and RTC data. `TOUCH` is an asynchronous event that can arrive while the host waits for another reply.

`PING` echoes at most 64 payload bytes. `LINE` and each `POLYLINE` segment are clipped to the canvas before rasterization. Line thickness zero is normalized to one, thickness is limited to 32 pixels, and one line or complete polyline is limited to 1,000,000 clipped pixel-write attempts. Commands above those limits fail with `BAD_ARGUMENT` rather than monopolizing the device loop.

## Canvas and image transport

The canvas is 450×600 RGB565 pixels. Coordinates use a top-left origin. Rectangles use half-open bounds:

```text
[x, x + width) × [y, y + height)
```

Standard-resolution tile formats are:

| Pixel format | Encodings | Use |
|---|---|---|
| RGB565 | RAW or RLE | Exact color output |
| Alpha8 | RAW or RLE | Tinted masks, including host-rendered text |
| Palette4 | Packed 4-bit indices plus local RGB565 palette | Lossy image transfer with up to 16 colors |
| Palette64 | Packed 6-bit indices plus local RGB565 palette | Lossy image transfer with up to 64 colors |

The standard tile profiles are 18×24, 30×40, and 45×60 pixels. Direct tiles fit in one protocol packet. Larger standard-resolution transfers can use the segmented tile sequence. Resource-cache entries use the same standard-resolution formats and are defined outside a frame before being drawn inside one.

Palette data is intentionally lossy. The host chooses colors and assigns palette indices. CRC comparison with the original RGB source is valid only for a lossless path such as RGB565 RAW or RLE.

## Scale2 transport

Scale2 accepts lower-resolution source pixels and writes each one as a 2×2 nearest-neighbor block in the normal framebuffer.

| Source format | Destination | Restrictions |
|---|---|---|
| RGB565 Scale2 | 2× width and 2× height RGB565 output | Direct transfer only |
| Palette4 Scale2 | 2× expanded Palette4 result | Direct transfer only |
| Palette64 Scale2 | 2× expanded Palette64 result | Direct transfer only |

Each Scale2 source tile is limited to 15×20 source pixels. Its expanded destination must remain inside the 450×600 canvas. Scale2 tiles cannot use segmented transfer or the resource cache.

A full-screen Scale2 source is 225×300. It overwrites the destination pixels directly. Host applications must redraw full-resolution overlays after updating an overlapping Scale2 background.

## Device text, touch, and RTC

The firmware includes a flash-resident GNU Unifont grid font. `FONT_INFO` exposes font metadata, `MEASURE_TEXT` reports Pico-rendered text metrics, and `DRAW_TEXT` draws UTF-8 text inside a frame. The protocol feature named device text is Pico-rendered text: it is useful when the host needs predictable cell geometry without transferring a host-rendered Alpha8 mask.

Touch events include coordinates, press state, and contact count. The firmware coalesces move activity to prioritize current positions.

The PCF85063 RTC is optional at startup. The firmware advertises RTC support only after the device responds. RTC values use UTC fields and support years 2000 through 2099.

## Capability negotiation

`HELLO_REPLY` contains the protocol version, canvas dimensions, standard tile profiles, maximum payload, and a 32-bit capability bitmap. A host should confirm the capabilities it requires before using optional features, including resource caching, device text, framebuffer movement, RTC access, or any Scale2 mode.

The precise capability constants are in `remote_protocol.h` and `protocol.py`. Update their definitions, the firmware dispatch path, the Python API, tests, and this document together when changing the wire protocol.
