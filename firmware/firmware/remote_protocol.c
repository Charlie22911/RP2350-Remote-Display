#include "remote_protocol.h"

#include <string.h>

#include "pico/stdlib.h"
#include "renderer.h"
#include "resource_cache.h"
#include "rtc_pcf85063.h"
#include "tusb.h"

#define RPD_PARSER_TIMEOUT_MS 250u
#define RPD_STAGED_TRANSFER_TIMEOUT_MS 1000u
#define RPD_PRESENT_DELAY_MS 2u
#define RPD_TX_QUEUE_DEPTH 24u
#define RPD_TX_MAX_PAYLOAD 64u
#define RPD_TOUCH_EDGE_QUEUE_DEPTH 8u
#define RPD_USB_READ_CHUNK_BYTES 64u
/* One 64-byte read can complete at most six minimum-size packets. Leave two
 * additional slots for a parser/staged timeout and an asynchronous present ACK. */
#define RPD_TX_READ_REPLY_RESERVE 8u

typedef enum {
    RPD_PARSE_HEADER = 0,
    RPD_PARSE_PACKET_CRC = 1,
    RPD_PARSE_PAYLOAD = 2,
} rpd_parser_state_t;

static uint8_t header_buffer[sizeof(rpd_packet_header_t)];
static uint16_t header_used;
static uint8_t packet_crc_buffer[sizeof(uint32_t)];
static uint8_t packet_crc_used;
static rpd_packet_header_t active_header;
static uint32_t active_packet_crc32;
static uint8_t payload_buffer[RPD_MAX_PAYLOAD];
static uint16_t payload_used;
static rpd_parser_state_t parser_state;
static uint32_t last_receive_ms;

static bool session_ready;
static bool session_packet_crc_enabled;
static bool touch_supported;
static bool frame_active;
static uint32_t active_frame_id;
static bool mounted_last_task;
static bool waiting_screen_visible;

static bool present_pending;
static bool present_ack_pending;
static uint32_t present_ack_sequence;
static uint8_t present_ack_command;
static uint8_t present_ack_flags;
static absolute_time_t present_not_before;

static struct {
    bool active;
    bool verify_content_crc;
    uint32_t expected_content_crc32;
    uint32_t last_activity_ms;
    uint32_t last_sequence;
    uint8_t last_command;
    rpd_tile_begin_payload_t metadata;
    uint16_t received_length;
} staged_tile;
static uint8_t staged_tile_data[RPD_MAX_ENCODED_TILE_BYTES];

static struct {
    bool active;
    bool verify_content_crc;
    uint32_t expected_content_crc32;
    uint32_t last_activity_ms;
    uint32_t last_sequence;
    uint8_t last_command;
    rpd_resource_begin_payload_t metadata;
    uint16_t received_length;
} staged_resource;
static uint8_t staged_resource_data[RPD_MAX_ENCODED_TILE_BYTES];

static struct {
    uint8_t type;
    uint8_t flags;
    uint32_t sequence;
    uint16_t payload_length;
    uint8_t payload[RPD_TX_MAX_PAYLOAD];
} tx_queue[RPD_TX_QUEUE_DEPTH];
static uint8_t tx_head;
static uint8_t tx_tail;
static uint8_t tx_count;

static rpd_touch_payload_t touch_edge_queue[RPD_TOUCH_EDGE_QUEUE_DEPTH];
static uint8_t touch_edge_head;
static uint8_t touch_edge_tail;
static uint8_t touch_edge_count;
static bool touch_move_pending;
static rpd_touch_payload_t touch_latest_move;
static bool touch_state_known;
static bool touch_last_pressed;

_Static_assert(sizeof(rpd_packet_header_t) == 12, "Unexpected packet header size");
_Static_assert(RPD_TX_READ_REPLY_RESERVE < RPD_TX_QUEUE_DEPTH, "TX reply reserve must leave queue capacity");
_Static_assert(sizeof(rpd_hello_reply_t) == 24, "Unexpected HELLO reply size");
_Static_assert(sizeof(rpd_tile_begin_payload_t) == 18, "Unexpected tile begin size");
_Static_assert(sizeof(rpd_tile_chunk_payload_t) == 6, "Unexpected tile chunk size");
_Static_assert(sizeof(rpd_tile_end_payload_t) == 4, "Unexpected tile end size");
_Static_assert(sizeof(rpd_resource_begin_payload_t) == 12, "Unexpected resource begin size");
_Static_assert(sizeof(rpd_resource_chunk_payload_t) == 6, "Unexpected resource chunk size");
_Static_assert(sizeof(rpd_resource_end_payload_t) == 4, "Unexpected resource end size");
_Static_assert(sizeof(rpd_draw_resource_payload_t) == 10, "Unexpected resource draw size");
_Static_assert(sizeof(rpd_resource_info_reply_t) == 12, "Unexpected resource info size");
_Static_assert(sizeof(rpd_font_info_reply_t) == 14, "Unexpected font info size");
_Static_assert(sizeof(rpd_measure_text_prefix_t) == 2, "Unexpected measure-text prefix size");
_Static_assert(sizeof(rpd_measure_text_reply_t) == 8, "Unexpected measure-text reply size");
_Static_assert(sizeof(rpd_draw_text_prefix_t) == 8, "Unexpected draw-text prefix size");
_Static_assert(sizeof(rpd_copy_rect_payload_t) == 12, "Unexpected copy-rect payload size");
_Static_assert(sizeof(rpd_scroll_rect_payload_t) == 14, "Unexpected scroll-rect payload size");
_Static_assert(sizeof(rpd_rtc_set_payload_t) == 8, "Unexpected RTC set payload size");
_Static_assert(sizeof(rpd_rtc_read_reply_t) == 9, "Unexpected RTC read reply size");

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, uint32_t length)
{
    for (uint32_t index = 0u; index < length; ++index) {
        crc ^= data[index];
        for (uint8_t bit = 0u; bit < 8u; ++bit) {
            const uint32_t mask = 0u - (crc & 1u);
            crc = (crc >> 1u) ^ (0xEDB88320u & mask);
        }
    }
    return crc;
}

static uint32_t data_crc32(const uint8_t *data, uint32_t length)
{
    uint32_t crc = 0xFFFFFFFFu;
    if (data != NULL && length != 0u) {
        crc = crc32_update(crc, data, length);
    }
    return ~crc;
}

