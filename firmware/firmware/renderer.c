#include "renderer.h"

#include <stddef.h>
#include <string.h>

#include "AMOLED_2in41.h"
#include "builtin_font.h"
#include "rp_pico_alloc.h"

#define RENDERER_DIRTY_WORDS ((RPD_SCREEN_HEIGHT + 31u) / 32u)

static uint16_t *framebuffer;
static uint32_t dirty_rows[RENDERER_DIRTY_WORDS];
static bool present_active;
static uint16_t present_scan_y;
static uint16_t active_band_y0;
static uint16_t active_band_y1;

static inline uint16_t panel_word(uint16_t rgb565)
{
    return (uint16_t)((rgb565 << 8) | (rgb565 >> 8));
}

static inline uint16_t host_word(uint16_t panel_rgb565)
{
    return panel_word(panel_rgb565);
}

static inline uint32_t framebuffer_index(uint16_t x, uint16_t y)
{
    return (uint32_t)y * RPD_SCREEN_WIDTH + x;
}

static bool row_is_dirty(uint16_t y)
{
    return (dirty_rows[y >> 5u] & (1u << (y & 31u))) != 0u;
}

static void set_row_dirty(uint16_t y)
{
    dirty_rows[y >> 5u] |= 1u << (y & 31u);
}

static void clear_row_dirty(uint16_t y)
{
    dirty_rows[y >> 5u] &= ~(1u << (y & 31u));
}

static void mark_dirty(uint16_t y0, uint16_t y1)
{
    if (y0 >= RPD_SCREEN_HEIGHT) {
        return;
    }
    if (y1 >= RPD_SCREEN_HEIGHT) {
        y1 = RPD_SCREEN_HEIGHT - 1u;
    }
    for (uint16_t y = y0; y <= y1; ++y) {
        set_row_dirty(y);
    }
}

static bool find_dirty_band(uint16_t start_y, uint16_t *band_y0, uint16_t *band_y1)
{
    uint16_t y = start_y;
    while (y < RPD_SCREEN_HEIGHT && !row_is_dirty(y)) {
        ++y;
    }
    if (y >= RPD_SCREEN_HEIGHT) {
        return false;
    }

    *band_y0 = y;
    while (y + 1u < RPD_SCREEN_HEIGHT && row_is_dirty((uint16_t)(y + 1u))) {
        ++y;
    }
    *band_y1 = y;
    return true;
}

static void clear_dirty_band(uint16_t y0, uint16_t y1)
{
    for (uint16_t y = y0; y <= y1; ++y) {
        clear_row_dirty(y);
    }
}

static bool clip_rect(int32_t *x, int32_t *y, int32_t *width, int32_t *height)
{
    if (*width <= 0 || *height <= 0) {
        return false;
    }

    int32_t x2 = *x + *width;
    int32_t y2 = *y + *height;

    if (x2 <= 0 || y2 <= 0 || *x >= (int32_t)RPD_SCREEN_WIDTH || *y >= (int32_t)RPD_SCREEN_HEIGHT) {
        return false;
    }

    if (*x < 0) {
        *x = 0;
    }
    if (*y < 0) {
        *y = 0;
    }
    if (x2 > (int32_t)RPD_SCREEN_WIDTH) {
        x2 = (int32_t)RPD_SCREEN_WIDTH;
    }
    if (y2 > (int32_t)RPD_SCREEN_HEIGHT) {
        y2 = (int32_t)RPD_SCREEN_HEIGHT;
    }

    *width = x2 - *x;
    *height = y2 - *y;
    return *width > 0 && *height > 0;
}

static inline void write_pixel(int32_t x, int32_t y, uint16_t panel_rgb565)
{
    if ((uint32_t)x < RPD_SCREEN_WIDTH && (uint32_t)y < RPD_SCREEN_HEIGHT) {
        framebuffer[(uint32_t)y * RPD_SCREEN_WIDTH + (uint32_t)x] = panel_rgb565;
    }
}

static uint16_t blend_rgb565(uint16_t base, uint16_t foreground, uint8_t alpha)
{
    if (alpha == 0) {
        return base;
    }
    if (alpha == 255) {
        return foreground;
    }

    const uint16_t inverse = (uint16_t)(255u - alpha);
    const uint16_t br = (base >> 11) & 0x1fu;
    const uint16_t bg = (base >> 5) & 0x3fu;
    const uint16_t bb = base & 0x1fu;
    const uint16_t fr = (foreground >> 11) & 0x1fu;
    const uint16_t fg = (foreground >> 5) & 0x3fu;
    const uint16_t fb = foreground & 0x1fu;

    const uint16_t r = (uint16_t)((br * inverse + fr * alpha + 127u) / 255u);
    const uint16_t g = (uint16_t)((bg * inverse + fg * alpha + 127u) / 255u);
    const uint16_t b = (uint16_t)((bb * inverse + fb * alpha + 127u) / 255u);

    return (uint16_t)((r << 11) | (g << 5) | b);
}

static void alpha_pixel(uint16_t x, uint16_t y, uint16_t foreground, uint8_t alpha)
{
    if (alpha == 0) {
        return;
    }

    uint16_t *pixel = framebuffer + framebuffer_index(x, y);
    const uint16_t base = host_word(*pixel);
    *pixel = panel_word(blend_rgb565(base, foreground, alpha));
}

