#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

#include "AMOLED_2in41.h"
#include "builtin_font.h"
#include "pico/stdlib.h"

void *rp_mem_calloc(size_t count, size_t size)
{
    return calloc(count, size);
}

void *rp_mem_malloc(size_t size)
{
    return malloc(size);
}

void rp_mem_free(void *ptr)
{
    free(ptr);
}

uint32_t rpd_builtin_font_glyph_count(void)
{
    return 127011u;
}

bool rpd_builtin_font_lookup(uint32_t codepoint, rpd_builtin_font_glyph_t *glyph)
{
    static const uint8_t narrow[RPD_BUILTIN_FONT_CELL_HEIGHT] = {
        0x00u, 0x18u, 0x3Cu, 0x7Eu, 0xFFu, 0x7Eu, 0x3Cu, 0x18u,
        0x00u, 0x18u, 0x3Cu, 0x7Eu, 0xFFu, 0x7Eu, 0x3Cu, 0x18u,
    };
    static const uint8_t wide[RPD_BUILTIN_FONT_CELL_HEIGHT * 2u] = {
        0xFFu, 0xFFu, 0x81u, 0x81u, 0xBDu, 0xBDu, 0xA5u, 0xA5u,
        0xA5u, 0xA5u, 0xBDu, 0xBDu, 0x81u, 0x81u, 0xFFu, 0xFFu,
        0xFFu, 0xFFu, 0x81u, 0x81u, 0xBDu, 0xBDu, 0xA5u, 0xA5u,
        0xA5u, 0xA5u, 0xBDu, 0xBDu, 0x81u, 0x81u, 0xFFu, 0xFFu,
    };
    if (glyph == NULL) {
        return false;
    }
    if (codepoint == 0x10FFFFu) {
        return false;
    }
    *glyph = (rpd_builtin_font_glyph_t){
        .rows = codepoint == 0x6F22u ? wide : narrow,
        .cell_columns = codepoint == 0x6F22u ? 2u : 1u,
        .bytes_per_row = codepoint == 0x6F22u ? 2u : 1u,
    };
    return true;
}

void AMOLED_2IN41_SetBrightness(uint8_t brightness)
{
    (void)brightness;
}

bool AMOLED_2IN41_TransferActive(void)
{
    return false;
}

AMOLED_2IN41_TRANSFER_STATUS AMOLED_2IN41_PollTransfer(void)
{
    return AMOLED_2IN41_TRANSFER_COMPLETE;
}

void AMOLED_2IN41_CancelTransfer(void) {}

bool AMOLED_2IN41_BeginFullWidthRows(uint32_t start_y, uint32_t end_y, const uint16_t *image)
{
    (void)start_y;
    (void)end_y;
    (void)image;
    return true;
}

#include "../firmware/renderer.c"
#include "../firmware/resource_cache.c"

static uint16_t pixel(uint16_t x, uint16_t y)
{
    return host_word(framebuffer[framebuffer_index(x, y)]);
}

static void set_pixel(uint16_t x, uint16_t y, uint16_t color)
{
    renderer_fill_rect(x, y, 1u, 1u, color);
}

static uint16_t pattern(uint16_t x, uint16_t y)
{
    return (uint16_t)(0x1000u + y * 16u + x);
}

static void fill_pattern(uint16_t x, uint16_t y, uint16_t width, uint16_t height)
{
    for (uint16_t row = 0u; row < height; ++row) {
        for (uint16_t column = 0u; column < width; ++column) {
            set_pixel((uint16_t)(x + column), (uint16_t)(y + row), pattern(column, row));
        }
    }
}

static void test_overlap_copy(void)
{
    renderer_clear(0u);
    fill_pattern(10u, 10u, 6u, 4u);

    assert(renderer_copy_rect(10u, 10u, 5u, 3u, 11u, 11u));
    for (uint16_t row = 0u; row < 3u; ++row) {
        for (uint16_t column = 0u; column < 5u; ++column) {
            assert(pixel((uint16_t)(11u + column), (uint16_t)(11u + row)) == pattern(column, row));
        }
    }

    assert(!renderer_copy_rect(449u, 0u, 2u, 1u, 0u, 0u));
    assert(!renderer_copy_rect(0u, 0u, 0u, 1u, 0u, 0u));
}

