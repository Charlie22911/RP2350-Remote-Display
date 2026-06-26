/*****************************************************************************
* | File      	:   AMOLED_2in41.g_dma_tx_config
* | Author      :   Waveshare Team
* | Function    :   AMOLED Interface Functions
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
#include <stddef.h>

#include "DEV_Config.h"
#include "AMOLED_2in41.h"

AMOLED_2IN41_ATTRIBUTES AMOLED_2IN41;

/********************************************************************************
function:	Sets the start position and size of the display area
parameter:
        g_qspi    ：  g_qspi structure
		Xstart 	:   X direction Start coordinates
		Ystart  :   Y direction Start coordinates
		Xend    :   X direction end coordinates
		Yend    :   Y direction end coordinates
********************************************************************************/
void AMOLED_2IN41_SetWindows(uint32_t Xstart, uint32_t Ystart, uint32_t Xend, uint32_t Yend){
    // Xstart=Xstart+20;
	// Xend=Xend+20;

    Xstart=Xstart+16;
	Xend=Xend+16;

    QSPI_Select(g_qspi); 
    QSPI_REGISTER_Write(g_qspi, 0x2a); 
    QSPI_DATA_Write(g_qspi, Xstart>>8);
    QSPI_DATA_Write(g_qspi, Xstart&0xff);
    QSPI_DATA_Write(g_qspi, (Xend-1)>>8);
    QSPI_DATA_Write(g_qspi, (Xend-1)&0xff);
    QSPI_Deselect(g_qspi); 
    
    QSPI_Select(g_qspi); 
    QSPI_REGISTER_Write(g_qspi, 0x2b);
    QSPI_DATA_Write(g_qspi, Ystart>>8);
    QSPI_DATA_Write(g_qspi, Ystart&0xff);
    QSPI_DATA_Write(g_qspi, (Yend-1)>>8);
    QSPI_DATA_Write(g_qspi, (Yend-1)&0xff);
    QSPI_Deselect(g_qspi); 
    
    QSPI_Select(g_qspi); 
    QSPI_REGISTER_Write(g_qspi, 0x2c);
    QSPI_Deselect(g_qspi); 
    // WAIT_TIME();
}

/******************************************************************************
function :	Initialize the lcd register
parameter:
        g_qspi    ：  g_qspi structure
******************************************************************************/
static void AMOLED_2IN41_InitReg(){
    QSPI_Select(g_qspi); 
    QSPI_REGISTER_Write(g_qspi, 0x11);
    sleep_ms(120);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x44);
    QSPI_DATA_Write(g_qspi, 0x01);
    QSPI_DATA_Write(g_qspi, 0xD1); 
    QSPI_Deselect(g_qspi);
    
    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0xFE);
    QSPI_DATA_Write(g_qspi, 0x20);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x63); 
    QSPI_DATA_Write(g_qspi, 0xFF);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x26); 
    QSPI_DATA_Write(g_qspi, 0x0A);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x24); 
    QSPI_DATA_Write(g_qspi, 0x80);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0xFE); 
    QSPI_DATA_Write(g_qspi, 0x00);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x3A);
    QSPI_DATA_Write(g_qspi, 0x55);  
    QSPI_Deselect(g_qspi);
    
    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0xC4); 
    QSPI_DATA_Write(g_qspi, 0x80); 
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0xC2);   
    QSPI_DATA_Write(g_qspi, 0x00);
    QSPI_Deselect(g_qspi);

    sleep_ms(10);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x35);   
    QSPI_DATA_Write(g_qspi, 0x00);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x51);   
    QSPI_DATA_Write(g_qspi, 0x00);
    QSPI_Deselect(g_qspi);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x29);  
    QSPI_Deselect(g_qspi);

    sleep_ms(10);

    QSPI_Select(g_qspi);
    QSPI_REGISTER_Write(g_qspi, 0x51);   
    QSPI_DATA_Write(g_qspi, 0xFF);
    QSPI_Deselect(g_qspi);
    
    sleep_ms(10);
}

