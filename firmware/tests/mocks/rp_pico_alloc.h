#ifndef RPD_TEST_RP_PICO_ALLOC_H
#define RPD_TEST_RP_PICO_ALLOC_H

#include <stddef.h>
void *rp_mem_malloc(size_t size);
void *rp_mem_calloc(size_t count, size_t size);
void rp_mem_free(void *ptr);
#endif