bool renderer_init(void)
{
    framebuffer = rp_mem_calloc((size_t)RPD_SCREEN_WIDTH * RPD_SCREEN_HEIGHT, sizeof(uint16_t));
    if (framebuffer == NULL) {
        return false;
    }

    memset(dirty_rows, 0, sizeof(dirty_rows));
    present_active = false;
    present_scan_y = 0u;
    active_band_y0 = 0u;
    active_band_y1 = 0u;
    renderer_clear(0x0000u);
    return true;
}

void renderer_clear(uint16_t rgb565)
{
    const uint16_t value = panel_word(rgb565);
    const uint32_t pixel_count = (uint32_t)RPD_SCREEN_WIDTH * RPD_SCREEN_HEIGHT;

    for (uint32_t i = 0; i < pixel_count; ++i) {
        framebuffer[i] = value;
    }

    mark_dirty(0, RPD_SCREEN_HEIGHT - 1u);
}

static void draw_waiting_text(void)
{
    static const uint8_t title[] = "WAITING FOR HOST";
    static const uint8_t detail[] = "USB REMOTE DISPLAY";
    renderer_text_metrics_t title_metrics;
    renderer_text_metrics_t detail_metrics;

    if (!renderer_measure_text(RPD_BUILTIN_FONT_UI_MONO_8X16, 2u, title,
                               (uint16_t)(sizeof(title) - 1u), &title_metrics) ||
        !renderer_measure_text(RPD_BUILTIN_FONT_UI_MONO_8X16, 1u, detail,
                               (uint16_t)(sizeof(detail) - 1u), &detail_metrics)) {
        return;
    }

    const uint16_t gap = 16u;
    const uint16_t combined_height = (uint16_t)(title_metrics.height + gap + detail_metrics.height);
    const uint16_t title_x = (uint16_t)((RPD_SCREEN_WIDTH - title_metrics.width) / 2u);
    const uint16_t title_y = (uint16_t)((RPD_SCREEN_HEIGHT - combined_height) / 2u);
    const uint16_t detail_x = (uint16_t)((RPD_SCREEN_WIDTH - detail_metrics.width) / 2u);
    const uint16_t detail_y = (uint16_t)(title_y + title_metrics.height + gap);

    (void)renderer_draw_text(RPD_BUILTIN_FONT_UI_MONO_8X16, 2u, title_x, title_y, 0xFFFFu,
                             title, (uint16_t)(sizeof(title) - 1u));
    (void)renderer_draw_text(RPD_BUILTIN_FONT_UI_MONO_8X16, 1u, detail_x, detail_y, 0x7BEFu,
                             detail, (uint16_t)(sizeof(detail) - 1u));
}

void renderer_show_waiting_screen(void)
{
    renderer_clear(0x0000u);
    draw_waiting_text();
}

static bool renderer_font_id_supported(uint8_t font_id)
{
    return font_id == RPD_BUILTIN_FONT_UI_MONO_8X16;
}

static uint32_t decode_utf8_codepoint(const uint8_t *utf8, uint16_t length, uint16_t *offset, bool *valid)
{
    if (utf8 == NULL || offset == NULL || valid == NULL || *offset >= length) {
        if (valid != NULL) {
            *valid = false;
        }
        return RPD_BUILTIN_FONT_FALLBACK_CODEPOINT;
    }

    const uint8_t first = utf8[(*offset)++];
    if (first < 0x80u) {
        *valid = true;
        return first;
    }

    uint8_t continuation_count;
    uint32_t codepoint;
    uint32_t minimum;
    if ((first & 0xE0u) == 0xC0u) {
        continuation_count = 1u;
        codepoint = first & 0x1Fu;
        minimum = 0x80u;
    } else if ((first & 0xF0u) == 0xE0u) {
        continuation_count = 2u;
        codepoint = first & 0x0Fu;
        minimum = 0x800u;
    } else if ((first & 0xF8u) == 0xF0u) {
        continuation_count = 3u;
        codepoint = first & 0x07u;
        minimum = 0x10000u;
    } else {
        *valid = false;
        return RPD_BUILTIN_FONT_FALLBACK_CODEPOINT;
    }

    if ((uint16_t)(length - *offset) < continuation_count) {
        *valid = false;
        return RPD_BUILTIN_FONT_FALLBACK_CODEPOINT;
    }

    for (uint8_t index = 0u; index < continuation_count; ++index) {
        const uint8_t next = utf8[*offset + index];
        if ((next & 0xC0u) != 0x80u) {
            *valid = false;
            return RPD_BUILTIN_FONT_FALLBACK_CODEPOINT;
        }
        codepoint = (codepoint << 6u) | (next & 0x3Fu);
    }
    *offset = (uint16_t)(*offset + continuation_count);

    if (codepoint < minimum || codepoint > 0x10FFFFu ||
        (codepoint >= 0xD800u && codepoint <= 0xDFFFu)) {
        *valid = false;
        return RPD_BUILTIN_FONT_FALLBACK_CODEPOINT;
    }

    *valid = true;
    return codepoint;
}

static bool text_glyph_for_codepoint(uint32_t codepoint, rpd_builtin_font_glyph_t *glyph, bool *missing)
{
    if (glyph == NULL || missing == NULL) {
        return false;
    }

    if (rpd_builtin_font_lookup(codepoint, glyph)) {
        *missing = false;
        return true;
    }
    if (!rpd_builtin_font_lookup(RPD_BUILTIN_FONT_FALLBACK_CODEPOINT, glyph)) {
        return false;
    }
    *missing = true;
    return true;
}

