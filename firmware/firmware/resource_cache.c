#include "resource_cache.h"

#include <stddef.h>
#include <string.h>

#include "renderer.h"
#include "rp_pico_alloc.h"

typedef struct {
    bool in_use;
    uint32_t resource_id;
    uint16_t width;
    uint16_t height;
    uint8_t pixel_format;
    uint8_t codec;
    uint16_t encoded_length;
    uint8_t *encoded;
} rpd_resource_slot_t;

static rpd_resource_slot_t resource_slots[RPD_RESOURCE_CACHE_SLOT_CAPACITY];
static uint32_t cache_bytes_used;

static bool dimensions_valid(uint16_t width, uint16_t height)
{
    return width > 0u && height > 0u && width <= RPD_TILE_MAX_WIDTH && height <= RPD_TILE_MAX_HEIGHT;
}

static bool rle_is_valid(const uint8_t *encoded, uint16_t encoded_length, uint32_t expected_pixels,
                         uint8_t bytes_per_run)
{
    if (encoded == NULL || bytes_per_run < 2u) {
        return false;
    }

    uint16_t offset = 0u;
    uint32_t pixels = 0u;
    while ((uint32_t)offset + bytes_per_run <= encoded_length && pixels < expected_pixels) {
        const uint8_t run = encoded[offset];
        if (run == 0u || pixels + run > expected_pixels) {
            return false;
        }
        pixels += run;
        offset = (uint16_t)(offset + bytes_per_run);
    }

    return pixels == expected_pixels && offset == encoded_length;
}

static bool palette_indices_valid(const uint8_t *indices, uint32_t pixels,
                                  uint8_t bits_per_index, uint8_t palette_count)
{
    if (indices == NULL || (bits_per_index != 4u && bits_per_index != 6u)) {
        return false;
    }
    for (uint32_t pixel = 0u; pixel < pixels; ++pixel) {
        uint8_t palette_index;
        if (bits_per_index == 4u) {
            const uint8_t packed = indices[pixel / 2u];
            palette_index = (pixel & 1u) == 0u ? (uint8_t)(packed >> 4u) : (uint8_t)(packed & 0x0Fu);
        } else {
            const uint32_t bit_offset = pixel * 6u;
            const uint32_t byte_offset = bit_offset / 8u;
            const uint8_t shift = (uint8_t)(bit_offset & 7u);
            uint16_t packed = indices[byte_offset];
            if (shift > 2u) {
                packed |= (uint16_t)indices[byte_offset + 1u] << 8u;
            }
            palette_index = (uint8_t)((packed >> shift) & 0x3Fu);
        }
        if (palette_index >= palette_count) {
            return false;
        }
    }
    return true;
}

bool rpd_resource_cache_encoded_data_valid(uint16_t width, uint16_t height, uint8_t pixel_format,
                                           uint8_t codec, const uint8_t *encoded, uint16_t encoded_length)
{
    if (!dimensions_valid(width, height) || encoded == NULL || encoded_length == 0u ||
        encoded_length > RPD_MAX_ENCODED_TILE_BYTES) {
        return false;
    }

    const uint32_t pixels = (uint32_t)width * height;
    if (pixel_format == RPD_PIXEL_RGB565) {
        if (codec == RPD_CODEC_RAW) {
            return encoded_length == pixels * 2u;
        }
        if (codec == RPD_CODEC_RLE) {
            return rle_is_valid(encoded, encoded_length, pixels, 3u);
        }
        return false;
    }

    if (pixel_format == RPD_PIXEL_INDEX4) {
        if (codec != RPD_CODEC_PALETTE4 || encoded_length < 3u) {
            return false;
        }
        const uint8_t palette_count = encoded[0];
        const uint32_t index_bytes = (pixels + 1u) / 2u;
        const uint32_t expected = 1u + (uint32_t)palette_count * 2u + index_bytes;
        const uint32_t index_offset = 1u + (uint32_t)palette_count * 2u;
        return palette_count > 0u && palette_count <= 16u && expected == encoded_length &&
               palette_indices_valid(encoded + index_offset, pixels, 4u, palette_count);
    }

    if (pixel_format == RPD_PIXEL_INDEX6) {
        if (codec != RPD_CODEC_PALETTE64 || encoded_length < 4u) {
            return false;
        }
        const uint8_t palette_count = encoded[0];
        const uint32_t index_bytes = (pixels * 6u + 7u) / 8u;
        const uint32_t expected = 1u + (uint32_t)palette_count * 2u + index_bytes;
        const uint32_t index_offset = 1u + (uint32_t)palette_count * 2u;
        return palette_count > 0u && palette_count <= 64u && expected == encoded_length &&
               palette_indices_valid(encoded + index_offset, pixels, 6u, palette_count);
    }

    if (pixel_format == RPD_PIXEL_ALPHA8) {
        if (codec == RPD_CODEC_RAW) {
            return encoded_length == pixels;
        }
        if (codec == RPD_CODEC_RLE) {
            return rle_is_valid(encoded, encoded_length, pixels, 2u);
        }
        return false;
    }

    return false;
}

