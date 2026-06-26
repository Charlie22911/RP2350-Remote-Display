#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rtc_pcf85063.h"
#include "hardware/i2c.h"

#define RTC_ADDRESS 0x51u
#define CONTROL_1 0x00u
#define SECONDS 0x04u
#define CONTROL_1_STOP (1u << 5)
#define SECONDS_OS (1u << 7)

i2c_inst_t rpd_test_i2c1;

static uint8_t registers[256];
static uint8_t read_pointer;
static int write_operations;

int i2c_write_timeout_us(
    i2c_inst_t *i2c,
    uint8_t addr,
    const uint8_t *src,
    size_t len,
    bool nostop,
    uint timeout_us
) {
    (void)i2c;
    (void)timeout_us;
    assert(addr == RTC_ADDRESS);
    assert(src != NULL);
    if (nostop) {
        assert(len == 1u);
        read_pointer = src[0];
        return (int)len;
    }
    assert(len >= 2u);
    const uint8_t start = src[0];
    assert((size_t)start + len - 1u <= sizeof(registers));
    memcpy(&registers[start], &src[1], len - 1u);
    ++write_operations;
    return (int)len;
}

int i2c_read_timeout_us(
    i2c_inst_t *i2c,
    uint8_t addr,
    uint8_t *dst,
    size_t len,
    bool nostop,
    uint timeout_us
) {
    (void)i2c;
    (void)nostop;
    (void)timeout_us;
    assert(addr == RTC_ADDRESS);
    assert(dst != NULL);
    assert((size_t)read_pointer + len <= sizeof(registers));
    memcpy(dst, &registers[read_pointer], len);
    return (int)len;
}

static void set_initial_calendar(void) {
    memset(registers, 0, sizeof(registers));
    registers[CONTROL_1] = 0u;
    registers[SECONDS + 0u] = 0x56u;
    registers[SECONDS + 1u] = 0x34u;
    registers[SECONDS + 2u] = 0x12u;
    registers[SECONDS + 3u] = 0x25u;
    registers[SECONDS + 4u] = 4u;
    registers[SECONDS + 5u] = 0x06u;
    registers[SECONDS + 6u] = 0x26u;
    write_operations = 0;
}

static void test_read_and_power_loss_flag(void) {
    set_initial_calendar();
    rpd_rtc_init();
    assert(rpd_rtc_is_available());

    rpd_rtc_datetime_t value;
    assert(rpd_rtc_read(&value));
    assert(value.year == 2026u);
    assert(value.month == 6u);
    assert(value.day == 25u);
    assert(value.hour == 12u);
    assert(value.minute == 34u);
    assert(value.second == 56u);
    assert(value.weekday == 4u);
    assert(value.oscillator_valid);
    assert(value.running);
    assert(value.twenty_four_hour);

    registers[SECONDS] |= SECONDS_OS;
    assert(rpd_rtc_read(&value));
    assert(!value.oscillator_valid);
}

static void test_set_uses_bcd_stops_then_restarts(void) {
    set_initial_calendar();
    rpd_rtc_init();
    registers[CONTROL_1] = 0x05u;
    write_operations = 0;

    const rpd_rtc_datetime_t target = {
        .year = 2028u,
        .month = 2u,
        .day = 29u,
        .hour = 23u,
        .minute = 59u,
        .second = 58u,
        .weekday = 2u,
    };
    assert(rpd_rtc_set(&target));
    assert(write_operations == 3);
    assert((registers[CONTROL_1] & CONTROL_1_STOP) == 0u);
    assert(registers[CONTROL_1] == 0x05u);
    assert(registers[SECONDS + 0u] == 0x58u);
    assert(registers[SECONDS + 1u] == 0x59u);
    assert(registers[SECONDS + 2u] == 0x23u);
    assert(registers[SECONDS + 3u] == 0x29u);
    assert(registers[SECONDS + 4u] == 2u);
    assert(registers[SECONDS + 5u] == 0x02u);
    assert(registers[SECONDS + 6u] == 0x28u);

    rpd_rtc_datetime_t value;
    assert(rpd_rtc_read(&value));
    assert(value.year == 2028u && value.month == 2u && value.day == 29u);
    assert(value.hour == 23u && value.minute == 59u && value.second == 58u);
}

static void test_invalid_calendar_is_rejected_without_i2c_write(void) {
    set_initial_calendar();
    rpd_rtc_init();
    write_operations = 0;
    const rpd_rtc_datetime_t invalid = {
        .year = 2026u,
        .month = 2u,
        .day = 29u,
        .hour = 0u,
        .minute = 0u,
        .second = 0u,
        .weekday = 0u,
    };
    assert(!rpd_rtc_set(&invalid));
    assert(write_operations == 0);
}

int main(void) {
    test_read_and_power_loss_flag();
    test_set_uses_bcd_stops_then_restarts();
    test_invalid_calendar_is_rejected_without_i2c_write();
    puts("PCF85063 RTC harness passed");
    return 0;
}