bool renderer_font_info(uint8_t font_id, renderer_font_info_t *info)
{
    if (!renderer_font_id_supported(font_id) || info == NULL) {
        return false;
    }

    const uint32_t glyph_count = rpd_builtin_font_glyph_count();
    if (glyph_count == 0u) {
        return false;
    }

    *info = (renderer_font_info_t){
        .font_id = RPD_BUILTIN_FONT_UI_MONO_8X16,
        .cell_width = RPD_BUILTIN_FONT_CELL_WIDTH,
        .cell_height = RPD_BUILTIN_FONT_CELL_HEIGHT,
        .ascent = RPD_BUILTIN_FONT_ASCENT,
        .descent = RPD_BUILTIN_FONT_DESCENT,
        .line_gap = RPD_BUILTIN_FONT_LINE_GAP,
        .fallback_codepoint = RPD_BUILTIN_FONT_FALLBACK_CODEPOINT,
        .glyph_count = glyph_count,
        .coverage_version = RPD_BUILTIN_FONT_COVERAGE_VERSION,
    };
    return true;
}

bool renderer_measure_text(uint8_t font_id, uint8_t scale, const uint8_t *utf8, uint16_t length,
                           renderer_text_metrics_t *metrics)
{
    if (!renderer_font_id_supported(font_id) || metrics == NULL || scale == 0u || scale > 4u ||
        (length != 0u && utf8 == NULL)) {
        return false;
    }

    uint32_t current_width = 0u;
    uint32_t maximum_width = 0u;
    uint32_t line_count = 1u;
    uint32_t glyph_count = 0u;
    uint32_t missing_glyph_count = 0u;
    const uint32_t advance = RPD_BUILTIN_FONT_CELL_WIDTH * scale;
    uint16_t offset = 0u;

    while (offset < length) {
        bool utf8_valid;
        const uint32_t codepoint = decode_utf8_codepoint(utf8, length, &offset, &utf8_valid);
        if (codepoint == '\r') {
            continue;
        }
        if (codepoint == '\n') {
            if (current_width > maximum_width) {
                maximum_width = current_width;
            }
            current_width = 0u;
            ++line_count;
            continue;
        }
        if (codepoint == '\t') {
            current_width += advance * 4u;
            continue;
        }

        rpd_builtin_font_glyph_t glyph;
        bool missing;
        if (!text_glyph_for_codepoint(codepoint, &glyph, &missing)) {
            return false;
        }
        ++glyph_count;
        if (!utf8_valid || missing) {
            ++missing_glyph_count;
        }
        current_width += advance * glyph.cell_columns;
        if (current_width > UINT16_MAX || glyph_count > UINT16_MAX || missing_glyph_count > UINT16_MAX) {
            return false;
        }
    }

    if (current_width > maximum_width) {
        maximum_width = current_width;
    }
    const uint32_t height = line_count * RPD_BUILTIN_FONT_CELL_HEIGHT * scale;
    if (maximum_width > UINT16_MAX || height > UINT16_MAX) {
        return false;
    }

    *metrics = (renderer_text_metrics_t){
        .width = (uint16_t)maximum_width,
        .height = (uint16_t)height,
        .glyph_count = (uint16_t)glyph_count,
        .missing_glyph_count = (uint16_t)missing_glyph_count,
    };
    return true;
}

bool renderer_draw_text(uint8_t font_id, uint8_t scale, uint16_t x, uint16_t y, uint16_t rgb565,
                        const uint8_t *utf8, uint16_t length)
{
    renderer_text_metrics_t metrics;
    if (!renderer_measure_text(font_id, scale, utf8, length, &metrics)) {
        return false;
    }
    (void)metrics;

    const uint16_t panel_rgb565 = panel_word(rgb565);
    uint32_t cursor_x = x;
    uint32_t cursor_y = y;
    const uint32_t origin_x = x;
    const uint32_t advance = RPD_BUILTIN_FONT_CELL_WIDTH * scale;
    bool drew_pixels = false;
    uint32_t dirty_y0 = RPD_SCREEN_HEIGHT;
    uint32_t dirty_y1 = 0u;
    uint16_t offset = 0u;

    while (offset < length) {
        bool utf8_valid;
        const uint32_t codepoint = decode_utf8_codepoint(utf8, length, &offset, &utf8_valid);
        (void)utf8_valid;
        if (codepoint == '\r') {
            continue;
        }
        if (codepoint == '\n') {
            cursor_x = origin_x;
            cursor_y += RPD_BUILTIN_FONT_CELL_HEIGHT * scale;
            continue;
        }
        if (codepoint == '\t') {
            cursor_x += advance * 4u;
            continue;
        }

        rpd_builtin_font_glyph_t glyph;
        bool missing;
        if (!text_glyph_for_codepoint(codepoint, &glyph, &missing)) {
            return false;
        }
        (void)missing;

        for (uint8_t row = 0u; row < RPD_BUILTIN_FONT_CELL_HEIGHT; ++row) {
            for (uint8_t column = 0u; column < glyph.cell_columns * RPD_BUILTIN_FONT_CELL_WIDTH; ++column) {
                const uint8_t bits = glyph.rows[(uint32_t)row * glyph.bytes_per_row + column / 8u];
                if ((bits & (0x80u >> (column % 8u))) == 0u) {
                    continue;
                }
                const uint32_t pixel_x = cursor_x + (uint32_t)column * scale;
                const uint32_t pixel_y = cursor_y + (uint32_t)row * scale;
                for (uint8_t scale_y = 0u; scale_y < scale; ++scale_y) {
                    const uint32_t scaled_y = pixel_y + scale_y;
                    if (scaled_y >= RPD_SCREEN_HEIGHT) {
                        continue;
                    }
                    for (uint8_t scale_x = 0u; scale_x < scale; ++scale_x) {
                        const uint32_t scaled_x = pixel_x + scale_x;
                        if (scaled_x >= RPD_SCREEN_WIDTH) {
                            continue;
                        }
                        write_pixel((int32_t)scaled_x, (int32_t)scaled_y, panel_rgb565);
                        drew_pixels = true;
                        if (scaled_y < dirty_y0) {
                            dirty_y0 = scaled_y;
                        }
                        if (scaled_y > dirty_y1) {
                            dirty_y1 = scaled_y;
                        }
                    }
                }
            }
        }
        cursor_x += advance * glyph.cell_columns;
    }

    if (drew_pixels) {
        mark_dirty((uint16_t)dirty_y0, (uint16_t)dirty_y1);
    }
    return true;
}

