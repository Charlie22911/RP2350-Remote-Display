#ifndef RPD_TEST_MOCK_HARDWARE_I2C_H
#define RPD_TEST_MOCK_HARDWARE_I2C_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef unsigned int uint;
typedef struct i2c_inst {
    unsigned int unused;
} i2c_inst_t;

extern i2c_inst_t rpd_test_i2c1;
#define i2c1 (&rpd_test_i2c1)

int i2c_write_timeout_us(
    i2c_inst_t *i2c,
    uint8_t addr,
    const uint8_t *src,
    size_t len,
    bool nostop,
    uint timeout_us
);

int i2c_read_timeout_us(
    i2c_inst_t *i2c,
    uint8_t addr,
    uint8_t *dst,
    size_t len,
    bool nostop,
    uint timeout_us
);

#endif
