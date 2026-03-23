"""Minimal ST7796 display test for T-Display-S3 Pro."""
import time
from machine import Pin, SPI

# Pins from LilyGO pinmap
spi = SPI(2, baudrate=40000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(17), miso=Pin(8))
cs = Pin(6, Pin.OUT)
dc = Pin(9, Pin.OUT)
rst = Pin(47, Pin.OUT)
bl = Pin(48, Pin.OUT)

def cmd(c, data=None):
    cs.off()
    dc.off()
    spi.write(bytes([c]))
    if data:
        dc.on()
        spi.write(bytes(data))
    cs.on()

def fill(color_hi, color_lo):
    """Fill entire 320x480 RAM with a color."""
    cs.off()
    dc.off()
    spi.write(bytes([0x2A]))  # CASET
    dc.on()
    spi.write(bytes([0x00, 0x00, 0x01, 0x3F]))  # 0-319
    dc.off()
    spi.write(bytes([0x2B]))  # RASET
    dc.on()
    spi.write(bytes([0x00, 0x00, 0x01, 0xDF]))  # 0-479
    dc.off()
    spi.write(bytes([0x2C]))  # RAMWR
    dc.on()
    row = bytes([color_hi, color_lo] * 320)
    for _ in range(480):
        spi.write(row)
    cs.on()

print("[test] Hard reset...")
rst.on()
time.sleep_ms(50)
rst.off()
time.sleep_ms(50)
rst.on()
time.sleep_ms(150)

print("[test] Init sequence...")
cmd(0x01)  # SWRESET
time.sleep_ms(150)
cmd(0x11)  # SLPOUT
time.sleep_ms(120)

# Enable extended commands
cmd(0xF0, [0xC3])
cmd(0xF0, [0x96])

cmd(0x3A, [0x55])  # COLMOD 16-bit
time.sleep_ms(50)
cmd(0x36, [0x48])  # MADCTL: MX | BGR (portrait)

cmd(0xB4, [0x01])  # Column inversion
cmd(0xB6, [0x80, 0x02, 0x3B])  # Display function control
cmd(0xE8, [0x40, 0x8A, 0x00, 0x00, 0x29, 0x19, 0xA5, 0x33])
cmd(0xC1, [0x06])
cmd(0xC2, [0xA7])
cmd(0xC5, [0x18])

# Gamma
cmd(0xE0, [0xF0, 0x09, 0x0B, 0x06, 0x04, 0x15, 0x2F, 0x54,
           0x42, 0x3C, 0x17, 0x14, 0x18, 0x1B])
cmd(0xE1, [0xE0, 0x09, 0x0B, 0x06, 0x04, 0x03, 0x2B, 0x43,
           0x42, 0x3B, 0x16, 0x14, 0x17, 0x1B])

# Disable extended commands
cmd(0xF0, [0x3C])
cmd(0xF0, [0x69])

cmd(0x21)  # INVON (IPS)
time.sleep_ms(10)
cmd(0x13)  # NORON
time.sleep_ms(10)
cmd(0x29)  # DISPON
time.sleep_ms(100)

print("[test] Backlight on...")
bl.on()

print("[test] Fill RED...")
fill(0xF8, 0x00)  # Red in RGB565
time.sleep(2)

print("[test] Fill GREEN...")
fill(0x07, 0xE0)  # Green in RGB565
time.sleep(2)

print("[test] Fill BLUE...")
fill(0x00, 0x1F)  # Blue in RGB565
time.sleep(2)

print("[test] Fill WHITE...")
fill(0xFF, 0xFF)  # White
time.sleep(2)

print("[test] Done.")