static void assert_scroll(int16_t delta_x, int16_t delta_y)
{
    enum { X = 20, Y = 30, WIDTH = 5, HEIGHT = 4 };
    const uint16_t fill = 0xF800u;

    renderer_clear(0u);
    fill_pattern(X, Y, WIDTH, HEIGHT);
    assert(renderer_scroll_rect(X, Y, WIDTH, HEIGHT, delta_x, delta_y, fill));

    for (int32_t row = 0; row < HEIGHT; ++row) {
        for (int32_t column = 0; column < WIDTH; ++column) {
            const int32_t source_x = column - delta_x;
            const int32_t source_y = row - delta_y;
            const uint16_t expected = source_x >= 0 && source_x < WIDTH && source_y >= 0 && source_y < HEIGHT
                                          ? pattern((uint16_t)source_x, (uint16_t)source_y)
                                          : fill;
            assert(pixel((uint16_t)(X + column), (uint16_t)(Y + row)) == expected);
        }
    }
}

static void test_scroll_directions_and_fill(void)
{
    assert_scroll(-1, 0);
    assert_scroll(1, 0);
    assert_scroll(0, -1);
    assert_scroll(0, 1);
    assert_scroll(-1, -1);
    assert_scroll(1, -1);
    assert_scroll(-1, 1);
    assert_scroll(1, 1);

    renderer_clear(0u);
    fill_pattern(20u, 30u, 5u, 4u);
    assert(renderer_scroll_rect(20u, 30u, 5u, 4u, 5, 0, 0x07E0u));
    for (uint16_t row = 0u; row < 4u; ++row) {
        for (uint16_t column = 0u; column < 5u; ++column) {
            assert(pixel((uint16_t)(20u + column), (uint16_t)(30u + row)) == 0x07E0u);
        }
    }

    assert(!renderer_scroll_rect(449u, 0u, 2u, 1u, 0, 0, 0u));
}

static void test_line_clipping_and_work_bounds(void)
{
    renderer_clear(0u);
    assert(renderer_line(UINT16_MAX, UINT16_MAX, 0u, 0u, 0xF800u, 1u));
    assert(pixel(0u, 0u) == 0xF800u);
    assert(pixel(449u, 449u) == 0xF800u);

    renderer_clear(0u);
    assert(renderer_line(60000u, 60000u, UINT16_MAX, UINT16_MAX, 0x07E0u, 1u));
    assert(pixel(449u, 599u) == 0u);

    assert(!renderer_line(0u, 0u, 449u, 599u, 0xFFFFu,
                          (uint8_t)(RPD_LINE_MAX_THICKNESS + 1u)));
    assert(pixel(0u, 0u) == 0u);

    static const uint8_t over_budget_polyline[] = {
        0xFFu, 0xFFu, RPD_LINE_MAX_THICKNESS, 3u,
        0x00u, 0x00u, 0x00u, 0x00u,
        0xC1u, 0x01u, 0x57u, 0x02u,
        0x00u, 0x00u, 0x00u, 0x00u,
    };
    assert(!renderer_polyline(over_budget_polyline, sizeof(over_budget_polyline)));
    assert(pixel(0u, 0u) == 0u);
}

static void test_palette64_decode(void)
{
    /* Palette = [black, red, green], index stream = [0, 1, 2, 2, 1, 0]. */
    static const uint8_t encoded[] = {
        3u,
        0x00u, 0x00u,
        0x00u, 0xF8u,
        0xE0u, 0x07u,
        0x40u, 0x20u, 0x08u, 0x01u, 0x00u,
    };
    static const uint16_t expected[] = {
        0x0000u, 0xF800u, 0x07E0u,
        0x07E0u, 0xF800u, 0x0000u,
    };

    renderer_clear(0u);
    assert(renderer_blit_tile(40u, 50u, 3u, 2u, 0u, RPD_PIXEL_INDEX6,
                              RPD_CODEC_PALETTE64, encoded, sizeof(encoded)));
    for (uint16_t row = 0u; row < 2u; ++row) {
        for (uint16_t column = 0u; column < 3u; ++column) {
            assert(pixel((uint16_t)(40u + column), (uint16_t)(50u + row)) ==
                   expected[row * 3u + column]);
        }
    }
    assert(!renderer_blit_tile(0u, 0u, 3u, 2u, 0u, RPD_PIXEL_INDEX6,
                               RPD_CODEC_PALETTE64, encoded, (uint16_t)(sizeof(encoded) - 1u)));
}

