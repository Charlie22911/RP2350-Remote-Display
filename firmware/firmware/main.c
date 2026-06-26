#include <stdbool.h>
#include <stdint.h>

#include "pico/stdlib.h"
#include "hardware/watchdog.h"
#include "tusb.h"

#include "AMOLED_2in41.h"
#include "DEV_Config.h"
#include "FT6336U.h"
#include "qspi_pio.h"
#include "remote_protocol.h"
#include "renderer.h"

#define TOUCH_POLL_INTERVAL_MS 2u
#define MAIN_LOOP_WATCHDOG_MS 1500u

static void touch_task(void)
{
    static uint32_t last_poll_ms;
    static bool previous_pressed;
    static uint16_t previous_x;
    static uint16_t previous_y;
    static uint8_t previous_contacts;

    const uint32_t now = to_ms_since_boot(get_absolute_time());
    if ((uint32_t)(now - last_poll_ms) < TOUCH_POLL_INTERVAL_MS) {
        return;
    }
    last_poll_ms = now;

    FT6336U_Get_Point();
    const bool pressed = FT6336U.touch_num != 0;
    const uint16_t x = pressed ? FT6336U.touch1_x : previous_x;
    const uint16_t y = pressed ? FT6336U.touch1_y : previous_y;
    const uint8_t contacts = pressed ? (uint8_t)FT6336U.touch_num : 0u;

    if (pressed != previous_pressed || x != previous_x || y != previous_y || contacts != previous_contacts) {
        rpd_protocol_send_touch(x, y, pressed, contacts);
        previous_pressed = pressed;
        previous_x = x;
        previous_y = y;
        previous_contacts = contacts;
    }
}

int main(void)
{
    if (DEV_Module_Init() != 0) {
        while (true) {
            tight_loop_contents();
        }
    }

    QSPI_GPIO_Init(g_qspi);
    QSPI_PIO_Init(g_qspi);
    QSPI_4Wrie_Mode(&g_qspi);

    AMOLED_2IN41_Init();
    AMOLED_2IN41_SetBrightness(60);
    FT6336U_Init(FT6336U_Point_Mode);

    // The remote canvas spans the complete 450x600 panel. The host owns all UI.
    if (!renderer_init()) {
        // Visible fault indicator only. Normal startup clears the full canvas to black.
        AMOLED_2IN41_Clear(RED);
        while (true) {
            tight_loop_contents();
        }
    }

    renderer_show_waiting_screen();
    if (!renderer_flush_dirty()) {
        AMOLED_2IN41_Clear(RED);
        while (true) {
            tight_loop_contents();
        }
    }
    rpd_protocol_init();
    tusb_init();
    watchdog_enable(MAIN_LOOP_WATCHDOG_MS, true);

    while (true) {
        watchdog_update();
        tud_task();
        rpd_protocol_task();
        touch_task();
        rpd_protocol_display_task();
        tight_loop_contents();
    }
}
