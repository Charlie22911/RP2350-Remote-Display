#ifndef RP2350_REMOTE_BUILTIN_FONT_H
#define RP2350_REMOTE_BUILTIN_FONT_H

#include <stdbool.h>
#include <stdint.h>

#define RPD_BUILTIN_FONT_UI_MONO_8X16 0u
#define RPD_BUILTIN_FONT_CELL_WIDTH 8u
#define RPD_BUILTIN_FONT_CELL_HEIGHT 16u
#define RPD_BUILTIN_FONT_ASCENT 14u
#define RPD_BUILTIN_FONT_DESCENT 2u
#define RPD_BUILTIN_FONT_LINE_GAP 0u
#define RPD_BUILTIN_FONT_FALLBACK_CODEPOINT 0x003Fu
#define RPD_BUILTIN_FONT_COVERAGE_VERSION 2u

/*
 * GNU Unifont uses a terminal-style grid. Most glyphs take one 8x16 cell.
 * Full-width glyphs, including CJK characters, take two adjacent cells.
 */
typedef struct {
    const uint8_t *rows;
    uint8_t cell_columns;
    uint8_t bytes_per_row;
} rpd_builtin_font_glyph_t;

uint32_t rpd_builtin_font_glyph_count(void);
bool rpd_builtin_font_lookup(uint32_t codepoint, rpd_builtin_font_glyph_t *glyph);

#endif