void renderer_fill_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t rgb565)
{
    int32_t clipped_x = x;
    int32_t clipped_y = y;
    int32_t clipped_width = width;
    int32_t clipped_height = height;

    if (!clip_rect(&clipped_x, &clipped_y, &clipped_width, &clipped_height)) {
        return;
    }

    const uint16_t value = panel_word(rgb565);
    for (int32_t row = 0; row < clipped_height; ++row) {
        uint16_t *destination = framebuffer + (uint32_t)(clipped_y + row) * RPD_SCREEN_WIDTH + (uint32_t)clipped_x;
        for (int32_t column = 0; column < clipped_width; ++column) {
            destination[column] = value;
        }
    }

    mark_dirty((uint16_t)clipped_y, (uint16_t)(clipped_y + clipped_height - 1));
}

void renderer_stroke_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t rgb565, uint8_t thickness)
{
    if (width == 0 || height == 0) {
        return;
    }

    const uint16_t line = thickness == 0 ? 1u : thickness;
    const uint16_t horizontal = line > height ? height : line;
    const uint16_t vertical = line > width ? width : line;

    renderer_fill_rect(x, y, width, horizontal, rgb565);
    if (height > horizontal) {
        renderer_fill_rect(x, (uint16_t)(y + height - horizontal), width, horizontal, rgb565);
    }

    const uint16_t interior_height = height > horizontal * 2u ? (uint16_t)(height - horizontal * 2u) : 0u;
    if (interior_height != 0u) {
        renderer_fill_rect(x, (uint16_t)(y + horizontal), vertical, interior_height, rgb565);
        if (width > vertical) {
            renderer_fill_rect((uint16_t)(x + width - vertical), (uint16_t)(y + horizontal), vertical,
                               interior_height, rgb565);
        }
    }
}

void renderer_line(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1, uint16_t rgb565, uint8_t thickness)
{
    int32_t start_x = x0;
    int32_t start_y = y0;
    const int32_t end_x = x1;
    const int32_t end_y = y1;
    const int32_t dx = start_x < end_x ? end_x - start_x : start_x - end_x;
    const int32_t sx = start_x < end_x ? 1 : -1;
    const int32_t dy = start_y < end_y ? start_y - end_y : end_y - start_y;
    const int32_t sy = start_y < end_y ? 1 : -1;
    int32_t error = dx + dy;
    const int32_t radius = (thickness == 0 ? 1 : thickness) / 2;
    const uint16_t value = panel_word(rgb565);

    while (true) {
        for (int32_t oy = -radius; oy <= radius; ++oy) {
            for (int32_t ox = -radius; ox <= radius; ++ox) {
                write_pixel(start_x + ox, start_y + oy, value);
            }
        }

        if (start_x == end_x && start_y == end_y) {
            break;
        }

        const int32_t twice_error = error * 2;
        if (twice_error >= dy) {
            error += dy;
            start_x += sx;
        }
        if (twice_error <= dx) {
            error += dx;
            start_y += sy;
        }
    }

    int32_t min_y = (int32_t)(y0 < y1 ? y0 : y1) - radius;
    int32_t max_y = (int32_t)(y0 > y1 ? y0 : y1) + radius;
    if (min_y < 0) {
        min_y = 0;
    }
    if (max_y >= (int32_t)RPD_SCREEN_HEIGHT) {
        max_y = (int32_t)RPD_SCREEN_HEIGHT - 1;
    }
    mark_dirty((uint16_t)min_y, (uint16_t)max_y);
}

static bool check_canvas_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height)
{
    return width > 0u && height > 0u && x < RPD_SCREEN_WIDTH && y < RPD_SCREEN_HEIGHT &&
           (uint32_t)x + width <= RPD_SCREEN_WIDTH && (uint32_t)y + height <= RPD_SCREEN_HEIGHT;
}

bool renderer_copy_rect(uint16_t source_x, uint16_t source_y, uint16_t width, uint16_t height,
                        uint16_t destination_x, uint16_t destination_y)
{
    if (!check_canvas_rect(source_x, source_y, width, height) ||
        !check_canvas_rect(destination_x, destination_y, width, height)) {
        return false;
    }

    const size_t row_bytes = (size_t)width * sizeof(uint16_t);
    if (destination_y > source_y) {
        for (uint16_t row = height; row > 0u; --row) {
            const uint16_t offset = (uint16_t)(row - 1u);
            uint16_t *destination = framebuffer + framebuffer_index(destination_x, (uint16_t)(destination_y + offset));
            const uint16_t *source = framebuffer + framebuffer_index(source_x, (uint16_t)(source_y + offset));
            memmove(destination, source, row_bytes);
        }
    } else {
        for (uint16_t row = 0u; row < height; ++row) {
            uint16_t *destination = framebuffer + framebuffer_index(destination_x, (uint16_t)(destination_y + row));
            const uint16_t *source = framebuffer + framebuffer_index(source_x, (uint16_t)(source_y + row));
            memmove(destination, source, row_bytes);
        }
    }

    mark_dirty(destination_y, (uint16_t)(destination_y + height - 1u));
    return true;
}

