#ifndef RP2350_REMOTE_RTC_PCF85063_H
#define RP2350_REMOTE_RTC_PCF85063_H

#include <stdbool.h>
#include <stdint.h>

/*
 * Driver for the PCF85063ATL RTC wired to the Waveshare RP2350-Touch-AMOLED-2.41
 * shared I2C1 bus (GPIO6 SDA, GPIO7 SCL). The device keeps calendar fields for
 * the 2000-2099 range. Times exposed by the remote protocol are always UTC.
 */

typedef struct {
    uint16_t year;
    uint8_t month;
    uint8_t day;
    uint8_t hour;
    uint8_t minute;
    uint8_t second;
    /* PCF85063 convention: Sunday=0 through Saturday=6. */
    uint8_t weekday;
    bool oscillator_valid;
    bool running;
    bool twenty_four_hour;
} rpd_rtc_datetime_t;

/* Probe the RTC after the board I2C bus has been initialized. */
void rpd_rtc_init(void);

/* True when the PCF85063 acknowledged the boot-time probe. */
bool rpd_rtc_is_available(void);

/* Read a complete calendar register snapshot from the PCF85063. */
bool rpd_rtc_read(rpd_rtc_datetime_t *out);

/*
 * Set a UTC calendar value. Valid years are 2000 through 2099. The driver
 * forces 24-hour mode, clears the oscillator-stop flag in the seconds register,
 * and resumes the RTC after the time-register write completes.
 */
bool rpd_rtc_set(const rpd_rtc_datetime_t *value);

#endif
