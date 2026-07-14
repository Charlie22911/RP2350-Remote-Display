/*****************************************************************************
* | File      	:   FT6336U.c
* | Author      :   Waveshare Team
* | Function    :   FT6336U Interface Functions
* | Info        :
*----------------
* |	This version:   V1.0
* | Date        :   2025-03-20
* | Info        :   
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of theex Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
******************************************************************************/
#include "FT6336U.h"
#include "DEV_Config.h"
#include <inttypes.h>
#include <string.h>

FT6336U_Struct FT6336U;

/******************************************************************************
function :	Send one byte of data to the specified register of FT6336U
parameter:
******************************************************************************/
static bool FT6336U_I2C_Write_Byte(uint8_t reg, uint8_t value) {
    return DEV_I2C_Write_Byte(FT6336U_I2C_ADDR, reg, value);
}

/******************************************************************************
function :	Read one byte of data from the specified register of FT6336U
parameter:
******************************************************************************/
static bool FT6336U_I2C_Read_Byte(uint8_t reg, uint8_t *value) {
    return DEV_I2C_Read_Byte(FT6336U_I2C_ADDR, reg, value);
}

/******************************************************************************
function :	Read n byte of data from the specified register of FT6336U
parameter:
******************************************************************************/
static bool FT6336U_I2C_Read_nByte(uint8_t reg, uint8_t *pData, uint32_t Len) {
    return DEV_I2C_Read_nByte(FT6336U_I2C_ADDR, reg, pData, Len);
}

/******************************************************************************
function :	Reset the FT6336U
parameter:
******************************************************************************/
void FT6336U_Reset() {
    gpio_put(Touch_RST_PIN, 1);
    sleep_ms(10);
    gpio_put(Touch_RST_PIN, 0);
    sleep_ms(10);
    gpio_put(Touch_RST_PIN, 1);
    sleep_ms(300);
}

/******************************************************************************
function :	Initialize the FT6336U
parameter:
        mode    ：  FT6336U_Point_Mode
                    FT6336U_Gesture_Mode
******************************************************************************/
bool FT6336U_Init(uint8_t mode) {
    // FT6336U Reset
    FT6336U_Reset();

    memset(&FT6336U, 0, sizeof(FT6336U));
    FT6336U.mode = mode;
    int32_t id = FT6336U_ReadID();
    printf("FT6336URegister_WhoAmI = %" PRId32 "\n", id);
    if(id != 0x64) { 
        printf("Invalid device ID: 0x%" PRIx32 "\n", (uint32_t)id);
        return false;
    }
    if (mode == FT6336U_Gesture_Mode &&
        !FT6336U_I2C_Write_Byte(FT6336U_ADDR_GESTURE_EN, FT6336U_ADDR_GESTURE_ENABLE)) {
        printf("Unable to enable FT6336U gesture mode\n");
        return false;
    }
    printf("FT6336U initialized successfully\n");
    return true;
}

/******************************************************************************
function :	Read the ID of FT6336U
parameter:
******************************************************************************/
uint16_t FT6336U_ReadID() {
    uint8_t id = 0u;
    return FT6336U_I2C_Read_Byte(FT6336U_ADDR_CHIP_ID, &id) ? id : UINT16_MAX;
}

/******************************************************************************
function :	Read the current status of FT6336U
parameter:
******************************************************************************/
uint16_t FT6336U_ReadState(Value_Information info) {
    uint8_t buf[2];
    
    switch(info) {
        case FT6336U_GESTURE_ID:
            return FT6336U_I2C_Read_Byte(FT6336U_ADDR_GESTURE_OUTPUT, &buf[0]) ? buf[0] : UINT16_MAX;

        case FT6336U_FINGER_NUMBER:
            return FT6336U_I2C_Read_Byte(FT6336U_ADDR_TD_STATUS, &buf[0]) ? buf[0] : UINT16_MAX;

        case FT6336U_TOUCH1_X:
            if (!FT6336U_I2C_Read_nByte(FT6336U_ADDR_TOUCH1_X, buf, 2u)) return UINT16_MAX;
            return ((int16_t)(buf[0] & 0x0F) << 8) | buf[1];
            
        case FT6336U_TOUCH1_Y:
            if (!FT6336U_I2C_Read_nByte(FT6336U_ADDR_TOUCH1_Y, buf, 2u)) return UINT16_MAX;
            return ((int16_t)(buf[0] & 0x0F) << 8) | buf[1];

        case FT6336U_TOUCH2_X:
            if (!FT6336U_I2C_Read_nByte(FT6336U_ADDR_TOUCH2_X, buf, 2u)) return UINT16_MAX;
            return ((int16_t)(buf[0] & 0x0F) << 8) | buf[1];
            
        case FT6336U_TOUCH2_Y:
            if (!FT6336U_I2C_Read_nByte(FT6336U_ADDR_TOUCH2_Y, buf, 2u)) return UINT16_MAX;
            return ((int16_t)(buf[0] & 0x0F) << 8) | buf[1];
    }
    return -1;
}

/******************************************************************************
function :	Get the coordinate value of FT6336U contact
parameter:
******************************************************************************/
bool FT6336U_Get_Point(void) {
    /*
     * The controller stores TD_STATUS plus touch-one coordinates in one
     * consecutive register range.  Read it in a single I2C transaction so
     * touch polling does not perform three stop/start transactions per sample.
     * Touch two is fetched only when the controller reports a second contact.
     */
    uint8_t first[5] = {0};
    if (!FT6336U_I2C_Read_nByte(FT6336U_ADDR_TD_STATUS, first, sizeof(first))) {
        return false;
    }

    uint8_t fingers = (uint8_t)(first[0] & 0x0Fu);
    if (fingers > 2u) {
        fingers = 2u;
    }

    if (fingers != 0u) {
        FT6336U.touch1_x = (uint16_t)(((uint16_t)(first[1] & 0x0Fu) << 8u) | first[2]);
        FT6336U.touch1_y = (uint16_t)(((uint16_t)(first[3] & 0x0Fu) << 8u) | first[4]);
    }

    if (fingers == 2u) {
        uint8_t second[4] = {0};
        if (!FT6336U_I2C_Read_nByte(FT6336U_ADDR_TOUCH2_X, second, sizeof(second))) {
            return false;
        }
        FT6336U.touch2_x = (uint16_t)(((uint16_t)(second[0] & 0x0Fu) << 8u) | second[1]);
        FT6336U.touch2_y = (uint16_t)(((uint16_t)(second[2] & 0x0Fu) << 8u) | second[3]);
    } else {
        FT6336U.touch2_x = 0u;
        FT6336U.touch2_y = 0u;
    }

    FT6336U.touch_num = fingers;
    return true;
}

/******************************************************************************
function :	Get the coordinate value of FT6336U contact
parameter:
******************************************************************************/
uint8_t FT6336U_Get_Gesture() {
    uint8_t gesture = FT6336U_ReadState(FT6336U_GESTURE_ID);
    return gesture;
}

