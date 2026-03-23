# This code is originally from https://github.com/devbis/st7789py_mpy
# It's under the MIT license as well.
#
# Rewritten by Salvatore Sanfilippo.
#
# Copyright (C) 2024 Salvatore Sanfilippo <antirez@gmail.com>
# All Rights Reserved
# All the changes released under the MIT license as the original code.

import st7789_base, framebuf, struct

class ST7789(st7789_base.ST7789_base):
    def line(self, x0, y0, x1, y1, color):
        if y0 == y1: return self.hline(x0, x1, y0, color)
        if x0 == x1: return self.vline(y0, y1, x0, color)

        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy

        while True:
            self.pixel(x0, y0, color)
            if x0 == x1 and y0 == y1: break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def circle(self, x, y, radius, color, fill=False):
        f = 1 - radius
        dx = 1
        dy = -2 * radius
        x0 = 0
        y0 = radius

        if fill:
            self.hline(x - radius, x + radius, y, color)
        else:
            self.pixel(x - radius, y, color)
            self.pixel(x + radius, y, color)

        while x0 < y0:
            if f >= 0:
                y0 -= 1
                dy += 2
                f += dy
            x0 += 1
            dx += 2
            f += dx

            if fill:
                self.hline(x - x0, x + x0, y + y0, color)
                self.hline(x - x0, x + x0, y - y0, color)
                self.hline(x - y0, x + y0, y + x0, color)
                self.hline(x - y0, x + y0, y - x0, color)
            else:
                self.pixel(x + x0, y + y0, color)
                self.pixel(x - x0, y + y0, color)
                self.pixel(x + x0, y - y0, color)
                self.pixel(x - x0, y - y0, color)
                self.pixel(x + y0, y + x0, color)
                self.pixel(x - y0, y + x0, color)
                self.pixel(x + y0, y - x0, color)
                self.pixel(x - y0, y - x0, color)

    def fill_triangle(self, x0, y0, x1, y1, x2, y2, color):
        if y0 > y1: x0, y0, x1, y1 = x1, y1, x0, y0
        if y0 > y2: x0, y0, x2, y2 = x2, y2, x0, y0
        if y1 > y2: x1, y1, x2, y2 = x2, y2, x1, y1

        inv_slope1 = (x1 - x0) / (y1 - y0) if y1 - y0 != 0 else 0
        inv_slope2 = (x2 - x0) / (y2 - y0) if y2 - y0 != 0 else 0
        inv_slope3 = (x2 - x1) / (y2 - y1) if y2 - y1 != 0 else 0

        x_start, x_end = x0, x0

        for y in range(y0, y1 + 1):
            self.hline(int(x_start), int(x_end), y, color)
            x_start += inv_slope1
            x_end += inv_slope2

        x_start = x1

        for y in range(y1 + 1, y2 + 1):
            self.hline(int(x_start), int(x_end), y, color)
            x_start += inv_slope3
            x_end += inv_slope2

    def triangle(self, x0, y0, x1, y1, x2, y2, color, fill=False):
        if fill:
            return self.fill_triangle(x0, y0, x1, y1, x2, y2, color)
        else:
            self.line(x0, y0, x1, y1, color)
            self.line(x1, y1, x2, y2, color)
            self.line(x2, y2, x0, y0, color)

    def upscaled_char(self, x, y, char, fgcolor, bgcolor, upscaling):
        bitmap = bytearray(8)
        fb = framebuf.FrameBuffer(bitmap, 8, 8, framebuf.MONO_HMSB)
        fb.text(char, 0, 0, fgcolor[1]<<8|fgcolor[0])
        charsize = 8*upscaling
        if bgcolor: self.rect(x, y, charsize, charsize, bgcolor, fill=True)
        for py in range(8):
            for px in range(8):
                if not (bitmap[py] & (1<<px)): continue
                if upscaling > 1:
                    self.rect(x+px*upscaling, y+py*upscaling, upscaling, upscaling, fgcolor, fill=True)
                else:
                    self.pixel(x+px, y+py, fgcolor)

    def upscaled_text(self, x, y, txt, fgcolor, *, bgcolor=None, upscaling=2):
        for i in range(len(txt)):
            self.upscaled_char(x+i*(8*upscaling), y, txt[i], fgcolor, bgcolor, upscaling)

    def image(self, x, y, filename):
        try:
            f = open(filename, "rb")
        except:
            print("Warning: file not found displaying image:", filename)
            return
        hdr = f.read(4)
        w, h = struct.unpack(">HH", hdr)
        self.set_window(x, y, x+w-1, y+h-1)
        buf = bytearray(256)
        nocopy = memoryview(buf)
        while True:
            nread = f.readinto(buf)
            if nread == 0: return
            self.write(None, nocopy[:nread])