static uint32_t packet_crc32(uint8_t type, uint8_t flags, uint16_t payload_length,
                             uint32_t sequence, const uint8_t *payload)
{
    const uint8_t metadata[8] = {
        type,
        flags,
        (uint8_t)(payload_length & 0xFFu),
        (uint8_t)(payload_length >> 8u),
        (uint8_t)(sequence & 0xFFu),
        (uint8_t)((sequence >> 8u) & 0xFFu),
        (uint8_t)((sequence >> 16u) & 0xFFu),
        (uint8_t)((sequence >> 24u) & 0xFFu),
    };

    uint32_t crc = 0xFFFFFFFFu;
    crc = crc32_update(crc, metadata, sizeof(metadata));
    if (payload_length != 0u && payload != NULL) {
        crc = crc32_update(crc, payload, payload_length);
    }
    return ~crc;
}

static void reset_parser(void)
{
    header_used = 0u;
    packet_crc_used = 0u;
    payload_used = 0u;
    parser_state = RPD_PARSE_HEADER;
    active_packet_crc32 = 0u;
    memset(&active_header, 0, sizeof(active_header));
}

static void reset_staged_tile(void)
{
    memset(&staged_tile, 0, sizeof(staged_tile));
}

static void reset_staged_resource(void)
{
    memset(&staged_resource, 0, sizeof(staged_resource));
}

static void clear_tx_queue(void)
{
    tx_head = 0u;
    tx_tail = 0u;
    tx_count = 0u;
}

static void clear_touch_queue(void)
{
    touch_edge_head = 0u;
    touch_edge_tail = 0u;
    touch_edge_count = 0u;
    touch_move_pending = false;
    memset(&touch_latest_move, 0, sizeof(touch_latest_move));
    touch_state_known = false;
    touch_last_pressed = false;
}

static bool touch_edge_push(const rpd_touch_payload_t *event)
{
    if (event == NULL || touch_edge_count >= RPD_TOUCH_EDGE_QUEUE_DEPTH) {
        return false;
    }
    touch_edge_queue[touch_edge_head] = *event;
    touch_edge_head = (uint8_t)((touch_edge_head + 1u) % RPD_TOUCH_EDGE_QUEUE_DEPTH);
    ++touch_edge_count;
    return true;
}

static void reset_session_state(void)
{
    // A new session may arrive while a prior host's present is still in flight.
    // Cancel it before clearing protocol state so the panel transport cannot strand CS low.
    renderer_cancel_present();
    session_ready = false;
    session_packet_crc_enabled = false;
    frame_active = false;
    active_frame_id = 0u;
    present_pending = false;
    present_ack_pending = false;
    present_ack_sequence = 0u;
    present_ack_command = 0u;
    present_ack_flags = 0u;
    reset_staged_tile();
    reset_staged_resource();
    clear_touch_queue();
    rpd_resource_cache_reset();
}

static void reset_transport_state(void)
{
    reset_parser();
    reset_session_state();
    waiting_screen_visible = true;
    clear_tx_queue();
}

static void begin_hello_session(bool enable_packet_crc)
{
    reset_session_state();
    clear_tx_queue();
    session_ready = true;
    session_packet_crc_enabled = enable_packet_crc;
}

static bool tx_queue_push(uint8_t type, uint8_t flags, uint32_t sequence,
                          const void *payload, uint16_t payload_length)
{
    if (payload_length > RPD_TX_MAX_PAYLOAD || tx_count >= RPD_TX_QUEUE_DEPTH) {
        return false;
    }

    tx_queue[tx_head].type = type;
    tx_queue[tx_head].flags = flags;
    tx_queue[tx_head].sequence = sequence;
    tx_queue[tx_head].payload_length = payload_length;
    if (payload_length != 0u && payload != NULL) {
        memcpy(tx_queue[tx_head].payload, payload, payload_length);
    }

    tx_head = (uint8_t)((tx_head + 1u) % RPD_TX_QUEUE_DEPTH);
    ++tx_count;
    return true;
}

static bool tx_write_now(uint8_t type, uint8_t flags, uint32_t sequence,
                         const void *payload, uint16_t payload_length)
{
    if (!tud_mounted() || payload_length > RPD_TX_MAX_PAYLOAD) {
        return false;
    }

    const bool include_crc = (flags & RPD_PACKET_FLAG_CRC32) != 0u;
    const uint32_t packet_length = sizeof(rpd_packet_header_t) + (include_crc ? sizeof(uint32_t) : 0u) + payload_length;
    if (tud_vendor_write_available() < packet_length) {
        return false;
    }

    const rpd_packet_header_t header = {
        .magic = RPD_PACKET_MAGIC,
        .type = type,
        .flags = flags,
        .payload_length = payload_length,
        .sequence = sequence,
    };

    if (tud_vendor_write(&header, sizeof(header)) != sizeof(header)) {
        return false;
    }

    if (include_crc) {
        const uint32_t checksum = packet_crc32(type, flags, payload_length, sequence, payload);
        if (tud_vendor_write(&checksum, sizeof(checksum)) != sizeof(checksum)) {
            return false;
        }
    }

    if (payload_length != 0u && payload != NULL && tud_vendor_write(payload, payload_length) != payload_length) {
        return false;
    }

    tud_vendor_write_flush();
    return true;
}

static uint8_t session_reply_flags(void);

static void tx_drain(void)
{
    while (tx_count != 0u) {
        const uint8_t slot = tx_tail;
        if (!tx_write_now(tx_queue[slot].type, tx_queue[slot].flags, tx_queue[slot].sequence,
                          tx_queue[slot].payload, tx_queue[slot].payload_length)) {
            return;
        }

        tx_tail = (uint8_t)((tx_tail + 1u) % RPD_TX_QUEUE_DEPTH);
        --tx_count;
    }
}

static void touch_tx_drain(void)
{
    if (!session_ready || !tud_mounted() || tx_count != 0u) {
        return;
    }

    const uint8_t flags = session_reply_flags();
    if (touch_edge_count != 0u) {
        const rpd_touch_payload_t *event = &touch_edge_queue[touch_edge_tail];
        if (!tx_write_now(RPD_MSG_TOUCH, flags, 0u, event, sizeof(*event))) {
            return;
        }
        touch_edge_tail = (uint8_t)((touch_edge_tail + 1u) % RPD_TOUCH_EDGE_QUEUE_DEPTH);
        --touch_edge_count;
        return;
    }

    if (touch_move_pending && tx_write_now(RPD_MSG_TOUCH, flags, 0u,
                                           &touch_latest_move, sizeof(touch_latest_move))) {
        touch_move_pending = false;
    }
}

