import uasyncio as asyncio
import aioble
import bluetooth
import struct

SERVICE_UUID = bluetooth.UUID("F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C")
CHAR_UUID = bluetooth.UUID("A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D")

_char = None


async def run():
    global _char
    service = aioble.Service(SERVICE_UUID)
    _char = aioble.BufferedCharacteristic(
        service, CHAR_UUID,
        read=True, write=True, notify=True,
        max_len=512,
    )
    aioble.register_services(service)
    await asyncio.gather(advertise_task(), read_task())


async def advertise_task():
    while True:
        try:
            conn = await aioble.advertise(
                250_000, name="bitrelay",
                services=[SERVICE_UUID], timeout_ms=None,
            )
            print("[ADV] Connected: %s" % conn.device)
        except Exception as e:
            print("[ADV] Error: %s" % e)
            await asyncio.sleep(1)


async def read_task():
    print("[READ] Waiting for writes...")
    while True:
        try:
            result = await _char.written()
            if isinstance(result, tuple):
                conn, data = result
            else:
                conn = result
                data = _char.read()
            if data:
                raw = bytes(data)
                print("=== RAW PACKET: %d bytes ===" % len(raw))
                for i in range(0, len(raw), 32):
                    chunk = raw[i:i + 32]
                    print("  %03d: %s" % (i, chunk.hex()))
                if len(raw) >= 14:
                    ver = raw[0]
                    mtype = raw[1]
                    ttl = raw[2]
                    ts = struct.unpack_from('>Q', raw, 3)[0]
                    flags = raw[11]
                    plen = struct.unpack_from('>H', raw, 12)[0]
                    print("  ver=%d type=0x%02x ttl=%d flags=0x%02x payload_len=%d" % (
                        ver, mtype, ttl, flags, plen))
                    print("  sender_id: %s" % raw[14:22].hex())
                    offset = 22
                    if flags & 0x01:
                        print("  recipient: %s" % raw[offset:offset + 8].hex())
                        offset += 8
                    print("  payload @ offset %d: %s" % (
                        offset, raw[offset:offset + min(plen, 60)].hex()))
                    last = raw[-1]
                    if 0 < last <= len(raw):
                        start = len(raw) - last
                        ok = all(raw[start + j] == last for j in range(last))
                        print("  PKCS7: last=0x%02x pad=%d valid=%s unpadded_len=%d" % (
                            last, last, ok, start))
                print("===")
        except Exception as e:
            print("[READ] Error: %s" % e)
            await asyncio.sleep_ms(100)


asyncio.run(run())
