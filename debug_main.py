import uasyncio as asyncio
import aioble
import bluetooth
import sys

SERVICE_UUID = bluetooth.UUID("F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C")
CHAR_UUID = bluetooth.UUID("A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D")
SERVICE_BYTES = bytes(SERVICE_UUID)

from identity import Identity
from protocol import decode_packet, decode_message_payload, encode_packet, encode_message_payload, generate_msg_id, create_fragments
from config import MSG_ANNOUNCE, MSG_MESSAGE, MSG_LEAVE, MSG_FRAGMENT, MESSAGE_TTL, BROADCAST_RECIPIENT

identity = Identity()
identity.load_or_create()
print("Peer ID: %s  Nickname: %s" % (identity.peer_id_hex, identity.nickname))

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

    await asyncio.gather(
        advertise_task(),
        read_writes_task(),
        scan_and_connect_task(),
        send_announce_task(),
    )


async def advertise_task():
    print("[ADV] Starting advertiser...")
    while True:
        try:
            conn = await aioble.advertise(
                250_000, name="bitrelay",
                services=[SERVICE_UUID],
                timeout_ms=30000,
            )
            print("[ADV] Client connected: %s" % conn.device)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print("[ADV] Error: %s" % e)
            await asyncio.sleep(1)


async def read_writes_task():
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
                print("[READ] Got %d bytes from %s" % (len(data), conn.device))
                process_packet(bytes(data), "server")
        except Exception as e:
            print("[READ] Error: %s" % e)
            await asyncio.sleep_ms(100)


async def scan_and_connect_task():
    await asyncio.sleep(2)
    print("[SCAN] Starting scanner...")
    connected_addrs = set()
    while True:
        try:
            target = None
            async with aioble.scan(5000, active=True, interval_us=30000, window_us=30000) as scanner:
                async for result in scanner:
                    for svc in result.services():
                        if bytes(svc) == SERVICE_BYTES:
                            addr = str(result.device)
                            if addr not in connected_addrs:
                                target = result
                            break
                    if target:
                        break

            if not target:
                await asyncio.sleep(5)
                continue

            dev = target.device
            addr = str(dev)
            print("[SCAN] Found peer %s RSSI=%d, connecting..." % (addr, target.rssi))

            try:
                conn = await dev.connect(timeout_ms=10000)
                print("[CONN] Connected to %s" % addr)
            except Exception as e:
                print("[CONN] Connect failed: %s" % e)
                await asyncio.sleep(5)
                continue

            connected_addrs.add(addr)
            try:
                await conn.exchange_mtu(512)
            except Exception as e:
                print("[CONN] MTU: %s" % e)

            try:
                svc = await conn.service(SERVICE_UUID)
                ch = await svc.characteristic(CHAR_UUID)
                await ch.subscribe(notify=True)
                print("[CONN] Subscribed to notifications")
            except Exception as e:
                print("[CONN] Service discovery failed: %s" % e)
                connected_addrs.discard(addr)
                conn.disconnect()
                await asyncio.sleep(5)
                continue

            while conn.is_connected():
                try:
                    data = await ch.notified(timeout_ms=5000)
                    if data:
                        print("[NOTIFY] Got %d bytes" % len(data))
                        process_packet(bytes(data), "client")
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    print("[NOTIFY] Error: %s" % e)
                    break

            connected_addrs.discard(addr)
            print("[CONN] Disconnected from %s" % addr)
            await asyncio.sleep(5)

        except Exception as e:
            print("[SCAN] Error: %s" % e)
            await asyncio.sleep(5)


async def send_announce_task():
    await asyncio.sleep(3)
    while True:
        payload = identity.encode_announce_tlv()
        raw = encode_packet(
            msg_type=MSG_ANNOUNCE,
            ttl=MESSAGE_TTL,
            sender_id=identity.peer_id,
            payload=payload,
        )
        print("[SEND] Broadcasting ANNOUNCE (%d bytes)" % len(raw))
        # Notify all server-side connections
        try:
            _char.notify(None, raw)
        except Exception:
            pass
        await asyncio.sleep(60)


def process_packet(raw, source):
    pkt = decode_packet(raw)
    if pkt is None:
        print("  [DECODE] Failed to decode %d bytes" % len(raw))
        print("  [DECODE] First 30 bytes: %s" % raw[:30].hex())
        return

    type_names = {MSG_ANNOUNCE: "ANNOUNCE", MSG_MESSAGE: "MESSAGE", MSG_LEAVE: "LEAVE", MSG_FRAGMENT: "FRAGMENT"}
    type_name = type_names.get(pkt["type"], "0x%02x" % pkt["type"])
    sender_hex = ''.join('%02x' % b for b in pkt["sender_id"])
    print("  [PKT] type=%s ttl=%d sender=%s payload=%d bytes (via %s)" % (
        type_name, pkt["ttl"], sender_hex[:16], len(pkt["payload"]), source))

    if pkt["type"] == MSG_ANNOUNCE:
        announce = identity.decode_announce_tlv(pkt["payload"])
        if announce:
            print("  [ANNOUNCE] nickname='%s' noise_key=%s" % (
                announce["nickname"], ''.join('%02x' % b for b in announce["noise_pubkey"][:8])))
        else:
            print("  [ANNOUNCE] TLV decode failed! payload[0:20]=%s" % pkt["payload"][:20].hex())
    elif pkt["type"] == MSG_MESSAGE:
        msg = decode_message_payload(pkt["payload"])
        if msg:
            print("  [MSG] from='%s' content='%s'" % (msg["sender"], msg["content"]))
        else:
            print("  [MSG] payload decode failed!")


asyncio.run(run())