/********************************************************************************
function :	Reset the lcd
parameter:
        qspi_bus  ：  QSPI structure
********************************************************************************/
static void AMOLED_2IN41_Reset(pio_qspi_t qspi_bus){
    gpio_put(qspi_bus.pin_rst, 1);
    DEV_Delay_ms(50);
    gpio_put(qspi_bus.pin_rst, 0);
    DEV_Delay_ms(50);
    gpio_put(qspi_bus.pin_rst, 1);
    DEV_Delay_ms(300);
}

/********************************************************************************
function :	Initialize the lcd
parameter:
********************************************************************************/
void AMOLED_2IN41_Init()
{
    //Hardware reset
    AMOLED_2IN41_Reset(g_qspi);
    
    //Set the initialization register
    AMOLED_2IN41_InitReg(g_qspi);

    AMOLED_2IN41.HEIGHT	 = AMOLED_2IN41_HEIGHT;
    AMOLED_2IN41.WIDTH   = AMOLED_2IN41_WIDTH;
}

/******************************************************************************
function :	Set AMOLED Brightness
parameter:
******************************************************************************/
void AMOLED_2IN41_SetBrightness(uint8_t brightness){
    if(brightness > 100) brightness = 100;
    brightness = brightness * 255 / 100;

    // QSPI_1Wrie_Mode(&g_qspi);
    QSPI_Select(g_qspi); 
    QSPI_REGISTER_Write(g_qspi, 0x51);
    QSPI_DATA_Write(g_qspi, brightness);
    QSPI_Deselect(g_qspi);
}

/******************************************************************************
function :	Clear screen
parameter:
******************************************************************************/
void AMOLED_2IN41_Clear(UWORD Color) {
    // Color data
    UWORD image[AMOLED_2IN41.HEIGHT];
    for (uint32_t row = 0u; row < AMOLED_2IN41.HEIGHT; ++row) {
        image[row] = (UWORD)((Color >> 8u) | ((Color & 0xffu) << 8u));
    }
	UBYTE *partial_image = (UBYTE *)(image);

    // Send command in one-line mode
    // QSPI_1Wrie_Mode(&g_qspi);
    AMOLED_2IN41_SetWindows(0,0,AMOLED_2IN41.WIDTH,AMOLED_2IN41.HEIGHT);
    QSPI_Select(g_qspi);
    QSPI_Pixel_Write(g_qspi,0x2c);

    // Four-wire mode sends RGB data
    // QSPI_4Wrie_Mode(&g_qspi);
    channel_config_set_dreq(&g_dma_tx_config, pio_get_dreq(g_qspi.pio, g_qspi.sm, true));
    for (uint32_t row = 0u; row < AMOLED_2IN41.HEIGHT; ++row) {
        dma_channel_configure(g_dma_tx_channel, 
                            &g_dma_tx_config,
                            &g_qspi.pio->txf[g_qspi.sm],  // Destination pointer (PIO TX FIFO)
                            partial_image,            // Source pointer (data buffer)
                            AMOLED_2IN41.WIDTH*2,      // Data length (unit: number of transmissions)
                            true);                    // Start transferring immediately
        
        // Waiting for DMA transfer to complete
        while(dma_channel_is_busy(g_dma_tx_channel));
    }

    QSPI_Deselect(g_qspi);
}