static void test_palette64_scale2_decode(void)
{
    /* Palette = [black, red, green], index stream = [0, 1, 2, 2, 1, 0]. */
    static const uint8_t encoded[] = {
        3u,
        0x00u, 0x00u,
        0x00u, 0xF8u,
        0xE0u, 0x07u,
        0x40u, 0x20u, 0x08u, 0x01u, 0x00u,
    };
    static const uint16_t expected[] = {
        0x0000u, 0xF800u, 0x07E0u,
        0x07E0u, 0xF800u, 0x0000u,
    };

    renderer_clear(0u);
    assert(renderer_blit_tile(40u, 50u, 3u, 2u, 0u, RPD_PIXEL_INDEX6_SCALE2,
                              RPD_CODEC_PALETTE64, encoded, sizeof(encoded)));
    for (uint16_t row = 0u; row < 2u; ++row) {
        for (uint16_t column = 0u; column < 3u; ++column) {
            const uint16_t color = expected[row * 3u + column];
            const uint16_t x = (uint16_t)(40u + column * 2u);
            const uint16_t y = (uint16_t)(50u + row * 2u);
            assert(pixel(x, y) == color);
            assert(pixel((uint16_t)(x + 1u), y) == color);
            assert(pixel(x, (uint16_t)(y + 1u)) == color);
            assert(pixel((uint16_t)(x + 1u), (uint16_t)(y + 1u)) == color);
        }
    }
    assert(!renderer_blit_tile(0u, 0u, 3u, 2u, 0u, RPD_PIXEL_INDEX6_SCALE2,
                               RPD_CODEC_PALETTE64, encoded, (uint16_t)(sizeof(encoded) - 1u)));
}

static void test_palette64_resource_cache(void)
{
    static const uint8_t encoded[] = {
        3u,
        0x00u, 0x00u,
        0x00u, 0xF8u,
        0xE0u, 0x07u,
        0x40u, 0x20u, 0x08u, 0x01u, 0x00u,
    };
    static const uint8_t invalid_index[] = {
        1u,
        0x00u, 0x00u,
        0x01u,
    };

    rpd_resource_cache_init();
    assert(rpd_resource_cache_encoded_data_valid(3u, 2u, RPD_PIXEL_INDEX6,
                                                 RPD_CODEC_PALETTE64, encoded, sizeof(encoded)));
    assert(rpd_resource_cache_define(7u, 3u, 2u, RPD_PIXEL_INDEX6,
                                     RPD_CODEC_PALETTE64, encoded, sizeof(encoded)));
    assert(rpd_resource_cache_contains(7u));
    renderer_clear(0u);
    assert(rpd_resource_cache_draw(7u, 10u, 20u, 0u));
    assert(pixel(11u, 20u) == 0xF800u);
    assert(rpd_resource_cache_release(7u));

    assert(!rpd_resource_cache_encoded_data_valid(1u, 1u, RPD_PIXEL_INDEX6,
                                                  RPD_CODEC_PALETTE64,
                                                  invalid_index, sizeof(invalid_index)));
}

static void test_terminal_grid_text_metrics(void)
{
    static const uint8_t narrow[] = "CPU";
    static const uint8_t wide[] = {'A', 0xE6u, 0xBCu, 0xA2u, 'B'};
    static const uint8_t missing[] = {0xF4u, 0x8Fu, 0xBFu, 0xBFu};
    renderer_text_metrics_t metrics;

    assert(renderer_measure_text(RPD_BUILTIN_FONT_UI_MONO_8X16, 1u, narrow,
                                 (uint16_t)(sizeof(narrow) - 1u), &metrics));
    assert(metrics.width == 3u * RPD_BUILTIN_FONT_CELL_WIDTH);
    assert(metrics.missing_glyph_count == 0u);

    assert(renderer_measure_text(RPD_BUILTIN_FONT_UI_MONO_8X16, 1u, wide,
                                 (uint16_t)sizeof(wide), &metrics));
    assert(metrics.width == 4u * RPD_BUILTIN_FONT_CELL_WIDTH);
    assert(metrics.glyph_count == 3u);
    assert(metrics.missing_glyph_count == 0u);

    assert(renderer_measure_text(RPD_BUILTIN_FONT_UI_MONO_8X16, 2u, missing,
                                 (uint16_t)sizeof(missing), &metrics));
    assert(metrics.width == 2u * RPD_BUILTIN_FONT_CELL_WIDTH);
    assert(metrics.missing_glyph_count == 1u);
}

int main(void)
{
    assert(renderer_init());
    test_overlap_copy();
    test_scroll_directions_and_fill();
    test_line_clipping_and_work_bounds();
    test_palette64_decode();
    test_palette64_scale2_decode();
    test_palette64_resource_cache();
    test_terminal_grid_text_metrics();
    return 0;
}