static rpd_resource_slot_t *find_slot(uint32_t resource_id)
{
    if (resource_id == 0u) {
        return NULL;
    }

    for (uint16_t index = 0u; index < RPD_RESOURCE_CACHE_SLOT_CAPACITY; ++index) {
        if (resource_slots[index].in_use && resource_slots[index].resource_id == resource_id) {
            return &resource_slots[index];
        }
    }
    return NULL;
}

static rpd_resource_slot_t *find_free_slot(void)
{
    for (uint16_t index = 0u; index < RPD_RESOURCE_CACHE_SLOT_CAPACITY; ++index) {
        if (!resource_slots[index].in_use) {
            return &resource_slots[index];
        }
    }
    return NULL;
}

void rpd_resource_cache_init(void)
{
    memset(resource_slots, 0, sizeof(resource_slots));
    cache_bytes_used = 0u;
}

void rpd_resource_cache_reset(void)
{
    for (uint16_t index = 0u; index < RPD_RESOURCE_CACHE_SLOT_CAPACITY; ++index) {
        rpd_resource_slot_t *slot = &resource_slots[index];
        if (slot->in_use && slot->encoded != NULL) {
            rp_mem_free(slot->encoded);
        }
        memset(slot, 0, sizeof(*slot));
    }
    cache_bytes_used = 0u;
}

bool rpd_resource_cache_contains(uint32_t resource_id)
{
    return find_slot(resource_id) != NULL;
}

bool rpd_resource_cache_define(uint32_t resource_id,
                               uint16_t width,
                               uint16_t height,
                               uint8_t pixel_format,
                               uint8_t codec,
                               const uint8_t *encoded,
                               uint16_t encoded_length)
{
    if (resource_id == 0u || find_slot(resource_id) != NULL ||
        !rpd_resource_cache_encoded_data_valid(width, height, pixel_format, codec, encoded, encoded_length)) {
        return false;
    }

    rpd_resource_slot_t *slot = find_free_slot();
    if (slot == NULL || encoded_length > RPD_RESOURCE_CACHE_BYTE_CAPACITY - cache_bytes_used) {
        return false;
    }

    uint8_t *copy = rp_mem_malloc(encoded_length);
    if (copy == NULL) {
        return false;
    }

    memcpy(copy, encoded, encoded_length);
    slot->in_use = true;
    slot->resource_id = resource_id;
    slot->width = width;
    slot->height = height;
    slot->pixel_format = pixel_format;
    slot->codec = codec;
    slot->encoded_length = encoded_length;
    slot->encoded = copy;
    cache_bytes_used += encoded_length;
    return true;
}

bool rpd_resource_cache_draw(uint32_t resource_id, uint16_t x, uint16_t y, uint16_t color)
{
    rpd_resource_slot_t *slot = find_slot(resource_id);
    if (slot == NULL) {
        return false;
    }

    return renderer_blit_tile(x, y, slot->width, slot->height, color, slot->pixel_format,
                              slot->codec, slot->encoded, slot->encoded_length);
}

bool rpd_resource_cache_release(uint32_t resource_id)
{
    rpd_resource_slot_t *slot = find_slot(resource_id);
    if (slot == NULL) {
        return false;
    }

    if (slot->encoded != NULL) {
        rp_mem_free(slot->encoded);
    }
    cache_bytes_used -= slot->encoded_length;
    memset(slot, 0, sizeof(*slot));
    return true;
}

rpd_resource_cache_info_t rpd_resource_cache_info(void)
{
    rpd_resource_cache_info_t info = {
        .slot_capacity = RPD_RESOURCE_CACHE_SLOT_CAPACITY,
        .slot_used = 0u,
        .byte_capacity = RPD_RESOURCE_CACHE_BYTE_CAPACITY,
        .byte_used = cache_bytes_used,
    };

    for (uint16_t index = 0u; index < RPD_RESOURCE_CACHE_SLOT_CAPACITY; ++index) {
        if (resource_slots[index].in_use) {
            ++info.slot_used;
        }
    }
    return info;
}