/******************************************************************************
function :	Send data to AMOLED to complete full screen refresh
parameter:
        Image   ：  Image data
******************************************************************************/
void AMOLED_2IN41_Display(UWORD *Image)
{
    // Send command in one-line mode
    // QSPI_1Wrie_Mode(&g_qspi);
    AMOLED_2IN41_SetWindows(0,0,AMOLED_2IN41.WIDTH,AMOLED_2IN41.HEIGHT);
    QSPI_Select(g_qspi);
    QSPI_Pixel_Write(g_qspi,0x2c);

    // Four-wire mode sends RGB data
    // QSPI_4Wrie_Mode(&g_qspi);
    channel_config_set_dreq(&g_dma_tx_config, pio_get_dreq(g_qspi.pio, g_qspi.sm, true));
    dma_channel_configure(g_dma_tx_channel, 
                        &g_dma_tx_config,
                        &g_qspi.pio->txf[g_qspi.sm],  // Destination pointer (PIO TX FIFO)
                        (UBYTE *)Image,           // Source pointer (data buffer)
                        AMOLED_2IN41.WIDTH*AMOLED_2IN41.HEIGHT*2,   // Data length (unit: number of transmissions)
                        true);                    // Start transferring immediately
    
    // Waiting for DMA transfer to complete
    while(dma_channel_is_busy(g_dma_tx_channel));
    QSPI_Deselect(g_qspi);             
}

/******************************************************************************
function :	Send data to AMOLED to complete partial refresh
parameter:
		Xstart 	:   X direction Start coordinates
		Ystart  :   Y direction Start coordinates
		Xend    :   X direction end coordinates
		Yend    :   Y direction end coordinates
        Image   ：  Image data
******************************************************************************/
void AMOLED_2IN41_DisplayWindows(uint32_t Xstart, uint32_t Ystart, uint32_t Xend, uint32_t Yend, UWORD *Image) {
    // Send command in one-line mode
    // QSPI_1Wrie_Mode(&g_qspi);
    AMOLED_2IN41_SetWindows(Xstart, Ystart, Xend, Yend);
    QSPI_Select(g_qspi);
    QSPI_Pixel_Write(g_qspi, 0x2c);

    // Four-wire mode sends RGB data
    // QSPI_4Wrie_Mode(&g_qspi);
    channel_config_set_dreq(&g_dma_tx_config, pio_get_dreq(g_qspi.pio, g_qspi.sm, true));

    uint32_t pixel_offset;
    UBYTE *partial_image;
    for (uint32_t row = Ystart; row < Yend; ++row) {
        pixel_offset = (row * AMOLED_2IN41.WIDTH + Xstart) * 2u;
        partial_image = (UBYTE *)Image + pixel_offset;

        dma_channel_configure(g_dma_tx_channel, 
                            &g_dma_tx_config,
                            &g_qspi.pio->txf[g_qspi.sm],  // Destination pointer (PIO TX FIFO)
                            partial_image,            // Source pointer (data buffer)
                            (Xend-Xstart)*2,          // Data length (unit: number of transmissions)
                            true);                    // Start transferring immediately

        // Waiting for DMA transfer to complete
        while(dma_channel_is_busy(g_dma_tx_channel));
    }

    QSPI_Deselect(g_qspi);
}

typedef enum {
    AMOLED_2IN41_ASYNC_IDLE = 0,
    AMOLED_2IN41_ASYNC_DMA = 1,
    AMOLED_2IN41_ASYNC_FIFO = 2,
} amoled_async_phase_t;

static amoled_async_phase_t async_phase;
static absolute_time_t async_dma_deadline;
static absolute_time_t async_fifo_deadline;

static void AMOLED_2IN41_RecoverTransport(void)
{
    dma_channel_abort(g_dma_tx_channel);
    pio_sm_set_enabled(g_qspi.pio, g_qspi.sm, false);
    pio_sm_clear_fifos(g_qspi.pio, g_qspi.sm);
    pio_sm_restart(g_qspi.pio, g_qspi.sm);
    pio_sm_set_enabled(g_qspi.pio, g_qspi.sm, true);
    gpio_put(g_qspi.pin_cs, 1);
    async_phase = AMOLED_2IN41_ASYNC_IDLE;
}

bool AMOLED_2IN41_TransferActive(void)
{
    return async_phase != AMOLED_2IN41_ASYNC_IDLE;
}