static uint8_t session_reply_flags(void)
{
    return session_packet_crc_enabled ? RPD_PACKET_FLAG_CRC32 : 0u;
}

static void send_small_packet_with_flags(uint8_t type, uint8_t flags, uint32_t sequence,
                                         const void *payload, uint16_t payload_length)
{
    tx_drain();
    if (!tx_write_now(type, flags, sequence, payload, payload_length)) {
        (void)tx_queue_push(type, flags, sequence, payload, payload_length);
    }
}

static void send_small_packet(uint8_t type, uint32_t sequence, const void *payload, uint16_t payload_length)
{
    send_small_packet_with_flags(type, session_reply_flags(), sequence, payload, payload_length);
}

static void send_ack_with_flags(uint32_t sequence, uint8_t flags)
{
    const uint8_t status = RPD_STATUS_OK;
    send_small_packet_with_flags(RPD_MSG_ACK, flags, sequence, &status, sizeof(status));
}

static void send_ack(uint32_t sequence)
{
    send_ack_with_flags(sequence, session_reply_flags());
}

static void send_error_with_flags(uint32_t sequence, uint8_t command, rpd_status_t status,
                                  uint8_t flags)
{
    const uint8_t payload[2] = {(uint8_t)status, command};
    send_small_packet_with_flags(RPD_MSG_ERROR, flags, sequence, payload, sizeof(payload));
}

static void send_error(uint32_t sequence, uint8_t command, rpd_status_t status)
{
    send_error_with_flags(sequence, command, status, session_reply_flags());
}

static bool read_u16(const uint8_t *bytes, uint16_t length, uint16_t offset, uint16_t *value)
{
    if (bytes == NULL || value == NULL || (uint32_t)offset + 2u > length) {
        return false;
    }

    *value = (uint16_t)bytes[offset] | ((uint16_t)bytes[offset + 1u] << 8u);
    return true;
}

static bool read_u32(const uint8_t *bytes, uint16_t length, uint16_t offset, uint32_t *value)
{
    if (bytes == NULL || value == NULL || (uint32_t)offset + 4u > length) {
        return false;
    }

    *value = (uint32_t)bytes[offset] |
             ((uint32_t)bytes[offset + 1u] << 8u) |
             ((uint32_t)bytes[offset + 2u] << 16u) |
             ((uint32_t)bytes[offset + 3u] << 24u);
    return true;
}

static bool read_frame_id(const uint8_t *payload, uint16_t payload_length, uint32_t *frame_id)
{
    if (payload == NULL || frame_id == NULL || payload_length != sizeof(rpd_frame_payload_t)) {
        return false;
    }

    memcpy(frame_id, payload, sizeof(*frame_id));
    return true;
}

static void schedule_present_with_flags(uint32_t acknowledgement_sequence,
                                        uint8_t acknowledgement_command,
                                        bool acknowledge_after_present,
                                        uint8_t acknowledgement_flags)
{
    present_pending = true;
    present_ack_pending = acknowledge_after_present;
    present_ack_sequence = acknowledgement_sequence;
    present_ack_command = acknowledgement_command;
    present_ack_flags = acknowledge_after_present ? acknowledgement_flags : 0u;
    present_not_before = make_timeout_time_ms(RPD_PRESENT_DELAY_MS);
}

static void schedule_present(uint32_t acknowledgement_sequence, uint8_t acknowledgement_command,
                             bool acknowledge_after_present)
{
    schedule_present_with_flags(acknowledgement_sequence, acknowledgement_command,
                                acknowledge_after_present, session_reply_flags());
}

static void enter_waiting_state(void)
{
    /* Recovery may be triggered asynchronously. Stop panel DMA before changing
     * framebuffer contents and discard any acknowledgement for the old present. */
    renderer_cancel_present();
    present_pending = false;
    present_ack_pending = false;
    present_ack_sequence = 0u;
    present_ack_command = 0u;
    present_ack_flags = 0u;
    session_ready = false;
    session_packet_crc_enabled = false;
    frame_active = false;
    active_frame_id = 0u;
    reset_staged_tile();
    reset_staged_resource();
    waiting_screen_visible = true;
    renderer_show_waiting_screen();
    schedule_present(0u, 0u, false);
}

static bool require_session_and_frame(const rpd_packet_header_t *header)
{
    if (!session_ready || present_pending) {
        send_error(header->sequence, header->type, RPD_STATUS_NOT_READY);
        return false;
    }
    if (!frame_active) {
        send_error(header->sequence, header->type, RPD_STATUS_FRAME_STATE);
        return false;
    }
    if (staged_tile.active) {
        send_error(header->sequence, header->type, RPD_STATUS_TILE_STATE);
        return false;
    }
    return true;
}

static void abort_active_frame(uint32_t sequence, uint8_t command, rpd_status_t status)
{
    send_error(sequence, command, status);
    enter_waiting_state();
}

static bool tile_geometry_is_valid(uint16_t x, uint16_t y, uint16_t width, uint16_t height)
{
    return width > 0u && height > 0u && width <= RPD_TILE_MAX_WIDTH && height <= RPD_TILE_MAX_HEIGHT &&
           x < RPD_SCREEN_WIDTH && y < RPD_SCREEN_HEIGHT &&
           (uint32_t)x + width <= RPD_SCREEN_WIDTH && (uint32_t)y + height <= RPD_SCREEN_HEIGHT;
}

