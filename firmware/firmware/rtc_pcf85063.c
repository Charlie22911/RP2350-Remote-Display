#include "rtc_pcf85063.h"

#include <stddef.h>
#include <string.h>

#include "hardware/i2c.h"

#define RPD_RTC_I2C_PORT i2c1
#define RPD_RTC_I2C_ADDRESS 0x51u
#define RPD_RTC_I2C_TIMEOUT_US 20000u

#define RPD_RTC_REG_CONTROL_1 0x00u
#define RPD_RTC_REG_SECONDS 0x04u
#define RPD_RTC_TIME_REGISTER_COUNT 7u
#define RPD_RTC_SNAPSHOT_REGISTER_COUNT (RPD_RTC_REG_SECONDS + RPD_RTC_TIME_REGISTER_COUNT)

#define RPD_RTC_CONTROL_1_STOP (1u << 5)
#define RPD_RTC_CONTROL_1_CIE (1u << 2)
#define RPD_RTC_CONTROL_1_12_24 (1u << 1)
#define RPD_RTC_CONTROL_1_CAP_SEL (1u << 0)
#define RPD_RTC_SECONDS_OS (1u << 7)

static bool rtc_available;

static bool rtc_i2c_read(uint8_t register_address, uint8_t *buffer, size_t length)
{
    if (buffer == NULL || length == 0u || length > 16u) {
        return false;
    }

    const int written = i2c_write_timeout_us(RPD_RTC_I2C_PORT, RPD_RTC_I2C_ADDRESS,
                                             &register_address, 1u, true,
                                             RPD_RTC_I2C_TIMEOUT_US);
    if (written != 1) {
        return false;
    }

    const int read = i2c_read_timeout_us(RPD_RTC_I2C_PORT, RPD_RTC_I2C_ADDRESS,
                                         buffer, length, false,
                                         RPD_RTC_I2C_TIMEOUT_US);
    return read == (int)length;
}

static bool rtc_i2c_write(uint8_t register_address, const uint8_t *data, size_t length)
{
    if (data == NULL || length == 0u || length > RPD_RTC_TIME_REGISTER_COUNT) {
        return false;
    }

    uint8_t packet[1u + RPD_RTC_TIME_REGISTER_COUNT];
    packet[0] = register_address;
    memcpy(packet + 1u, data, length);

    const int written = i2c_write_timeout_us(RPD_RTC_I2C_PORT, RPD_RTC_I2C_ADDRESS,
                                             packet, length + 1u, false,
                                             RPD_RTC_I2C_TIMEOUT_US);
    return written == (int)(length + 1u);
}

static bool bcd_to_decimal(uint8_t bcd, uint8_t maximum, uint8_t *out)
{
    const uint8_t tens = (uint8_t)((bcd >> 4u) & 0x0Fu);
    const uint8_t units = (uint8_t)(bcd & 0x0Fu);
    if (out == NULL || tens > 9u || units > 9u) {
        return false;
    }
    const uint8_t value = (uint8_t)(tens * 10u + units);
    if (value > maximum) {
        return false;
    }
    *out = value;
    return true;
}

static uint8_t decimal_to_bcd(uint8_t value)
{
    return (uint8_t)(((value / 10u) << 4u) | (value % 10u));
}

static bool is_leap_year(uint16_t year)
{
    return (year % 4u) == 0u;
}

static uint8_t days_in_month(uint16_t year, uint8_t month)
{
    static const uint8_t days[] = {
        31u, 28u, 31u, 30u, 31u, 30u,
        31u, 31u, 30u, 31u, 30u, 31u,
    };
    if (month < 1u || month > 12u) {
        return 0u;
    }
    if (month == 2u && is_leap_year(year)) {
        return 29u;
    }
    return days[month - 1u];
}

static bool datetime_is_valid(const rpd_rtc_datetime_t *value)
{
    if (value == NULL || value->year < 2000u || value->year > 2099u ||
        value->month < 1u || value->month > 12u ||
        value->hour > 23u || value->minute > 59u || value->second > 59u ||
        value->weekday > 6u) {
        return false;
    }
    return value->day >= 1u && value->day <= days_in_month(value->year, value->month);
}

