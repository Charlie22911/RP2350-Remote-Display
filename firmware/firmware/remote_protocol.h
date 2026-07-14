#ifndef RP2350_REMOTE_PROTOCOL_H
#define RP2350_REMOTE_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RPD_PROTOCOL_VERSION 16u
#define RPD_PACKET_MAGIC 0x31445052u
#define RPD_MAX_PAYLOAD 4096u
#define RPD_SCREEN_WIDTH 450u
#define RPD_SCREEN_HEIGHT 600u

/* Bound primitive work so a valid packet cannot starve the main loop/watchdog. */
#define RPD_LINE_MAX_THICKNESS 32u
#define RPD_LINE_MAX_WORK 1000000u

#define RPD_TILE_SMALL_WIDTH 18u
#define RPD_TILE_SMALL_HEIGHT 24u
#define RPD_TILE_MEDIUM_WIDTH 30u
#define RPD_TILE_MEDIUM_HEIGHT 40u
#define RPD_TILE_LARGE_WIDTH 45u
#define RPD_TILE_LARGE_HEIGHT 60u
#define RPD_TILE_MAX_WIDTH RPD_TILE_LARGE_WIDTH
#define RPD_TILE_MAX_HEIGHT RPD_TILE_LARGE_HEIGHT
#define RPD_MAX_ENCODED_TILE_BYTES (RPD_TILE_LARGE_WIDTH * RPD_TILE_LARGE_HEIGHT * 3u)

/* Packet CRC is opt-in. The normal USB bulk path relies on USB link-layer CRC/retry. */
#define RPD_PACKET_FLAG_CRC32 0x01u
/* RESOURCE_BEGIN or TILE_BEGIN only: append a uint32_t encoded-data CRC after the base payload. */
#define RPD_PACKET_FLAG_CONTENT_CRC32 0x02u
/* Compatibility name retained for the v6 host transport API. */
#define RPD_PACKET_FLAG_TILE_CONTENT_CRC32 RPD_PACKET_FLAG_CONTENT_CRC32
#define RPD_PACKET_FLAG_KNOWN (RPD_PACKET_FLAG_CRC32 | RPD_PACKET_FLAG_CONTENT_CRC32)

typedef enum {
    RPD_MSG_HELLO = 0x01,
    RPD_MSG_PING = 0x02,
    RPD_MSG_FRAME_BEGIN = 0x03,
    RPD_MSG_FRAME_END = 0x04,
    RPD_MSG_FILL_RECT = 0x05,
    RPD_MSG_STROKE_RECT = 0x06,
    RPD_MSG_LINE = 0x07,
    RPD_MSG_POLYLINE = 0x08,
    RPD_MSG_BLIT_TILE = 0x09,
    RPD_MSG_CLEAR = 0x0A,
    RPD_MSG_SET_BRIGHTNESS = 0x0B,
    RPD_MSG_FRAME_ABORT = 0x0C,
    RPD_MSG_SESSION_CLOSE = 0x0D,
    RPD_MSG_TILE_BEGIN = 0x0E,
    RPD_MSG_TILE_CHUNK = 0x0F,
    RPD_MSG_TILE_END = 0x10,
    RPD_MSG_CANVAS_CRC = 0x11,
    RPD_MSG_RESOURCE_BEGIN = 0x12,
    RPD_MSG_RESOURCE_CHUNK = 0x13,
    RPD_MSG_RESOURCE_END = 0x14,
    RPD_MSG_DRAW_RESOURCE = 0x15,
    RPD_MSG_RESOURCE_RELEASE = 0x16,
    RPD_MSG_RESOURCE_CLEAR = 0x17,
    RPD_MSG_RESOURCE_INFO = 0x18,
    RPD_MSG_FONT_INFO = 0x19,
    RPD_MSG_MEASURE_TEXT = 0x1A,
    RPD_MSG_DRAW_TEXT = 0x1B,
    RPD_MSG_COPY_RECT = 0x1C,
    RPD_MSG_SCROLL_RECT = 0x1D,
    RPD_MSG_RTC_READ = 0x1E,
    RPD_MSG_RTC_SET = 0x1F,

    RPD_MSG_HELLO_REPLY = 0x81,
    RPD_MSG_PONG = 0x82,
    RPD_MSG_ACK = 0x83,
    RPD_MSG_ERROR = 0x84,
    RPD_MSG_CANVAS_CRC_REPLY = 0x85,
    RPD_MSG_RESOURCE_INFO_REPLY = 0x86,
    RPD_MSG_FONT_INFO_REPLY = 0x87,
    RPD_MSG_MEASURE_TEXT_REPLY = 0x88,
    RPD_MSG_RTC_READ_REPLY = 0x89,
    RPD_MSG_TOUCH = 0x90,
} rpd_message_type_t;