void AMOLED_2IN41_CancelTransfer(void)
{
    if (AMOLED_2IN41_TransferActive() || dma_channel_is_busy(g_dma_tx_channel)) {
        AMOLED_2IN41_RecoverTransport();
    }
}

bool AMOLED_2IN41_BeginFullWidthRows(uint32_t Ystart, uint32_t Yend, const UWORD *Image)
{
    const uint32_t width = AMOLED_2IN41.WIDTH;
    const uint32_t height = AMOLED_2IN41.HEIGHT;

    if (AMOLED_2IN41_TransferActive() || dma_channel_is_busy(g_dma_tx_channel) ||
        Image == NULL || Ystart >= Yend || Yend > height || width == 0u) {
        return false;
    }

    AMOLED_2IN41_SetWindows(0u, Ystart, width, Yend);
    QSPI_Select(g_qspi);
    QSPI_Pixel_Write(g_qspi, 0x2c);

    channel_config_set_dreq(&g_dma_tx_config, pio_get_dreq(g_qspi.pio, g_qspi.sm, true));
    const uint32_t source_offset = Ystart * width;
    const uint32_t byte_count = (Yend - Ystart) * width * sizeof(UWORD);

    dma_channel_configure(g_dma_tx_channel,
                          &g_dma_tx_config,
                          &g_qspi.pio->txf[g_qspi.sm],
                          ((const UBYTE *)Image) + source_offset * sizeof(UWORD),
                          byte_count,
                          true);

    async_phase = AMOLED_2IN41_ASYNC_DMA;
    async_dma_deadline = make_timeout_time_us(250000u);
    return true;
}

AMOLED_2IN41_TRANSFER_STATUS AMOLED_2IN41_PollTransfer(void)
{
    if (async_phase == AMOLED_2IN41_ASYNC_IDLE) {
        return AMOLED_2IN41_TRANSFER_IDLE;
    }

    if (async_phase == AMOLED_2IN41_ASYNC_DMA) {
        if (dma_channel_is_busy(g_dma_tx_channel)) {
            if (time_reached(async_dma_deadline)) {
                AMOLED_2IN41_RecoverTransport();
                return AMOLED_2IN41_TRANSFER_ERROR;
            }
            return AMOLED_2IN41_TRANSFER_ACTIVE;
        }
        async_phase = AMOLED_2IN41_ASYNC_FIFO;
        async_fifo_deadline = make_timeout_time_us(20000u);
    }

    if (async_phase == AMOLED_2IN41_ASYNC_FIFO) {
        if (!pio_sm_is_tx_fifo_empty(g_qspi.pio, g_qspi.sm)) {
            if (time_reached(async_fifo_deadline)) {
                AMOLED_2IN41_RecoverTransport();
                return AMOLED_2IN41_TRANSFER_ERROR;
            }
            return AMOLED_2IN41_TRANSFER_ACTIVE;
        }

        busy_wait_us_32(2u);
        gpio_put(g_qspi.pin_cs, 1);
        async_phase = AMOLED_2IN41_ASYNC_IDLE;
        return AMOLED_2IN41_TRANSFER_COMPLETE;
    }

    AMOLED_2IN41_RecoverTransport();
    return AMOLED_2IN41_TRANSFER_ERROR;
}

bool AMOLED_2IN41_DisplayFullWidthRows(uint32_t Ystart, uint32_t Yend, const UWORD *Image)
{
    if (!AMOLED_2IN41_BeginFullWidthRows(Ystart, Yend, Image)) {
        return false;
    }

    while (true) {
        const AMOLED_2IN41_TRANSFER_STATUS status = AMOLED_2IN41_PollTransfer();
        if (status == AMOLED_2IN41_TRANSFER_COMPLETE) {
            return true;
        }
        if (status == AMOLED_2IN41_TRANSFER_ERROR || status == AMOLED_2IN41_TRANSFER_IDLE) {
            return false;
        }
        tight_loop_contents();
    }
}