bool renderer_scroll_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                          int16_t delta_x, int16_t delta_y, uint16_t fill_rgb565)
{
    if (!check_canvas_rect(x, y, width, height)) {
        return false;
    }
    if (delta_x == 0 && delta_y == 0) {
        return true;
    }

    const int32_t magnitude_x = delta_x < 0 ? -(int32_t)delta_x : (int32_t)delta_x;
    const int32_t magnitude_y = delta_y < 0 ? -(int32_t)delta_y : (int32_t)delta_y;
    if (magnitude_x >= width || magnitude_y >= height) {
        renderer_fill_rect(x, y, width, height, fill_rgb565);
        return true;
    }

    const uint16_t copied_width = (uint16_t)(width - magnitude_x);
    const uint16_t copied_height = (uint16_t)(height - magnitude_y);
    const uint16_t source_x = (uint16_t)(x + (delta_x < 0 ? magnitude_x : 0));
    const uint16_t source_y = (uint16_t)(y + (delta_y < 0 ? magnitude_y : 0));
    const uint16_t destination_x = (uint16_t)(x + (delta_x > 0 ? magnitude_x : 0));
    const uint16_t destination_y = (uint16_t)(y + (delta_y > 0 ? magnitude_y : 0));

    if (!renderer_copy_rect(source_x, source_y, copied_width, copied_height, destination_x, destination_y)) {
        return false;
    }

    if (delta_x > 0) {
        renderer_fill_rect(x, y, (uint16_t)magnitude_x, height, fill_rgb565);
    } else if (delta_x < 0) {
        renderer_fill_rect((uint16_t)(x + width - magnitude_x), y, (uint16_t)magnitude_x, height, fill_rgb565);
    }
    if (delta_y > 0) {
        renderer_fill_rect(x, y, width, (uint16_t)magnitude_y, fill_rgb565);
    } else if (delta_y < 0) {
        renderer_fill_rect(x, (uint16_t)(y + height - magnitude_y), width, (uint16_t)magnitude_y, fill_rgb565);
    }

    mark_dirty(y, (uint16_t)(y + height - 1u));
    return true;
}

bool renderer_polyline(const uint8_t *payload, uint16_t length)
{
    if (length < 4) {
        return false;
    }

    const uint16_t color = (uint16_t)payload[0] | ((uint16_t)payload[1] << 8);
    const uint8_t thickness = payload[2];
    const uint8_t point_count = payload[3];
    const uint32_t required = 4u + (uint32_t)point_count * 4u;

    if (point_count < 2 || required != length) {
        return false;
    }

    uint16_t previous_x = (uint16_t)payload[4] | ((uint16_t)payload[5] << 8);
    uint16_t previous_y = (uint16_t)payload[6] | ((uint16_t)payload[7] << 8);

    for (uint8_t point = 1; point < point_count; ++point) {
        const uint32_t offset = 4u + (uint32_t)point * 4u;
        const uint16_t next_x = (uint16_t)payload[offset] | ((uint16_t)payload[offset + 1] << 8);
        const uint16_t next_y = (uint16_t)payload[offset + 2] | ((uint16_t)payload[offset + 3] << 8);
        renderer_line(previous_x, previous_y, next_x, next_y, color, thickness);
        previous_x = next_x;
        previous_y = next_y;
    }

    return true;
}

#define SCALE2_TILE_MAX_WIDTH 15u
#define SCALE2_TILE_MAX_HEIGHT 20u

static bool check_tile_bounds(uint16_t x, uint16_t y, uint16_t width, uint16_t height)
{
    return width > 0 && height > 0 && width <= RPD_TILE_MAX_WIDTH && height <= RPD_TILE_MAX_HEIGHT &&
           x < RPD_SCREEN_WIDTH && y < RPD_SCREEN_HEIGHT &&
           (uint32_t)x + width <= RPD_SCREEN_WIDTH && (uint32_t)y + height <= RPD_SCREEN_HEIGHT;
}

static bool check_scale2_tile_bounds(uint16_t x, uint16_t y, uint16_t width, uint16_t height)
{
    return width > 0 && height > 0 && width <= SCALE2_TILE_MAX_WIDTH && height <= SCALE2_TILE_MAX_HEIGHT &&
           x < RPD_SCREEN_WIDTH && y < RPD_SCREEN_HEIGHT &&
           (uint32_t)x + (uint32_t)width * 2u <= RPD_SCREEN_WIDTH &&
           (uint32_t)y + (uint32_t)height * 2u <= RPD_SCREEN_HEIGHT;
}

static inline void write_scale2_pixel(uint16_t x, uint16_t y, uint16_t rgb565);

static bool decode_rgb565_raw(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                               const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    if (length != pixels * 2u) {
        return false;
    }

    for (uint32_t pixel = 0; pixel < pixels; ++pixel) {
        const uint16_t value = (uint16_t)data[pixel * 2u] | ((uint16_t)data[pixel * 2u + 1u] << 8);
        const uint16_t px = (uint16_t)(pixel % width);
        const uint16_t py = (uint16_t)(pixel / width);
        framebuffer[framebuffer_index((uint16_t)(x + px), (uint16_t)(y + py))] = panel_word(value);
    }

    return true;
}