typedef enum {
    RPD_STATUS_OK = 0,
    RPD_STATUS_BAD_PACKET = 1,
    RPD_STATUS_BAD_COMMAND = 2,
    RPD_STATUS_BAD_ARGUMENT = 3,
    RPD_STATUS_DECODE_ERROR = 4,
    RPD_STATUS_OUT_OF_MEMORY = 5,
    RPD_STATUS_NOT_READY = 6,
    RPD_STATUS_FRAME_STATE = 7,
    RPD_STATUS_BAD_CRC = 8,
    RPD_STATUS_TIMEOUT = 9,
    RPD_STATUS_DISPLAY_ERROR = 10,
    RPD_STATUS_TILE_STATE = 11,
    RPD_STATUS_RESOURCE_STATE = 12,
    RPD_STATUS_RESOURCE_NOT_FOUND = 13,
    RPD_STATUS_RTC_ERROR = 14,
} rpd_status_t;

typedef enum {
    RPD_PIXEL_RGB565 = 0,
    RPD_PIXEL_ALPHA8 = 1,
    RPD_PIXEL_INDEX4 = 2,
    /* Packed 6-bit indices into a local 1..64 entry RGB565 palette. */
    RPD_PIXEL_INDEX6 = 3,
    /* Packed or compressed RGB565 source pixels upscaled 2x on-device. */
    RPD_PIXEL_RGB565_SCALE2 = 4,
    RPD_PIXEL_INDEX4_SCALE2 = 5,
    RPD_PIXEL_INDEX6_SCALE2 = 6,
} rpd_pixel_format_t;

typedef enum {
    RPD_CODEC_RAW = 0,
    RPD_CODEC_RLE = 1,
    RPD_CODEC_PALETTE4 = 2,
    RPD_CODEC_PALETTE64 = 3,
} rpd_codec_t;

#pragma pack(push, 1)
typedef struct {
    uint32_t magic;
    uint8_t type;
    uint8_t flags;
    uint16_t payload_length;
    uint32_t sequence;
} rpd_packet_header_t;

typedef struct {
    uint16_t protocol_version;
} rpd_hello_request_t;

typedef struct {
    uint16_t protocol_version;
    uint16_t width;
    uint16_t height;
    uint16_t small_tile_width;
    uint16_t small_tile_height;
    uint16_t medium_tile_width;
    uint16_t medium_tile_height;
    uint16_t large_tile_width;
    uint16_t large_tile_height;
    uint16_t max_payload;
    uint32_t capabilities;
} rpd_hello_reply_t;

typedef struct {
    uint32_t frame_id;
} rpd_frame_payload_t;

typedef struct {
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
    uint16_t color;
} rpd_fill_rect_payload_t;

typedef struct {
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
    uint16_t color;
    uint8_t thickness;
    uint8_t reserved;
} rpd_stroke_rect_payload_t;

typedef struct {
    uint16_t x0;
    uint16_t y0;
    uint16_t x1;
    uint16_t y1;
    uint16_t color;
    uint8_t thickness;
    uint8_t reserved;
} rpd_line_payload_t;

typedef struct {
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
    uint16_t color;
    uint8_t pixel_format;
    uint8_t codec;
} rpd_blit_tile_payload_t;

/* The optional encoded-data CRC follows this base payload when the packet flag is set. */
typedef struct {
    uint32_t tile_id;
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
    uint16_t color;
    uint8_t pixel_format;
    uint8_t codec;
    uint16_t encoded_length;
} rpd_tile_begin_payload_t;

typedef struct {
    uint32_t tile_id;
    uint16_t offset;
} rpd_tile_chunk_payload_t;

typedef struct {
    uint32_t tile_id;
} rpd_tile_end_payload_t;

typedef struct {
    uint32_t resource_id;
    uint16_t width;
    uint16_t height;
    uint8_t pixel_format;
    uint8_t codec;
    uint16_t encoded_length;
} rpd_resource_begin_payload_t;

typedef struct {
    uint32_t resource_id;
    uint16_t offset;
} rpd_resource_chunk_payload_t;

typedef struct {
    uint32_t resource_id;
} rpd_resource_end_payload_t;

typedef struct {
    uint32_t resource_id;
    uint16_t x;
    uint16_t y;
    uint16_t color;
} rpd_draw_resource_payload_t;

typedef struct {
    uint32_t resource_id;
} rpd_resource_release_payload_t;

