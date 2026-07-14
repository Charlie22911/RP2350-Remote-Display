#ifndef RP2350_REMOTE_RENDERER_H
#define RP2350_REMOTE_RENDERER_H

#include <stdbool.h>
#include <stdint.h>

#include "remote_protocol.h"

bool renderer_init(void);
void renderer_clear(uint16_t rgb565);
void renderer_show_waiting_screen(void);
void renderer_fill_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t rgb565);
void renderer_stroke_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t rgb565, uint8_t thickness);
bool renderer_line(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1, uint16_t rgb565, uint8_t thickness);
bool renderer_copy_rect(uint16_t source_x, uint16_t source_y, uint16_t width, uint16_t height,
                        uint16_t destination_x, uint16_t destination_y);
bool renderer_scroll_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                          int16_t delta_x, int16_t delta_y, uint16_t fill_rgb565);
bool renderer_polyline(const uint8_t *payload, uint16_t length);

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
} renderer_font_info_t;

typedef struct {
    uint16_t width;
    uint16_t height;
    uint16_t glyph_count;
    uint16_t missing_glyph_count;
} renderer_text_metrics_t;

bool renderer_font_info(uint8_t font_id, renderer_font_info_t *info);
bool renderer_measure_text(uint8_t font_id, uint8_t scale, const uint8_t *utf8, uint16_t length,
                           renderer_text_metrics_t *metrics);
bool renderer_draw_text(uint8_t font_id, uint8_t scale, uint16_t x, uint16_t y, uint16_t rgb565,
                        const uint8_t *utf8, uint16_t length);
bool renderer_blit_tile(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t color,
                        uint8_t pixel_format, uint8_t codec, const uint8_t *data, uint16_t length);
typedef enum {
    RENDERER_PRESENT_IDLE = 0,
    RENDERER_PRESENT_ACTIVE = 1,
    RENDERER_PRESENT_COMPLETE = 2,
    RENDERER_PRESENT_ERROR = 3,
} renderer_present_status_t;

bool renderer_present_begin(void);
renderer_present_status_t renderer_present_task(void);
bool renderer_present_active(void);
void renderer_cancel_present(void);
bool renderer_flush_dirty(void);
uint32_t renderer_canvas_crc32(void);
void renderer_set_brightness(uint8_t percent);

#endif