static bool decode_rgb565_rle(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                               const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    uint32_t written = 0;
    uint16_t offset = 0;

    while (offset + 3u <= length && written < pixels) {
        const uint8_t run = data[offset++];
        const uint16_t value = (uint16_t)data[offset] | ((uint16_t)data[offset + 1u] << 8);
        offset += 2;

        if (run == 0 || written + run > pixels) {
            return false;
        }

        for (uint8_t count = 0; count < run; ++count) {
            const uint32_t pixel = written++;
            const uint16_t px = (uint16_t)(pixel % width);
            const uint16_t py = (uint16_t)(pixel / width);
            framebuffer[framebuffer_index((uint16_t)(x + px), (uint16_t)(y + py))] = panel_word(value);
        }
    }

    return written == pixels && offset == length;
}

static bool decode_alpha_raw(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t color,
                             const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    if (length != pixels) {
        return false;
    }

    for (uint32_t pixel = 0; pixel < pixels; ++pixel) {
        const uint16_t px = (uint16_t)(pixel % width);
        const uint16_t py = (uint16_t)(pixel / width);
        alpha_pixel((uint16_t)(x + px), (uint16_t)(y + py), color, data[pixel]);
    }

    return true;
}

static bool decode_alpha_rle(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t color,
                             const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    uint32_t written = 0;
    uint16_t offset = 0;

    while (offset + 2u <= length && written < pixels) {
        const uint8_t run = data[offset++];
        const uint8_t alpha = data[offset++];

        if (run == 0 || written + run > pixels) {
            return false;
        }

        for (uint8_t count = 0; count < run; ++count) {
            const uint32_t pixel = written++;
            const uint16_t px = (uint16_t)(pixel % width);
            const uint16_t py = (uint16_t)(pixel / width);
            alpha_pixel((uint16_t)(x + px), (uint16_t)(y + py), color, alpha);
        }
    }

    return written == pixels && offset == length;
}

static bool decode_index4_palette(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                                  const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    if (length < 3u) {
        return false;
    }

    const uint8_t palette_count = data[0];
    if (palette_count == 0u || palette_count > 16u) {
        return false;
    }
    const uint16_t palette_bytes = (uint16_t)palette_count * 2u;
    const uint16_t index_offset = (uint16_t)(1u + palette_bytes);
    const uint16_t index_bytes = (uint16_t)((pixels + 1u) / 2u);
    if ((uint32_t)index_offset + index_bytes != length) {
        return false;
    }

    uint16_t palette[16];
    for (uint8_t index = 0u; index < palette_count; ++index) {
        const uint16_t offset = (uint16_t)(1u + index * 2u);
        palette[index] = (uint16_t)data[offset] | ((uint16_t)data[offset + 1u] << 8u);
    }

    for (uint32_t pixel = 0u; pixel < pixels; ++pixel) {
        const uint8_t packed = data[index_offset + pixel / 2u];
        const uint8_t palette_index = (pixel & 1u) == 0u ? (uint8_t)(packed >> 4u) : (uint8_t)(packed & 0x0Fu);
        if (palette_index >= palette_count) {
            return false;
        }
        const uint16_t px = (uint16_t)(pixel % width);
        const uint16_t py = (uint16_t)(pixel / width);
        framebuffer[framebuffer_index((uint16_t)(x + px), (uint16_t)(y + py))] = panel_word(palette[palette_index]);
    }
    return true;
}

static bool decode_index4_palette_scale2(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                                         const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    if (length < 3u) {
        return false;
    }

    const uint8_t palette_count = data[0];
    if (palette_count == 0u || palette_count > 16u) {
        return false;
    }
    const uint16_t palette_bytes = (uint16_t)palette_count * 2u;
    const uint16_t index_offset = (uint16_t)(1u + palette_bytes);
    const uint16_t index_bytes = (uint16_t)((pixels + 1u) / 2u);
    if ((uint32_t)index_offset + index_bytes != length) {
        return false;
    }

    uint16_t palette[16];
    for (uint8_t index = 0u; index < palette_count; ++index) {
        const uint16_t offset = (uint16_t)(1u + index * 2u);
        palette[index] = (uint16_t)data[offset] | ((uint16_t)data[offset + 1u] << 8u);
    }

    for (uint32_t pixel = 0u; pixel < pixels; ++pixel) {
        const uint8_t packed = data[index_offset + pixel / 2u];
        const uint8_t palette_index = (pixel & 1u) == 0u ? (uint8_t)(packed >> 4u) : (uint8_t)(packed & 0x0Fu);
        if (palette_index >= palette_count) {
            return false;
        }
        const uint16_t px = (uint16_t)(pixel % width);
        const uint16_t py = (uint16_t)(pixel / width);
        write_scale2_pixel((uint16_t)(x + px * 2u), (uint16_t)(y + py * 2u), palette[palette_index]);
    }
    return true;
}