typedef struct {
    uint16_t slot_capacity;
    uint16_t slot_used;
    uint32_t byte_capacity;
    uint32_t byte_used;
} rpd_resource_info_reply_t;

typedef struct {
    uint8_t font_id;
    uint8_t cell_width;
    uint8_t cell_height;
    uint8_t ascent;
    uint8_t descent;
    uint8_t line_gap;
    uint16_t fallback_codepoint;
    uint32_t glyph_count;
    uint16_t coverage_version;
} rpd_font_info_reply_t;

typedef struct {
    uint8_t font_id;
    uint8_t scale;
} rpd_measure_text_prefix_t;

typedef struct {
    uint16_t width;
    uint16_t height;
    uint16_t glyph_count;
    uint16_t missing_glyph_count;
} rpd_measure_text_reply_t;

typedef struct {
    uint16_t x;
    uint16_t y;
    uint16_t color;
    uint8_t font_id;
    uint8_t scale;
} rpd_draw_text_prefix_t;

typedef struct {
    uint16_t source_x;
    uint16_t source_y;
    uint16_t width;
    uint16_t height;
    uint16_t destination_x;
    uint16_t destination_y;
} rpd_copy_rect_payload_t;

typedef struct {
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
    int16_t delta_x;
    int16_t delta_y;
    uint16_t fill_color;
} rpd_scroll_rect_payload_t;

typedef struct {
    uint16_t year;
    uint8_t month;
    uint8_t day;
    uint8_t hour;
    uint8_t minute;
    uint8_t second;
    /* Sunday=0 through Saturday=6, matching PCF85063 register semantics. */
    uint8_t weekday;
} rpd_rtc_set_payload_t;

typedef struct {
    uint16_t year;
    uint8_t month;
    uint8_t day;
    uint8_t hour;
    uint8_t minute;
    uint8_t second;
    /* Sunday=0 through Saturday=6, matching PCF85063 register semantics. */
    uint8_t weekday;
    uint8_t flags;
} rpd_rtc_read_reply_t;

enum {
    RPD_RTC_FLAG_OSCILLATOR_VALID = 1u << 0,
    RPD_RTC_FLAG_RUNNING = 1u << 1,
    RPD_RTC_FLAG_24_HOUR = 1u << 2,
};

typedef struct {
    uint16_t x;
    uint16_t y;
    uint8_t state;
    uint8_t contacts;
} rpd_touch_payload_t;
#pragma pack(pop)

enum {
    RPD_CAP_RGB565_TILES = 1u << 0,
    RPD_CAP_ALPHA8_TILES = 1u << 1,
    RPD_CAP_RLE = 1u << 2,
    RPD_CAP_TOUCH_EVENTS = 1u << 3,
    RPD_CAP_PRIMITIVES = 1u << 4,
    RPD_CAP_OPTIONAL_PACKET_CRC32 = 1u << 5,
    RPD_CAP_FRAME_TRANSACTIONS = 1u << 6,
    RPD_CAP_WAITING_SCREEN = 1u << 7,
    RPD_CAP_BRIGHTNESS = 1u << 8,
    RPD_CAP_SESSION_REATTACH = 1u << 9,
    RPD_CAP_TILE_PROFILES = 1u << 10,
    RPD_CAP_SEGMENTED_TILES = 1u << 11,
    RPD_CAP_CANVAS_CRC32 = 1u << 12,
    RPD_CAP_OPTIONAL_TILE_CRC32 = 1u << 13,
    RPD_CAP_DIRTY_TILE_PRESENT = 1u << 14,
    RPD_CAP_RESOURCE_CACHE = 1u << 15,
    RPD_CAP_PALETTE4_TILES = 1u << 16,
    RPD_CAP_ASYNC_PRESENT = 1u << 17,
    RPD_CAP_TOUCH_COALESCING = 1u << 18,
    RPD_CAP_DEVICE_TEXT = 1u << 19,
    RPD_CAP_COPY_RECT = 1u << 20,
    RPD_CAP_SCROLL_RECT = 1u << 21,
    RPD_CAP_PALETTE64_TILES = 1u << 22,
    RPD_CAP_RTC_PCF85063 = 1u << 23,
    RPD_CAP_RGB565_SCALE2 = 1u << 24,
    RPD_CAP_PALETTE4_SCALE2 = 1u << 25,
    RPD_CAP_PALETTE64_SCALE2 = 1u << 26,
};

void rpd_protocol_init(bool touch_available);
void rpd_protocol_task(void);
void rpd_protocol_display_task(void);
bool rpd_protocol_touch_sync_required(void);
void rpd_protocol_send_touch(uint16_t x, uint16_t y, bool pressed, uint8_t contacts);

#endif