static bool tile_encoded_length_is_valid(uint16_t width, uint16_t height, uint8_t pixel_format,
                                         uint8_t codec, uint16_t encoded_length)
{
    if (encoded_length == 0u || encoded_length > RPD_MAX_ENCODED_TILE_BYTES) {
        return false;
    }

    const uint32_t pixels = (uint32_t)width * height;
    uint32_t maximum = 0u;
    uint32_t exact_raw = 0u;

    if (pixel_format == RPD_PIXEL_RGB565) {
        if (codec == RPD_CODEC_RAW) {
            exact_raw = pixels * 2u;
        } else if (codec == RPD_CODEC_RLE) {
            maximum = pixels * 3u;
        } else {
            return false;
        }
    } else if (pixel_format == RPD_PIXEL_INDEX4) {
        if (codec != RPD_CODEC_PALETTE4) {
            return false;
        }
        const uint32_t index_bytes = (pixels + 1u) / 2u;
        return encoded_length >= 1u + 2u + index_bytes &&
               encoded_length <= 1u + 32u + index_bytes;
    } else if (pixel_format == RPD_PIXEL_INDEX6) {
        if (codec != RPD_CODEC_PALETTE64) {
            return false;
        }
        const uint32_t index_bytes = (pixels * 6u + 7u) / 8u;
        return encoded_length >= 1u + 2u + index_bytes &&
               encoded_length <= 1u + 128u + index_bytes;
    } else if (pixel_format == RPD_PIXEL_ALPHA8) {
        if (codec == RPD_CODEC_RAW) {
            exact_raw = pixels;
        } else if (codec == RPD_CODEC_RLE) {
            maximum = pixels * 2u;
        } else {
            return false;
        }
    } else {
        return false;
    }

    if (exact_raw != 0u) {
        return encoded_length == exact_raw;
    }
    return encoded_length <= maximum;
}