static bool decode_index6_palette(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                                  const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    if (length < 4u) {
        return false;
    }

    const uint8_t palette_count = data[0];
    if (palette_count == 0u || palette_count > 64u) {
        return false;
    }
    const uint16_t palette_bytes = (uint16_t)palette_count * 2u;
    const uint16_t index_offset = (uint16_t)(1u + palette_bytes);
    const uint16_t index_bytes = (uint16_t)((pixels * 6u + 7u) / 8u);
    if ((uint32_t)index_offset + index_bytes != length) {
        return false;
    }

    uint16_t palette[64];
    for (uint8_t index = 0u; index < palette_count; ++index) {
        const uint16_t offset = (uint16_t)(1u + index * 2u);
        palette[index] = (uint16_t)data[offset] | ((uint16_t)data[offset + 1u] << 8u);
    }

    for (uint32_t pixel = 0u; pixel < pixels; ++pixel) {
        const uint32_t bit_offset = pixel * 6u;
        const uint16_t byte_offset = (uint16_t)(bit_offset / 8u);
        const uint8_t shift = (uint8_t)(bit_offset & 7u);
        uint16_t packed = data[index_offset + byte_offset];
        if (shift > 2u) {
            packed |= (uint16_t)data[index_offset + byte_offset + 1u] << 8u;
        }
        const uint8_t palette_index = (uint8_t)((packed >> shift) & 0x3Fu);
        if (palette_index >= palette_count) {
            return false;
        }
        const uint16_t px = (uint16_t)(pixel % width);
        const uint16_t py = (uint16_t)(pixel / width);
        framebuffer[framebuffer_index((uint16_t)(x + px), (uint16_t)(y + py))] = panel_word(palette[palette_index]);
    }
    return true;
}

static inline void write_scale2_pixel(uint16_t x, uint16_t y, uint16_t rgb565)
{
    const uint16_t word = panel_word(rgb565);
    const uint32_t top_left = framebuffer_index(x, y);
    const uint32_t top_right = framebuffer_index((uint16_t)(x + 1u), y);
    const uint32_t bottom_left = framebuffer_index(x, (uint16_t)(y + 1u));
    const uint32_t bottom_right = framebuffer_index((uint16_t)(x + 1u), (uint16_t)(y + 1u));
    framebuffer[top_left] = word;
    framebuffer[top_right] = word;
    framebuffer[bottom_left] = word;
    framebuffer[bottom_right] = word;
}

static bool decode_index6_palette_scale2(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                                         const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    if (length < 4u) {
        return false;
    }

    const uint8_t palette_count = data[0];
    if (palette_count == 0u || palette_count > 64u) {
        return false;
    }
    const uint16_t palette_bytes = (uint16_t)palette_count * 2u;
    const uint16_t index_offset = (uint16_t)(1u + palette_bytes);
    const uint16_t index_bytes = (uint16_t)((pixels * 6u + 7u) / 8u);
    if ((uint32_t)index_offset + index_bytes != length) {
        return false;
    }

    uint16_t palette[64];
    for (uint8_t index = 0u; index < palette_count; ++index) {
        const uint16_t offset = (uint16_t)(1u + index * 2u);
        palette[index] = (uint16_t)data[offset] | ((uint16_t)data[offset + 1u] << 8u);
    }

    for (uint32_t pixel = 0u; pixel < pixels; ++pixel) {
        const uint32_t bit_offset = pixel * 6u;
        const uint16_t byte_offset = (uint16_t)(bit_offset / 8u);
        const uint8_t shift = (uint8_t)(bit_offset & 7u);
        uint16_t packed = data[index_offset + byte_offset];
        if (shift > 2u) {
            packed |= (uint16_t)data[index_offset + byte_offset + 1u] << 8u;
        }
        const uint8_t palette_index = (uint8_t)((packed >> shift) & 0x3Fu);
        if (palette_index >= palette_count) {
            return false;
        }
        const uint16_t px = (uint16_t)(pixel % width);
        const uint16_t py = (uint16_t)(pixel / width);
        write_scale2_pixel((uint16_t)(x + px * 2u), (uint16_t)(y + py * 2u), palette[palette_index]);
    }
    return true;
}

static bool decode_rgb565_scale2_raw(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                                     const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    if (length != pixels * 2u) {
        return false;
    }

    for (uint32_t pixel = 0; pixel < pixels; ++pixel) {
        const uint16_t value = (uint16_t)data[pixel * 2u] | ((uint16_t)data[pixel * 2u + 1u] << 8);
        const uint16_t px = (uint16_t)(pixel % width);
        const uint16_t py = (uint16_t)(pixel / width);
        write_scale2_pixel((uint16_t)(x + px * 2u), (uint16_t)(y + py * 2u), value);
    }
    return true;
}

static bool decode_rgb565_scale2_rle(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                                     const uint8_t *data, uint16_t length)
{
    const uint32_t pixels = (uint32_t)width * height;
    uint32_t written = 0;
    uint16_t offset = 0;

    while (offset + 3u <= length && written < pixels) {
        const uint8_t run = data[offset++];
        const uint16_t value = (uint16_t)data[offset] | ((uint16_t)data[offset + 1u] << 8u);
        offset += 2u;

        if (run == 0u || written + run > pixels) {
            return false;
        }

        for (uint8_t count = 0u; count < run; ++count) {
            const uint32_t pixel = written++;
            const uint16_t px = (uint16_t)(pixel % width);
            const uint16_t py = (uint16_t)(pixel / width);
            write_scale2_pixel((uint16_t)(x + px * 2u), (uint16_t)(y + py * 2u), value);
        }
    }

    return written == pixels && offset == length;
}

