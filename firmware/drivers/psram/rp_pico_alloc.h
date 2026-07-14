

#ifndef _RP_PICO_ALLOC_H_
#define _RP_PICO_ALLOC_H_

#include <stdbool.h>
#include <stdlib.h>

#define RP2350_XIP_CSI_PIN  47
#define PSRAM_CMD_QUAD_END 0xF5
#define PSRAM_CMD_QUAD_ENABLE 0x35
#define PSRAM_CMD_READ_ID 0x9F
#define PSRAM_CMD_RSTEN 0x66
#define PSRAM_CMD_RST 0x99
#define PSRAM_CMD_QUAD_READ 0xEB
#define PSRAM_CMD_QUAD_WRITE 0x38
#define PSRAM_CMD_NOOP 0xFF
#define PSRAM_CMD_LINEAR_TOGGLE 0xC0

#define PSRAM_ID 0x5D

// max select pulse width = 8us
#define PSRAM_MAX_SELECT 0.000008f

// min deselect pulse width = 50ns
#define PSRAM_MIN_DESELECT 0.000000050f

// The performance build retains the board's established ~125 MHz PSRAM clock.
// Set RPD_PSRAM_MAX_SCK_HZ=109000000 for the conservative data-sheet ceiling.
#ifndef RPD_PSRAM_MAX_SCK_HZ
#define RPD_PSRAM_MAX_SCK_HZ 133000000u
#endif
#define PSRAM_MAX_SCK_HZ RPD_PSRAM_MAX_SCK_HZ

// Bound every direct-mode QMI wait. A missing or wedged device must fail
// allocator initialization instead of hanging before the watchdog is active.
#define PSRAM_QMI_WAIT_ITERATIONS 1000000u

#ifdef __cplusplus
extern "C"
{
#endif
    void *rp_mem_malloc(size_t size);
    void rp_mem_free(void *ptr);
    void *rp_mem_realloc(void *ptr, size_t size);
    void *rp_mem_calloc(size_t num, size_t size);
    size_t rp_mem_max_free_size(void);
    // wrappers
#if defined(RP_PICO_ALLOC_WRAP)
    void *__wrap_malloc(size_t size);
    void __wrap_free(void *ptr);
    void *__wrap_realloc(void *ptr, size_t size);
    void *__wrap_calloc(size_t num, size_t size);
#endif
#ifdef __cplusplus
}
#endif

#endif
