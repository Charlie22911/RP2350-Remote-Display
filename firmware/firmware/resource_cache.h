#ifndef RP2350_REMOTE_RESOURCE_CACHE_H
#define RP2350_REMOTE_RESOURCE_CACHE_H

#include <stdbool.h>
#include <stdint.h>

#include "remote_protocol.h"

#define RPD_RESOURCE_CACHE_SLOT_CAPACITY 64u
#define RPD_RESOURCE_CACHE_BYTE_CAPACITY (256u * 1024u)

typedef struct {
    uint16_t slot_capacity;
    uint16_t slot_used;
    uint32_t byte_capacity;
    uint32_t byte_used;
} rpd_resource_cache_info_t;

void rpd_resource_cache_init(void);
void rpd_resource_cache_reset(void);
bool rpd_resource_cache_contains(uint32_t resource_id);
bool rpd_resource_cache_define(uint32_t resource_id,
                               uint16_t width,
                               uint16_t height,
                               uint8_t pixel_format,
                               uint8_t codec,
                               const uint8_t *encoded,
                               uint16_t encoded_length);
bool rpd_resource_cache_draw(uint32_t resource_id, uint16_t x, uint16_t y, uint16_t color);
bool rpd_resource_cache_release(uint32_t resource_id);
rpd_resource_cache_info_t rpd_resource_cache_info(void);

#endif
