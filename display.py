import uasyncio as asyncio
import time
from machine import Pin, SPI
from st7789_ext import ST7789
from config import (
    LCD_WIDTH, LCD_HEIGHT, LCD_SPI_HOST, LCD_BAUDRATE,
    LCD_SCLK, LCD_MOSI, LCD_MISO, LCD_CS, LCD_DC, LCD_RST, LCD_BL,
)


class Display:
    def __init__(self):
        spi = SPI(LCD_SPI_HOST,
                  baudrate=LCD_BAUDRATE,
                  polarity=0, phase=0,
                  sck=Pin(LCD_SCLK),
                  mosi=Pin(LCD_MOSI),
                  miso=Pin(LCD_MISO))
        # Pass landscape dimensions (480x222) so driver bounds match our coords
        self.drv = ST7789(spi, LCD_HEIGHT, LCD_WIDTH,
                          reset=Pin(LCD_RST, Pin.OUT),
                          dc=Pin(LCD_DC, Pin.OUT),
                          cs=Pin(LCD_CS, Pin.OUT))
        self._st7796_init()
        self.w = LCD_HEIGHT  # 480
        self.h = LCD_WIDTH   # 222
        self.bl = Pin(LCD_BL, Pin.OUT)
        self.bl.on()

        # Colors
        self.BLACK = self.drv.color(0, 0, 0)
        self.WHITE = self.drv.color(255, 255, 255)
        self.CYAN = self.drv.color(0, 200, 200)
        self.GRAY = self.drv.color(120, 120, 120)
        self.GREEN = self.drv.color(0, 220, 80)
        self.YELLOW = self.drv.color(220, 200, 0)
        self.DIM = self.drv.color(80, 80, 80)

        # Track last displayed values for partial updates
        self._last_peers = -1
        self._last_relayed = -1

    def _st7796_init(self):
        """ST7796-specific init sequence (replaces generic ST7789 init)."""
        d = self.drv
        d.xstart = 0
        d.ystart = 49  # 222px panel centered in 320px ST7796 RAM: (320-222)/2=49
        d.inversion = True

        if d.cs:
            d.cs.off()
        d.hard_reset()
        d.soft_reset()
        d.sleep_mode(False)
        time.sleep_ms(120)

        # Enable ST7796 extended command set
        d.write(bytes([0xF0]), bytes([0xC3]))
        d.write(bytes([0xF0]), bytes([0x96]))

        # Color mode: 65K, 16-bit
        d._set_color_mode(0x55)
        time.sleep_ms(50)

        # MADCTL: MV (landscape) | BGR (ST7796 color order)
        # 0x28 = 0x20 (MV) | 0x08 (BGR)
        d.write(bytes([0x36]), bytes([0x28]))

        # Display inversion control
        d.write(bytes([0xB4]), bytes([0x01]))

        # Display function control
        d.write(bytes([0xB6]), bytes([0x80, 0x22, 0x3B]))

        # Adjustment control 3
        d.write(bytes([0xE8]), bytes([0x40, 0x8A, 0x00, 0x00,
                                      0x29, 0x19, 0xA5, 0x33]))

        # Power control
        d.write(bytes([0xC1]), bytes([0x06]))
        d.write(bytes([0xC2]), bytes([0xA7]))
        d.write(bytes([0xC5]), bytes([0x18]))

        # Positive gamma correction
        d.write(bytes([0xE0]), bytes([0xF0, 0x09, 0x0B, 0x06,
                                      0x04, 0x15, 0x2F, 0x54,
                                      0x42, 0x3C, 0x17, 0x14,
                                      0x18, 0x1B]))

        # Negative gamma correction
        d.write(bytes([0xE1]), bytes([0xE0, 0x09, 0x0B, 0x06,
                                      0x04, 0x03, 0x2B, 0x43,
                                      0x42, 0x3B, 0x16, 0x14,
                                      0x17, 0x1B]))

        # Disable extended command set
        d.write(bytes([0xF0]), bytes([0x3C]))
        d.write(bytes([0xF0]), bytes([0x69]))

        # Inversion on (IPS panel)
        d.inversion_mode(True)
        time.sleep_ms(10)

        # Normal display mode on
        d.write(bytes([0x13]))
        time.sleep_ms(10)

        # Fill black
        d.fill(d.color(0, 0, 0))

        # Display on
        d.write(bytes([0x29]))
        time.sleep_ms(100)

    def show_boot_splash(self):
        """Show boot splash screen (landscape 480x222)."""
        d = self.drv
        d.fill(self.BLACK)

        # "BITRELAY" - large centered text (scale=4, each char 32px wide)
        txt = "BITRELAY"
        txt_w = len(txt) * 8 * 4
        x = (self.w - txt_w) // 2
        d.upscaled_text(x, 40, txt, self.CYAN, upscaling=4)

        # "ESP32 BLE MESH" - subtitle (scale=2, each char 16px wide)
        sub = "ESP32 BLE MESH"
        sub_w = len(sub) * 8 * 2
        x = (self.w - sub_w) // 2
        d.upscaled_text(x, 90, sub, self.GRAY, upscaling=2)

        # Cyan accent line
        margin = 60
        d.hline(margin, self.w - margin, 120, self.CYAN)

        # "Syncing time..." at bottom
        msg = "Syncing time..."
        msg_w = len(msg) * 8 * 2
        x = (self.w - msg_w) // 2
        d.upscaled_text(x, 160, msg, self.YELLOW, upscaling=2)

    def show_status(self, peers, relayed, nickname, peer_id):
        """Draw full status screen (landscape 480x222)."""
        d = self.drv
        d.fill(self.BLACK)

        # Header: "BITRELAY"
        d.upscaled_text(10, 8, "BITRELAY", self.CYAN, upscaling=2)

        # Separator line
        d.hline(10, self.w - 10, 30, self.CYAN)

        # Left side: PEERS
        d.upscaled_text(40, 50, "PEERS", self.GRAY, upscaling=2)
        peers_str = "%d" % peers
        # Large number centered under label
        pw = len(peers_str) * 8 * 5
        px = 40 + (len("PEERS") * 16 - pw) // 2
        d.upscaled_text(max(px, 40), 80, peers_str, self.GREEN, upscaling=5)

        # Right side: RELAYED
        rx = 260
        d.upscaled_text(rx, 50, "RELAYED", self.GRAY, upscaling=2)
        rel_str = "%d" % relayed
        rw = len(rel_str) * 8 * 5
        rpx = rx + (len("RELAYED") * 16 - rw) // 2
        d.upscaled_text(max(rpx, rx), 80, rel_str, self.GREEN, upscaling=5)

        # Bottom separator
        d.hline(10, self.w - 10, 170, self.CYAN)

        # Nickname and peer ID
        info = "%s | %s" % (nickname, peer_id[:16])
        d.upscaled_text(10, 185, info, self.DIM, upscaling=2)

    def _update_values(self, peers, relayed):
        """Partial update: only redraw changed numbers."""
        d = self.drv

        if peers != self._last_peers:
            # Clear peers number area and redraw
            d.rect(20, 80, 200, 50, self.BLACK, fill=True)
            peers_str = "%d" % peers
            pw = len(peers_str) * 8 * 5
            px = 40 + (len("PEERS") * 16 - pw) // 2
            d.upscaled_text(max(px, 40), 80, peers_str, self.GREEN, upscaling=5)

        if relayed != self._last_relayed:
            # Clear relayed number area and redraw
            d.rect(240, 80, 220, 50, self.BLACK, fill=True)
            rx = 260
            rel_str = "%d" % relayed
            rw = len(rel_str) * 8 * 5
            rpx = rx + (len("RELAYED") * 16 - rw) // 2
            d.upscaled_text(max(rpx, rx), 80, rel_str, self.GREEN, upscaling=5)

    async def refresh_loop(self, get_status_cb):
        """Coroutine that refreshes the status display every 2 seconds."""
        while True:
            status = get_status_cb()
            peers = status["connections"]
            relayed = status["relayed"]
            if peers != self._last_peers or relayed != self._last_relayed:
                self._update_values(peers, relayed)
                self._last_peers = peers
                self._last_relayed = relayed
            await asyncio.sleep(2)