static void handle_packet(const rpd_packet_header_t *header, const uint8_t *payload)
{
    if (header == NULL) {
        return;
    }

    if ((header->flags & RPD_PACKET_FLAG_CONTENT_CRC32) != 0u &&
        header->type != RPD_MSG_TILE_BEGIN && header->type != RPD_MSG_RESOURCE_BEGIN) {
        send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
        return;
    }

    switch ((rpd_message_type_t)header->type) {
    case RPD_MSG_HELLO: {
        rpd_hello_request_t request;
        if ((header->flags & RPD_PACKET_FLAG_TILE_CONTENT_CRC32) != 0u ||
            header->payload_length != sizeof(request) || payload == NULL) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }

        memcpy(&request, payload, sizeof(request));
        if (request.protocol_version != RPD_PROTOCOL_VERSION) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }

        begin_hello_session((header->flags & RPD_PACKET_FLAG_CRC32) != 0u);
        const rpd_hello_reply_t reply = {
            .protocol_version = RPD_PROTOCOL_VERSION,
            .width = RPD_SCREEN_WIDTH,
            .height = RPD_SCREEN_HEIGHT,
            .small_tile_width = RPD_TILE_SMALL_WIDTH,
            .small_tile_height = RPD_TILE_SMALL_HEIGHT,
            .medium_tile_width = RPD_TILE_MEDIUM_WIDTH,
            .medium_tile_height = RPD_TILE_MEDIUM_HEIGHT,
            .large_tile_width = RPD_TILE_LARGE_WIDTH,
            .large_tile_height = RPD_TILE_LARGE_HEIGHT,
            .max_payload = RPD_MAX_PAYLOAD,
            .capabilities = RPD_CAP_RGB565_TILES | RPD_CAP_ALPHA8_TILES | RPD_CAP_RLE |
                            RPD_CAP_PRIMITIVES | RPD_CAP_OPTIONAL_PACKET_CRC32 |
                            RPD_CAP_FRAME_TRANSACTIONS | RPD_CAP_WAITING_SCREEN | RPD_CAP_BRIGHTNESS |
                            RPD_CAP_SESSION_REATTACH | RPD_CAP_TILE_PROFILES | RPD_CAP_SEGMENTED_TILES |
                            RPD_CAP_CANVAS_CRC32 | RPD_CAP_OPTIONAL_TILE_CRC32 |
                            RPD_CAP_DIRTY_TILE_PRESENT | RPD_CAP_RESOURCE_CACHE |
                            RPD_CAP_PALETTE4_TILES | RPD_CAP_ASYNC_PRESENT |
                            RPD_CAP_DEVICE_TEXT |
                            RPD_CAP_COPY_RECT | RPD_CAP_SCROLL_RECT |
                            RPD_CAP_PALETTE64_TILES |
                            RPD_CAP_RGB565_SCALE2 |
                            RPD_CAP_PALETTE4_SCALE2 |
                            RPD_CAP_PALETTE64_SCALE2 |
                            (touch_supported ? (RPD_CAP_TOUCH_EVENTS | RPD_CAP_TOUCH_COALESCING) : 0u) |
                            (rpd_rtc_is_available() ? RPD_CAP_RTC_PCF85063 : 0u),
        };
        send_small_packet(RPD_MSG_HELLO_REPLY, header->sequence, &reply, sizeof(reply));
        return;
    }

    case RPD_MSG_PING:
        if (header->payload_length > RPD_TX_MAX_PAYLOAD) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        send_small_packet(RPD_MSG_PONG, header->sequence, payload, header->payload_length);
        return;

    case RPD_MSG_FRAME_BEGIN: {
        uint32_t frame_id;
        if (!session_ready || present_pending || staged_resource.active) {
            send_error(header->sequence, header->type,
                       staged_resource.active ? RPD_STATUS_RESOURCE_STATE : RPD_STATUS_NOT_READY);
            return;
        }
        if (!read_frame_id(payload, header->payload_length, &frame_id) || frame_active) {
            send_error(header->sequence, header->type, RPD_STATUS_FRAME_STATE);
            return;
        }

        frame_active = true;
        active_frame_id = frame_id;
        reset_staged_tile();
        if (waiting_screen_visible) {
            renderer_clear(0x0000u);
            waiting_screen_visible = false;
        }
        send_ack(header->sequence);
        return;
    }

    case RPD_MSG_FRAME_END: {
        uint32_t frame_id;
        if (!session_ready || !frame_active || staged_tile.active ||
            !read_frame_id(payload, header->payload_length, &frame_id) || frame_id != active_frame_id) {
            abort_active_frame(header->sequence, header->type,
                               staged_tile.active ? RPD_STATUS_TILE_STATE : RPD_STATUS_FRAME_STATE);
            return;
        }

        frame_active = false;
        active_frame_id = 0u;
        schedule_present(header->sequence, RPD_MSG_FRAME_END, true);
        return;
    }

    case RPD_MSG_FRAME_ABORT: {
        uint32_t frame_id;
        if (!session_ready || !frame_active || !read_frame_id(payload, header->payload_length, &frame_id) ||
            frame_id != active_frame_id) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_FRAME_STATE);
            return;
        }

        const uint8_t acknowledgement_flags = session_reply_flags();
        enter_waiting_state();
        schedule_present_with_flags(header->sequence, RPD_MSG_FRAME_ABORT, true,
                                    acknowledgement_flags);
        return;
    }

    case RPD_MSG_SESSION_CLOSE:
        if (header->payload_length != 0u) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        send_ack(header->sequence);
        reset_session_state();
        return;

    case RPD_MSG_SET_BRIGHTNESS:
        if (!session_ready || present_pending) {
            send_error(header->sequence, header->type, RPD_STATUS_NOT_READY);
            return;
        }
        if (header->payload_length != 1u || payload == NULL || payload[0] > 100u) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        renderer_set_brightness(payload[0]);
        send_ack(header->sequence);
        return;

    case RPD_MSG_CANVAS_CRC: {
        if (!session_ready || frame_active || present_pending || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_NOT_READY);
            return;
        }
        if (header->payload_length != 0u) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }

        const uint32_t crc = renderer_canvas_crc32();
        send_small_packet(RPD_MSG_CANVAS_CRC_REPLY, header->sequence, &crc, sizeof(crc));
        return;
    }

    case RPD_MSG_RTC_READ: {
        if (!session_ready || frame_active || present_pending || staged_resource.active || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_NOT_READY);
            return;
        }
        if (header->payload_length != 0u) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        rpd_rtc_datetime_t value;
        if (!rpd_rtc_is_available() || !rpd_rtc_read(&value)) {
            send_error(header->sequence, header->type, RPD_STATUS_RTC_ERROR);
            return;
        }
        uint8_t flags = 0u;
        if (value.oscillator_valid) {
            flags |= RPD_RTC_FLAG_OSCILLATOR_VALID;
        }
        if (value.running) {
            flags |= RPD_RTC_FLAG_RUNNING;
        }
        if (value.twenty_four_hour) {
            flags |= RPD_RTC_FLAG_24_HOUR;
        }
        const rpd_rtc_read_reply_t reply = {
            .year = value.year,
            .month = value.month,
            .day = value.day,
            .hour = value.hour,
            .minute = value.minute,
            .second = value.second,
            .weekday = value.weekday,
            .flags = flags,
        };
        send_small_packet(RPD_MSG_RTC_READ_REPLY, header->sequence, &reply, sizeof(reply));
        return;
    }

    case RPD_MSG_RTC_SET: {
        rpd_rtc_set_payload_t command;
        if (!session_ready || frame_active || present_pending || staged_resource.active || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_NOT_READY);
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        const rpd_rtc_datetime_t value = {
            .year = command.year,
            .month = command.month,
            .day = command.day,
            .hour = command.hour,
            .minute = command.minute,
            .second = command.second,
            .weekday = command.weekday,
            .oscillator_valid = true,
            .running = true,
            .twenty_four_hour = true,
        };
        if (!rpd_rtc_is_available() || !rpd_rtc_set(&value)) {
            send_error(header->sequence, header->type, RPD_STATUS_RTC_ERROR);
            return;
        }
        send_ack(header->sequence);
        return;
    }

    case RPD_MSG_CLEAR: {
        uint16_t color;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length != 2u || !read_u16(payload, header->payload_length, 0u, &color)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        renderer_clear(color);
        return;
    }

    case RPD_MSG_FILL_RECT: {
        rpd_fill_rect_payload_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        renderer_fill_rect(command.x, command.y, command.width, command.height, command.color);
        return;
    }

    case RPD_MSG_STROKE_RECT: {
        rpd_stroke_rect_payload_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        renderer_stroke_rect(command.x, command.y, command.width, command.height, command.color, command.thickness);
        return;
    }

    case RPD_MSG_LINE: {
        rpd_line_payload_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (!renderer_line(command.x0, command.y0, command.x1, command.y1,
                           command.color, command.thickness)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
        }
        return;
    }

    case RPD_MSG_POLYLINE:
        if (!require_session_and_frame(header)) {
            return;
        }
        if (!renderer_polyline(payload, header->payload_length)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
        }
        return;

    case RPD_MSG_COPY_RECT: {
        rpd_copy_rect_payload_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (!renderer_copy_rect(command.source_x, command.source_y, command.width, command.height,
                                command.destination_x, command.destination_y)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
        }
        return;
    }

    case RPD_MSG_SCROLL_RECT: {
        rpd_scroll_rect_payload_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (!renderer_scroll_rect(command.x, command.y, command.width, command.height,
                                  command.delta_x, command.delta_y, command.fill_color)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
        }
        return;
    }

    case RPD_MSG_DRAW_TEXT: {
        rpd_draw_text_prefix_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length < sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        const uint8_t *utf8 = payload + sizeof(command);
        const uint16_t utf8_length = (uint16_t)(header->payload_length - sizeof(command));
        if (!renderer_draw_text(command.font_id, command.scale, command.x, command.y, command.color,
                                utf8, utf8_length)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
        }
        return;
    }

    case RPD_MSG_BLIT_TILE: {
        rpd_blit_tile_payload_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length < sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (!renderer_blit_tile(command.x, command.y, command.width, command.height, command.color,
                                command.pixel_format, command.codec,
                                payload + sizeof(command),
                                (uint16_t)(header->payload_length - sizeof(command)))) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_DECODE_ERROR);
        }
        return;
    }

    case RPD_MSG_TILE_BEGIN: {
        rpd_tile_begin_payload_t command;
        const bool verify_content_crc = (header->flags & RPD_PACKET_FLAG_CONTENT_CRC32) != 0u;
        const uint16_t required_length = (uint16_t)(sizeof(command) + (verify_content_crc ? sizeof(uint32_t) : 0u));
        uint32_t content_crc = 0u;

        if (!session_ready || present_pending || !frame_active || staged_tile.active) {
            send_error(header->sequence, header->type, staged_tile.active ? RPD_STATUS_TILE_STATE : RPD_STATUS_NOT_READY);
            return;
        }
        if (header->payload_length != required_length || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (verify_content_crc && !read_u32(payload, header->payload_length, sizeof(command), &content_crc)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        if (command.tile_id == 0u || !tile_geometry_is_valid(command.x, command.y, command.width, command.height) ||
            !tile_encoded_length_is_valid(command.width, command.height, command.pixel_format,
                                          command.codec, command.encoded_length)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        staged_tile.active = true;
        staged_tile.verify_content_crc = verify_content_crc;
        staged_tile.expected_content_crc32 = content_crc;
        staged_tile.last_activity_ms = to_ms_since_boot(get_absolute_time());
        staged_tile.last_sequence = header->sequence;
        staged_tile.last_command = header->type;
        staged_tile.metadata = command;
        staged_tile.received_length = 0u;
        return;
    }

    case RPD_MSG_TILE_CHUNK: {
        rpd_tile_chunk_payload_t chunk;
        if (!session_ready || !frame_active || !staged_tile.active || payload == NULL ||
            header->payload_length <= sizeof(chunk)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_TILE_STATE);
            return;
        }
        memcpy(&chunk, payload, sizeof(chunk));
        const uint16_t data_length = (uint16_t)(header->payload_length - sizeof(chunk));
        if (chunk.tile_id != staged_tile.metadata.tile_id || chunk.offset != staged_tile.received_length ||
            (uint32_t)staged_tile.received_length + data_length > staged_tile.metadata.encoded_length) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_TILE_STATE);
            return;
        }
        memcpy(staged_tile_data + staged_tile.received_length, payload + sizeof(chunk), data_length);
        staged_tile.received_length = (uint16_t)(staged_tile.received_length + data_length);
        staged_tile.last_activity_ms = to_ms_since_boot(get_absolute_time());
        staged_tile.last_sequence = header->sequence;
        staged_tile.last_command = header->type;
        return;
    }

    case RPD_MSG_TILE_END: {
        rpd_tile_end_payload_t end;
        if (!session_ready || !frame_active || !staged_tile.active || payload == NULL ||
            header->payload_length != sizeof(end)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_TILE_STATE);
            return;
        }
        memcpy(&end, payload, sizeof(end));
        if (end.tile_id != staged_tile.metadata.tile_id ||
            staged_tile.received_length != staged_tile.metadata.encoded_length) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_TILE_STATE);
            return;
        }
        if (staged_tile.verify_content_crc &&
            data_crc32(staged_tile_data, staged_tile.received_length) != staged_tile.expected_content_crc32) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_CRC);
            return;
        }

        const rpd_tile_begin_payload_t command = staged_tile.metadata;
        const uint16_t data_length = staged_tile.received_length;
        reset_staged_tile();
        if (!renderer_blit_tile(command.x, command.y, command.width, command.height, command.color,
                                command.pixel_format, command.codec, staged_tile_data, data_length)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_DECODE_ERROR);
        }
        return;
    }

    case RPD_MSG_RESOURCE_BEGIN: {
        rpd_resource_begin_payload_t command;
        const bool verify_content_crc = (header->flags & RPD_PACKET_FLAG_CONTENT_CRC32) != 0u;
        const uint16_t required_length = (uint16_t)(sizeof(command) + (verify_content_crc ? sizeof(uint32_t) : 0u));
        uint32_t content_crc = 0u;

        if (!session_ready || present_pending || frame_active || staged_tile.active || staged_resource.active) {
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        if (header->payload_length != required_length || payload == NULL) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (verify_content_crc && !read_u32(payload, header->payload_length, sizeof(command), &content_crc)) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        if (command.resource_id == 0u || rpd_resource_cache_contains(command.resource_id) ||
            !tile_geometry_is_valid(0u, 0u, command.width, command.height) ||
            !tile_encoded_length_is_valid(command.width, command.height, command.pixel_format,
                                          command.codec, command.encoded_length)) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        staged_resource.active = true;
        staged_resource.verify_content_crc = verify_content_crc;
        staged_resource.expected_content_crc32 = content_crc;
        staged_resource.last_activity_ms = to_ms_since_boot(get_absolute_time());
        staged_resource.last_sequence = header->sequence;
        staged_resource.last_command = header->type;
        staged_resource.metadata = command;
        staged_resource.received_length = 0u;
        return;
    }

    case RPD_MSG_RESOURCE_CHUNK: {
        rpd_resource_chunk_payload_t chunk;
        if (!session_ready || frame_active || !staged_resource.active || payload == NULL ||
            header->payload_length <= sizeof(chunk)) {
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        memcpy(&chunk, payload, sizeof(chunk));
        const uint16_t data_length = (uint16_t)(header->payload_length - sizeof(chunk));
        if (chunk.resource_id != staged_resource.metadata.resource_id || chunk.offset != staged_resource.received_length ||
            (uint32_t)staged_resource.received_length + data_length > staged_resource.metadata.encoded_length) {
            reset_staged_resource();
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        memcpy(staged_resource_data + staged_resource.received_length, payload + sizeof(chunk), data_length);
        staged_resource.received_length = (uint16_t)(staged_resource.received_length + data_length);
        staged_resource.last_activity_ms = to_ms_since_boot(get_absolute_time());
        staged_resource.last_sequence = header->sequence;
        staged_resource.last_command = header->type;
        return;
    }

    case RPD_MSG_RESOURCE_END: {
        rpd_resource_end_payload_t end;
        if (!session_ready || frame_active || !staged_resource.active || payload == NULL ||
            header->payload_length != sizeof(end)) {
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        memcpy(&end, payload, sizeof(end));
        if (end.resource_id != staged_resource.metadata.resource_id ||
            staged_resource.received_length != staged_resource.metadata.encoded_length) {
            reset_staged_resource();
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        if (staged_resource.verify_content_crc &&
            data_crc32(staged_resource_data, staged_resource.received_length) != staged_resource.expected_content_crc32) {
            reset_staged_resource();
            send_error(header->sequence, header->type, RPD_STATUS_BAD_CRC);
            return;
        }

        const rpd_resource_begin_payload_t command = staged_resource.metadata;
        const uint16_t data_length = staged_resource.received_length;
        reset_staged_resource();
        if (!rpd_resource_cache_encoded_data_valid(command.width, command.height,
                                                   command.pixel_format, command.codec,
                                                   staged_resource_data, data_length)) {
            send_error(header->sequence, header->type, RPD_STATUS_DECODE_ERROR);
            return;
        }
        if (!rpd_resource_cache_define(command.resource_id, command.width, command.height,
                                       command.pixel_format, command.codec,
                                       staged_resource_data, data_length)) {
            send_error(header->sequence, header->type, RPD_STATUS_OUT_OF_MEMORY);
            return;
        }
        send_ack(header->sequence);
        return;
    }

    case RPD_MSG_DRAW_RESOURCE: {
        rpd_draw_resource_payload_t command;
        if (!require_session_and_frame(header)) {
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (!rpd_resource_cache_contains(command.resource_id)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_RESOURCE_NOT_FOUND);
            return;
        }
        if (!rpd_resource_cache_draw(command.resource_id, command.x, command.y, command.color)) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_DECODE_ERROR);
        }
        return;
    }

    case RPD_MSG_RESOURCE_RELEASE: {
        rpd_resource_release_payload_t command;
        if (!session_ready || frame_active || present_pending || staged_resource.active || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        if (header->payload_length != sizeof(command) || payload == NULL) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        if (!rpd_resource_cache_release(command.resource_id)) {
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_NOT_FOUND);
            return;
        }
        send_ack(header->sequence);
        return;
    }

    case RPD_MSG_RESOURCE_CLEAR:
        if (!session_ready || frame_active || present_pending || staged_resource.active || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        if (header->payload_length != 0u) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        rpd_resource_cache_reset();
        send_ack(header->sequence);
        return;

    case RPD_MSG_RESOURCE_INFO: {
        if (!session_ready || frame_active || present_pending || staged_resource.active || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_RESOURCE_STATE);
            return;
        }
        if (header->payload_length != 0u) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        const rpd_resource_cache_info_t cache_info = rpd_resource_cache_info();
        const rpd_resource_info_reply_t reply = {
            .slot_capacity = cache_info.slot_capacity,
            .slot_used = cache_info.slot_used,
            .byte_capacity = cache_info.byte_capacity,
            .byte_used = cache_info.byte_used,
        };
        send_small_packet(RPD_MSG_RESOURCE_INFO_REPLY, header->sequence, &reply, sizeof(reply));
        return;
    }

    case RPD_MSG_FONT_INFO: {
        renderer_font_info_t font_info;
        if (!session_ready || frame_active || present_pending || staged_resource.active || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_NOT_READY);
            return;
        }
        if (header->payload_length != 1u || payload == NULL || !renderer_font_info(payload[0], &font_info)) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        const rpd_font_info_reply_t reply = {
            .font_id = font_info.font_id,
            .cell_width = font_info.cell_width,
            .cell_height = font_info.cell_height,
            .ascent = font_info.ascent,
            .descent = font_info.descent,
            .line_gap = font_info.line_gap,
            .fallback_codepoint = font_info.fallback_codepoint,
            .glyph_count = font_info.glyph_count,
            .coverage_version = font_info.coverage_version,
        };
        send_small_packet(RPD_MSG_FONT_INFO_REPLY, header->sequence, &reply, sizeof(reply));
        return;
    }

    case RPD_MSG_MEASURE_TEXT: {
        rpd_measure_text_prefix_t command;
        renderer_text_metrics_t text_metrics;
        if (!session_ready || frame_active || present_pending || staged_resource.active || staged_tile.active) {
            send_error(header->sequence, header->type, RPD_STATUS_NOT_READY);
            return;
        }
        if (header->payload_length < sizeof(command) || payload == NULL) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        memcpy(&command, payload, sizeof(command));
        const uint8_t *utf8 = payload + sizeof(command);
        const uint16_t utf8_length = (uint16_t)(header->payload_length - sizeof(command));
        if (!renderer_measure_text(command.font_id, command.scale, utf8, utf8_length, &text_metrics)) {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_ARGUMENT);
            return;
        }
        const rpd_measure_text_reply_t reply = {
            .width = text_metrics.width,
            .height = text_metrics.height,
            .glyph_count = text_metrics.glyph_count,
            .missing_glyph_count = text_metrics.missing_glyph_count,
        };
        send_small_packet(RPD_MSG_MEASURE_TEXT_REPLY, header->sequence, &reply, sizeof(reply));
        return;
    }

    default:
        if (frame_active) {
            abort_active_frame(header->sequence, header->type, RPD_STATUS_BAD_COMMAND);
        } else {
            send_error(header->sequence, header->type, RPD_STATUS_BAD_COMMAND);
        }
        return;
    }
}

