#ifndef RPD_TEST_MOCK_TUSB_H
#define RPD_TEST_MOCK_TUSB_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CFG_TUD_ENDPOINT0_SIZE 64u

#define TUSB_DESC_DEVICE             0x01u
#define TUSB_DESC_CONFIGURATION      0x02u
#define TUSB_DESC_STRING             0x03u
#define TUSB_DESC_INTERFACE          0x04u
#define TUSB_DESC_ENDPOINT           0x05u
#define TUSB_DESC_BOS                0x0Fu
#define TUSB_DESC_DEVICE_CAPABILITY  0x10u

#define TUSB_CLASS_VENDOR_SPECIFIC   0xFFu
#define TUSB_XFER_BULK               0x02u
#define DEVICE_CAPABILITY_PLATFORM   0x05u

#define TUSB_DIR_IN                  0x01u
#define TUSB_REQ_TYPE_VENDOR         0x02u
#define TUSB_REQ_RCPT_DEVICE         0x00u

#define CONTROL_STAGE_SETUP          0x01u

#define MS_OS_20_SET_HEADER_DESCRIPTOR 0x00u
#define MS_OS_20_FEATURE_COMPATBLE_ID  0x03u
#define MS_OS_20_FEATURE_REG_PROPERTY  0x04u

#define TU_ARRAY_SIZE(_array) (sizeof(_array) / sizeof((_array)[0]))
#define U16_TO_U8S_LE(_value) \
    ((uint8_t)((uint16_t)(_value) & 0xFFu)), \
    ((uint8_t)(((uint16_t)(_value) >> 8) & 0xFFu))
#define U32_TO_U8S_LE(_value) \
    ((uint8_t)((uint32_t)(_value) & 0xFFu)), \
    ((uint8_t)(((uint32_t)(_value) >> 8) & 0xFFu)), \
    ((uint8_t)(((uint32_t)(_value) >> 16) & 0xFFu)), \
    ((uint8_t)(((uint32_t)(_value) >> 24) & 0xFFu))

#define TUD_CONFIG_DESC_LEN 9u
#define TUD_CONFIG_DESCRIPTOR(_config_num, _interface_count, _string_index, \
                              _total_len, _attributes, _power_ma) \
    9u, TUSB_DESC_CONFIGURATION, U16_TO_U8S_LE(_total_len), \
    (_interface_count), (_config_num), (_string_index), \
    (uint8_t)(0x80u | (_attributes)), (uint8_t)((_power_ma) / 2u)

#define TUD_VENDOR_DESC_LEN (9u + 7u + 7u)
#define TUD_VENDOR_DESCRIPTOR(_interface_num, _string_index, _endpoint_out, \
                              _endpoint_in, _endpoint_size) \
    9u, TUSB_DESC_INTERFACE, (_interface_num), 0u, 2u, \
    TUSB_CLASS_VENDOR_SPECIFIC, 0u, 0u, (_string_index), \
    7u, TUSB_DESC_ENDPOINT, (_endpoint_out), TUSB_XFER_BULK, \
    U16_TO_U8S_LE(_endpoint_size), 0u, \
    7u, TUSB_DESC_ENDPOINT, (_endpoint_in), TUSB_XFER_BULK, \
    U16_TO_U8S_LE(_endpoint_size), 0u

#define TUD_BOS_DESC_LEN 5u
#define TUD_BOS_DESCRIPTOR(_total_len, _capability_count) \
    5u, TUSB_DESC_BOS, U16_TO_U8S_LE(_total_len), (_capability_count)

#define TUD_BOS_MICROSOFT_OS_DESC_LEN 28u
#define TUD_BOS_MS_OS_20_UUID \
    0xDFu, 0x60u, 0xDDu, 0xD8u, 0x89u, 0x45u, 0xC7u, 0x4Cu, \
    0x9Cu, 0xD2u, 0x65u, 0x9Du, 0x9Eu, 0x64u, 0x8Au, 0x9Fu
#define TUD_BOS_MS_OS_20_DESCRIPTOR(_descriptor_set_len, _vendor_code) \
    28u, TUSB_DESC_DEVICE_CAPABILITY, DEVICE_CAPABILITY_PLATFORM, 0u, \
    TUD_BOS_MS_OS_20_UUID, U32_TO_U8S_LE(0x06030000u), \
    U16_TO_U8S_LE(_descriptor_set_len), (_vendor_code), 0u

typedef struct __attribute__((packed)) {
    uint8_t bLength;
    uint8_t bDescriptorType;
    uint16_t bcdUSB;
    uint8_t bDeviceClass;
    uint8_t bDeviceSubClass;
    uint8_t bDeviceProtocol;
    uint8_t bMaxPacketSize0;
    uint16_t idVendor;
    uint16_t idProduct;
    uint16_t bcdDevice;
    uint8_t iManufacturer;
    uint8_t iProduct;
    uint8_t iSerialNumber;
    uint8_t bNumConfigurations;
} tusb_desc_device_t;

typedef struct __attribute__((packed)) {
    union {
        struct __attribute__((packed)) {
            uint8_t recipient : 5;
            uint8_t type : 2;
            uint8_t direction : 1;
        } bmRequestType_bit;
        uint8_t bmRequestType;
    };
    uint8_t bRequest;
    uint16_t wValue;
    uint16_t wIndex;
    uint16_t wLength;
} tusb_control_request_t;

bool tud_control_xfer(uint8_t rhport,
                      tusb_control_request_t const *request,
                      void *buffer,
                      uint16_t length);

#endif