bool renderer_blit_tile(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint16_t color,
                        uint8_t pixel_format, uint8_t codec, const uint8_t *data, uint16_t length)
{
    if (data == NULL) {
        return false;
    }
    if (pixel_format == RPD_PIXEL_RGB565_SCALE2 || pixel_format == RPD_PIXEL_INDEX4_SCALE2 ||
        pixel_format == RPD_PIXEL_INDEX6_SCALE2) {
        if (!check_scale2_tile_bounds(x, y, width, height)) {
            return false;
        }
    } else if (!check_tile_bounds(x, y, width, height)) {
        return false;
    }

    bool decoded = false;
    if (pixel_format == RPD_PIXEL_RGB565) {
        if (codec == RPD_CODEC_RAW) {
            decoded = decode_rgb565_raw(x, y, width, height, data, length);
        } else if (codec == RPD_CODEC_RLE) {
            decoded = decode_rgb565_rle(x, y, width, height, data, length);
        }
    } else if (pixel_format == RPD_PIXEL_INDEX4) {
        if (codec == RPD_CODEC_PALETTE4) {
            decoded = decode_index4_palette(x, y, width, height, data, length);
        }
    } else if (pixel_format == RPD_PIXEL_INDEX6) {
        if (codec == RPD_CODEC_PALETTE64) {
            decoded = decode_index6_palette(x, y, width, height, data, length);
        }
    } else if (pixel_format == RPD_PIXEL_ALPHA8) {
        if (codec == RPD_CODEC_RAW) {
            decoded = decode_alpha_raw(x, y, width, height, color, data, length);
        } else if (codec == RPD_CODEC_RLE) {
            decoded = decode_alpha_rle(x, y, width, height, color, data, length);
        }
    } else if (pixel_format == RPD_PIXEL_RGB565_SCALE2) {
        if (codec == RPD_CODEC_RAW) {
            decoded = decode_rgb565_scale2_raw(x, y, width, height, data, length);
        } else if (codec == RPD_CODEC_RLE) {
            decoded = decode_rgb565_scale2_rle(x, y, width, height, data, length);
        }
    } else if (pixel_format == RPD_PIXEL_INDEX4_SCALE2) {
        if (codec == RPD_CODEC_PALETTE4) {
            decoded = decode_index4_palette_scale2(x, y, width, height, data, length);
        }
    } else if (pixel_format == RPD_PIXEL_INDEX6_SCALE2) {
        if (codec == RPD_CODEC_PALETTE64) {
            decoded = decode_index6_palette_scale2(x, y, width, height, data, length);
        }
    }

    if (decoded) {
        const uint16_t dirty_height =
            (pixel_format == RPD_PIXEL_RGB565_SCALE2 || pixel_format == RPD_PIXEL_INDEX4_SCALE2 ||
             pixel_format == RPD_PIXEL_INDEX6_SCALE2)
                ? (uint16_t)(height * 2u)
                : height;
        mark_dirty(y, (uint16_t)(y + dirty_height - 1u));
    }
    return decoded;
}

bool renderer_present_begin(void)
{
    if (present_active || AMOLED_2IN41_TransferActive()) {
        return false;
    }

    present_active = true;
    present_scan_y = 0u;
    active_band_y0 = 0u;
    active_band_y1 = 0u;
    return true;
}

bool renderer_present_active(void)
{
    return present_active;
}

void renderer_cancel_present(void)
{
    AMOLED_2IN41_CancelTransfer();
    present_active = false;
    present_scan_y = 0u;
    active_band_y0 = 0u;
    active_band_y1 = 0u;
}

renderer_present_status_t renderer_present_task(void)
{
    if (!present_active) {
        return RENDERER_PRESENT_IDLE;
    }

    if (AMOLED_2IN41_TransferActive()) {
        const AMOLED_2IN41_TRANSFER_STATUS display_status = AMOLED_2IN41_PollTransfer();
        if (display_status == AMOLED_2IN41_TRANSFER_ACTIVE) {
            return RENDERER_PRESENT_ACTIVE;
        }
        if (display_status != AMOLED_2IN41_TRANSFER_COMPLETE) {
            present_active = false;
            return RENDERER_PRESENT_ERROR;
        }

        clear_dirty_band(active_band_y0, active_band_y1);
        present_scan_y = (uint16_t)(active_band_y1 + 1u);
    }

    uint16_t band_y0;
    uint16_t band_y1;
    if (!find_dirty_band(present_scan_y, &band_y0, &band_y1)) {
        present_active = false;
        return RENDERER_PRESENT_COMPLETE;
    }

    active_band_y0 = band_y0;
    active_band_y1 = band_y1;
    if (!AMOLED_2IN41_BeginFullWidthRows(band_y0, (uint16_t)(band_y1 + 1u), framebuffer)) {
        present_active = false;
        return RENDERER_PRESENT_ERROR;
    }
    return RENDERER_PRESENT_ACTIVE;
}

bool renderer_flush_dirty(void)
{
    if (!renderer_present_begin()) {
        return false;
    }

    while (true) {
        const renderer_present_status_t status = renderer_present_task();
        if (status == RENDERER_PRESENT_COMPLETE) {
            return true;
        }
        if (status == RENDERER_PRESENT_ERROR || status == RENDERER_PRESENT_IDLE) {
            return false;
        }
        tight_loop_contents();
    }
}

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

uint32_t renderer_canvas_crc32(void)
{
    uint32_t crc = 0xFFFFFFFFu;

    for (uint32_t pixel = 0u; pixel < (uint32_t)RPD_SCREEN_WIDTH * RPD_SCREEN_HEIGHT; ++pixel) {
        const uint16_t value = host_word(framebuffer[pixel]);
        const uint8_t bytes[2] = {
            (uint8_t)(value & 0xFFu),
            (uint8_t)(value >> 8u),
        };
        crc = crc32_update(crc, bytes, sizeof(bytes));
    }

    return ~crc;
}

void renderer_set_brightness(uint8_t percent)
{
    AMOLED_2IN41_SetBrightness(percent);
}