static bool header_is_sane(const rpd_packet_header_t *header)
{
    return header->magic == RPD_PACKET_MAGIC && header->payload_length <= RPD_MAX_PAYLOAD &&
           (header->flags & ~RPD_PACKET_FLAG_KNOWN) == 0u;
}

static void complete_active_packet(void)
{
    const uint8_t *payload = active_header.payload_length == 0u ? NULL : payload_buffer;
    const bool validate_crc = (active_header.flags & RPD_PACKET_FLAG_CRC32) != 0u;

    if (validate_crc && active_packet_crc32 != packet_crc32(active_header.type, active_header.flags,
                                                              active_header.payload_length,
                                                              active_header.sequence, payload)) {
        send_error(active_header.sequence, active_header.type, RPD_STATUS_BAD_CRC);
        if (frame_active) {
            enter_waiting_state();
        }
    } else {
        handle_packet(&active_header, payload);
    }

    reset_parser();
}

static void parser_consume_byte(uint8_t byte)
{
    if (parser_state == RPD_PARSE_HEADER) {
        header_buffer[header_used++] = byte;
        if (header_used < sizeof(rpd_packet_header_t)) {
            return;
        }

        memcpy(&active_header, header_buffer, sizeof(active_header));
        if (!header_is_sane(&active_header)) {
            memmove(header_buffer, header_buffer + 1u, sizeof(header_buffer) - 1u);
            header_used = sizeof(header_buffer) - 1u;
            return;
        }

        if ((active_header.flags & RPD_PACKET_FLAG_CRC32) != 0u) {
            parser_state = RPD_PARSE_PACKET_CRC;
            packet_crc_used = 0u;
            return;
        }
        if (active_header.payload_length == 0u) {
            complete_active_packet();
            return;
        }

        parser_state = RPD_PARSE_PAYLOAD;
        payload_used = 0u;
        return;
    }

    if (parser_state == RPD_PARSE_PACKET_CRC) {
        packet_crc_buffer[packet_crc_used++] = byte;
        if (packet_crc_used < sizeof(uint32_t)) {
            return;
        }

        memcpy(&active_packet_crc32, packet_crc_buffer, sizeof(active_packet_crc32));
        if (active_header.payload_length == 0u) {
            complete_active_packet();
            return;
        }

        parser_state = RPD_PARSE_PAYLOAD;
        payload_used = 0u;
        return;
    }

    payload_buffer[payload_used++] = byte;
    if (payload_used < active_header.payload_length) {
        return;
    }

    complete_active_packet();
}

