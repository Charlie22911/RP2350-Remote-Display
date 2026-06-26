#include <assert.h>
#include <stdint.h>

#include "builtin_font.h"

int main(void)
{
    rpd_builtin_font_glyph_t glyph;

    assert(rpd_builtin_font_glyph_count() == 127011u);

    assert(rpd_builtin_font_lookup(0x003Fu, &glyph));
    assert(glyph.cell_columns == 1u && glyph.bytes_per_row == 1u);

    assert(rpd_builtin_font_lookup(0x2500u, &glyph));
    assert(glyph.cell_columns == 1u && glyph.bytes_per_row == 1u);

    assert(rpd_builtin_font_lookup(0x6F22u, &glyph));
    assert(glyph.cell_columns == 2u && glyph.bytes_per_row == 2u);

    assert(rpd_builtin_font_lookup(0x1F434u, &glyph));
    assert(glyph.cell_columns == 2u && glyph.bytes_per_row == 2u);

    assert(!rpd_builtin_font_lookup(0x10FFFFu, &glyph));
    return 0;
}