static bool decode_hour(uint8_t raw, bool twelve_hour_mode, uint8_t *hour)
{
    if (!twelve_hour_mode) {
        return bcd_to_decimal((uint8_t)(raw & 0x3Fu), 23u, hour);
    }

    uint8_t twelve_hour = 0u;
    if (!bcd_to_decimal((uint8_t)(raw & 0x1Fu), 12u, &twelve_hour) || twelve_hour == 0u) {
        return false;
    }
    const bool pm = (raw & (1u << 5)) != 0u;
    if (twelve_hour == 12u) {
        *hour = pm ? 12u : 0u;
    } else {
        *hour = (uint8_t)(twelve_hour + (pm ? 12u : 0u));
    }
    return true;
}

void rpd_rtc_init(void)
{
    uint8_t control_1 = 0u;
    rtc_available = rtc_i2c_read(RPD_RTC_REG_CONTROL_1, &control_1, 1u);
}

bool rpd_rtc_is_available(void)
{
    return rtc_available;
}

bool rpd_rtc_read(rpd_rtc_datetime_t *out)
{
    if (!rtc_available || out == NULL) {
        return false;
    }

    uint8_t registers[RPD_RTC_SNAPSHOT_REGISTER_COUNT];
    if (!rtc_i2c_read(RPD_RTC_REG_CONTROL_1, registers, sizeof(registers))) {
        return false;
    }

    const uint8_t control_1 = registers[0];
    const uint8_t seconds_raw = registers[4];
    const bool twelve_hour_mode = (control_1 & RPD_RTC_CONTROL_1_12_24) != 0u;

    rpd_rtc_datetime_t value = {
        .oscillator_valid = (seconds_raw & RPD_RTC_SECONDS_OS) == 0u,
        .running = (control_1 & RPD_RTC_CONTROL_1_STOP) == 0u,
        .twenty_four_hour = !twelve_hour_mode,
    };

    uint8_t year_two_digits = 0u;
    if (!bcd_to_decimal((uint8_t)(seconds_raw & 0x7Fu), 59u, &value.second) ||
        !bcd_to_decimal((uint8_t)(registers[5] & 0x7Fu), 59u, &value.minute) ||
        !decode_hour(registers[6], twelve_hour_mode, &value.hour) ||
        !bcd_to_decimal((uint8_t)(registers[7] & 0x3Fu), 31u, &value.day) ||
        (registers[8] & 0xF8u) != 0u ||
        !bcd_to_decimal((uint8_t)(registers[9] & 0x1Fu), 12u, &value.month) ||
        !bcd_to_decimal(registers[10], 99u, &year_two_digits)) {
        return false;
    }

    value.year = (uint16_t)(2000u + year_two_digits);
    value.weekday = (uint8_t)(registers[8] & 0x07u);
    if (!datetime_is_valid(&value)) {
        return false;
    }

    *out = value;
    return true;
}

bool rpd_rtc_set(const rpd_rtc_datetime_t *value)
{
    if (!rtc_available || !datetime_is_valid(value)) {
        return false;
    }

    uint8_t previous_control_1 = 0u;
    if (!rtc_i2c_read(RPD_RTC_REG_CONTROL_1, &previous_control_1, 1u)) {
        return false;
    }

    /* Preserve only electrical calibration / correction choices. Force normal 24-hour operation. */
    const uint8_t control_running = (uint8_t)(previous_control_1 &
                                              (RPD_RTC_CONTROL_1_CIE | RPD_RTC_CONTROL_1_CAP_SEL));
    const uint8_t control_stopped = (uint8_t)(control_running | RPD_RTC_CONTROL_1_STOP);
    if (!rtc_i2c_write(RPD_RTC_REG_CONTROL_1, &control_stopped, 1u)) {
        return false;
    }

    const uint8_t time_registers[RPD_RTC_TIME_REGISTER_COUNT] = {
        decimal_to_bcd(value->second),
        decimal_to_bcd(value->minute),
        decimal_to_bcd(value->hour),
        decimal_to_bcd(value->day),
        value->weekday,
        decimal_to_bcd(value->month),
        decimal_to_bcd((uint8_t)(value->year - 2000u)),
    };

    if (!rtc_i2c_write(RPD_RTC_REG_SECONDS, time_registers, sizeof(time_registers))) {
        /* Avoid leaving a functioning RTC frozen if the calendar write is interrupted. */
        (void)rtc_i2c_write(RPD_RTC_REG_CONTROL_1, &control_running, 1u);
        return false;
    }

    return rtc_i2c_write(RPD_RTC_REG_CONTROL_1, &control_running, 1u);
}