static void parser_timeout_task(void)
{
    if (parser_state == RPD_PARSE_HEADER && header_used == 0u) {
        return;
    }

    const uint32_t now = to_ms_since_boot(get_absolute_time());
    if ((uint32_t)(now - last_receive_ms) < RPD_PARSER_TIMEOUT_MS) {
        return;
    }

    if (parser_state != RPD_PARSE_HEADER && header_is_sane(&active_header)) {
        send_error(active_header.sequence, active_header.type, RPD_STATUS_TIMEOUT);
    }
    if (frame_active) {
        enter_waiting_state();
    } else if (staged_resource.active) {
        reset_session_state();
    }
    reset_parser();
}

static void staged_transfer_timeout_task(void)
{
    const uint32_t now = to_ms_since_boot(get_absolute_time());
    if (staged_tile.active &&
        (uint32_t)(now - staged_tile.last_activity_ms) >= RPD_STAGED_TRANSFER_TIMEOUT_MS) {
        const uint32_t sequence = staged_tile.last_sequence;
        const uint8_t command = staged_tile.last_command;
        send_error(sequence, command, RPD_STATUS_TIMEOUT);
        enter_waiting_state();
        return;
    }
    if (staged_resource.active &&
        (uint32_t)(now - staged_resource.last_activity_ms) >= RPD_STAGED_TRANSFER_TIMEOUT_MS) {
        const uint32_t sequence = staged_resource.last_sequence;
        const uint8_t command = staged_resource.last_command;
        send_error(sequence, command, RPD_STATUS_TIMEOUT);
        reset_session_state();
    }
}

