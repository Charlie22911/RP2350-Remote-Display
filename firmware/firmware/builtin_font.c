/* GNU Unifont 17.0.04 binary asset reader. See firmware/NOTICE.md. */
#include "builtin_font.h"

#include <stddef.h>
#include <stdint.h>

#define RPD_UNIFONT_HEADER_SIZE 24u
#define RPD_UNIFONT_MAP_ENTRY_SIZE 9u
#define RPD_UNIFONT_FORMAT_VERSION 1u

extern const uint8_t rpd_builtin_font_blob_start[];
extern const uint8_t rpd_builtin_font_blob_end[];

typedef struct {
    uint32_t glyph_count;
    uint32_t map_offset;
    uint32_t bitmap_offset;
    uint32_t total_size;
} rpd_unifont_header_t;

static uint32_t read_le32(const uint8_t *data)
{
    return (uint32_t)data[0] | ((uint32_t)data[1] << 8u) | ((uint32_t)data[2] << 16u) |
           ((uint32_t)data[3] << 24u);
}

static bool read_header(rpd_unifont_header_t *header)
{
    if (header == NULL) {
        return false;
    }

    const uint8_t *const data = rpd_builtin_font_blob_start;
    const size_t available = (size_t)(rpd_builtin_font_blob_end - rpd_builtin_font_blob_start);
    if (available < RPD_UNIFONT_HEADER_SIZE || data[0] != 'R' || data[1] != 'U' || data[2] != 'F' ||
        data[3] != '1' || data[4] != RPD_UNIFONT_FORMAT_VERSION || data[5] != RPD_BUILTIN_FONT_CELL_WIDTH ||
        data[6] != RPD_BUILTIN_FONT_CELL_HEIGHT) {
        return false;
    }

    const uint32_t glyph_count = read_le32(data + 8u);
    const uint32_t map_offset = read_le32(data + 12u);
    const uint32_t bitmap_offset = read_le32(data + 16u);
    const uint32_t total_size = read_le32(data + 20u);
    const uint64_t map_end = (uint64_t)map_offset + (uint64_t)glyph_count * RPD_UNIFONT_MAP_ENTRY_SIZE;

    if (glyph_count == 0u || map_offset < RPD_UNIFONT_HEADER_SIZE || map_end > bitmap_offset ||
        bitmap_offset > total_size || total_size > available) {
        return false;
    }

    *header = (rpd_unifont_header_t){
        .glyph_count = glyph_count,
        .map_offset = map_offset,
        .bitmap_offset = bitmap_offset,
        .total_size = total_size,
    };
    return true;
}

uint32_t rpd_builtin_font_glyph_count(void)
{
    rpd_unifont_header_t header;
    return read_header(&header) ? header.glyph_count : 0u;
}

bool rpd_builtin_font_lookup(uint32_t codepoint, rpd_builtin_font_glyph_t *glyph)
{
    if (glyph == NULL) {
        return false;
    }

    rpd_unifont_header_t header;
    if (!read_header(&header)) {
        return false;
    }

    const uint8_t *const data = rpd_builtin_font_blob_start;
    uint32_t lower = 0u;
    uint32_t upper = header.glyph_count;
    while (lower < upper) {
        const uint32_t middle = lower + (upper - lower) / 2u;
        const uint8_t *const entry = data + header.map_offset + (size_t)middle * RPD_UNIFONT_MAP_ENTRY_SIZE;
        const uint32_t candidate = read_le32(entry);
        if (codepoint == candidate) {
            const uint32_t bitmap_relative_offset = read_le32(entry + 4u);
            const uint8_t cell_columns = entry[8u];
            const uint32_t glyph_bytes = (uint32_t)cell_columns * RPD_BUILTIN_FONT_CELL_HEIGHT;
            const uint64_t bitmap_end = (uint64_t)header.bitmap_offset + bitmap_relative_offset + glyph_bytes;
            if ((cell_columns != 1u && cell_columns != 2u) || bitmap_end > header.total_size) {
                return false;
            }
            *glyph = (rpd_builtin_font_glyph_t){
                .rows = data + header.bitmap_offset + bitmap_relative_offset,
                .cell_columns = cell_columns,
                .bytes_per_row = cell_columns,
            };
            return true;
        }
        if (codepoint < candidate) {
            upper = middle;
        } else {
            lower = middle + 1u;
        }
    }

    return false;
}