void rpd_protocol_init(bool touch_available)
{
    touch_supported = touch_available;
    rpd_rtc_init();
    rpd_resource_cache_init();
    reset_transport_state();
    last_receive_ms = to_ms_since_boot(get_absolute_time());
    mounted_last_task = false;
}

void rpd_protocol_task(void)
{
    const bool mounted = tud_mounted();
    if (!mounted) {
        if (mounted_last_task) {
            reset_parser();
            reset_session_state();
            clear_tx_queue();
        }
        mounted_last_task = false;
        return;
    }
    mounted_last_task = true;

    /* Drain first and stop consuming OUT packets before required replies can
     * fill the bounded queue. TinyUSB then supplies natural endpoint backpressure. */
    tx_drain();
    uint8_t buffer[RPD_USB_READ_CHUNK_BYTES];
    while (tud_vendor_available() != 0u &&
           tx_count <= RPD_TX_QUEUE_DEPTH - RPD_TX_READ_REPLY_RESERVE) {
        const uint32_t count = tud_vendor_read(buffer, sizeof(buffer));
        if (count == 0u) {
            break;
        }
        last_receive_ms = to_ms_since_boot(get_absolute_time());
        for (uint32_t index = 0u; index < count; ++index) {
            parser_consume_byte(buffer[index]);
        }
        tx_drain();
    }

    parser_timeout_task();
    staged_transfer_timeout_task();
    tx_drain();
    touch_tx_drain();
}

void rpd_protocol_display_task(void)
{
    if (!present_pending || !time_reached(present_not_before)) {
        return;
    }

    if (!renderer_present_active()) {
        if (!renderer_present_begin()) {
            const bool acknowledge = present_ack_pending;
            const uint32_t acknowledgement_sequence = present_ack_sequence;
            const uint8_t acknowledgement_command = present_ack_command;
            const uint8_t acknowledgement_flags = present_ack_flags;
            reset_session_state();
            waiting_screen_visible = true;
            renderer_show_waiting_screen();
            if (acknowledge) {
                send_error_with_flags(acknowledgement_sequence, acknowledgement_command,
                                      RPD_STATUS_DISPLAY_ERROR, acknowledgement_flags);
            }
            /* Retry only the recovery screen after quiescing the transport. */
            present_pending = true;
            present_not_before = make_timeout_time_ms(RPD_PRESENT_DELAY_MS);
            return;
        }
    }

    const renderer_present_status_t status = renderer_present_task();
    if (status == RENDERER_PRESENT_ACTIVE) {
        return;
    }

    const bool acknowledge = present_ack_pending;
    const uint32_t acknowledgement_sequence = present_ack_sequence;
    const uint8_t acknowledgement_command = present_ack_command;
    const uint8_t acknowledgement_flags = present_ack_flags;
    present_pending = false;
    present_ack_pending = false;
    present_ack_sequence = 0u;
    present_ack_command = 0u;
    present_ack_flags = 0u;

    if (status == RENDERER_PRESENT_COMPLETE) {
        if (acknowledge) {
            send_ack_with_flags(acknowledgement_sequence, acknowledgement_flags);
        }
        return;
    }

    reset_session_state();
    waiting_screen_visible = true;
    renderer_show_waiting_screen();
    if (acknowledge) {
        send_error_with_flags(acknowledgement_sequence, acknowledgement_command,
                              RPD_STATUS_DISPLAY_ERROR, acknowledgement_flags);
    }
    // Render the recovery screen asynchronously after reporting the error.
    present_pending = true;
    present_not_before = make_timeout_time_ms(RPD_PRESENT_DELAY_MS);
}

bool rpd_protocol_touch_sync_required(void)
{
    return touch_supported && session_ready && !touch_state_known;
}

void rpd_protocol_send_touch(uint16_t x, uint16_t y, bool pressed, uint8_t contacts)
{
    if (!touch_supported || !session_ready || !tud_mounted()) {
        return;
    }

    const rpd_touch_payload_t event = {
        .x = x,
        .y = y,
        .state = pressed ? 1u : 0u,
        .contacts = contacts,
    };

    const bool edge = !touch_state_known || pressed != touch_last_pressed;
    touch_state_known = true;
    touch_last_pressed = pressed;

    if (edge) {
        // Preserve press/release transitions. A movement sample already superseded by
        // this edge is not useful to the host and can be discarded.
        touch_move_pending = false;
        if (!touch_edge_push(&event)) {
            // Keep the newest edge when the host is temporarily back-pressured.
            touch_edge_tail = (uint8_t)((touch_edge_tail + 1u) % RPD_TOUCH_EDGE_QUEUE_DEPTH);
            --touch_edge_count;
            (void)touch_edge_push(&event);
        }
        return;
    }

    // Move samples are intentionally coalesced. The newest finger position is more
    // useful than replaying a stale path after a display present.
    touch_latest_move = event;
    touch_move_pending = true;
}

