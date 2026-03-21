import uasyncio as asyncio
import aioble
import bluetooth
import struct
import time

from identity import Identity
from protocol import encode_packet, decode_packet
from config import MSG_MESSAGE, MESSAGE_TTL, BROADCAST_RECIPIENT

SERVICE_UUID = bluetooth.UUID("F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C")
CHAR_UUID = bluetooth.UUID("A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D")

identity = Identity()
identity.load_or_create()
print("Peer ID: %s  Nickname: %s" % (identity.peer_id_hex, identity.nickname))

_char = None
_conns = []


async def run():
    global _char
    service = aioble.Service(SERVICE_UUID)
    _char = aioble.BufferedCharacteristic(
        service, CHAR_UUID,
        read=True, write=True, notify=True,
        max_len=512,
    )
    aioble.register_services(service)
    await asyncio.gather(advertise_task(), send_task())


async def advertise_task():
    while True:
        try:
            conn = await aioble.advertise(
                250_000, name="bitrelay",
                services=[SERVICE_UUID], timeout_ms=None,
            )
            addr = str(conn.device)
            print("[ADV] Client connected: %s" % addr)
            _conns.append(conn)
        except Exception as e:
            print("[ADV] Error: %s" % e)
            await asyncio.sleep(1)


async def send_task():
    await asyncio.sleep(10)
    print("[SEND] Preparing test message...")

    content = "hello from esp32"
    payload = content.encode("utf-8")
    raw = encode_packet(
        msg_type=MSG_MESSAGE,
        ttl=MESSAGE_TTL,
        sender_id=identity.peer_id,
        payload=payload,
        recipient_id=BROADCAST_RECIPIENT,
    )

    print("[SEND] Packet: %d bytes" % len(raw))
    print("[SEND] Hex (first 50): %s" % raw[:50].hex())

    # Verify our own packet decodes correctly
    pkt = decode_packet(raw)
    if pkt:
        print("[SEND] Self-decode OK: type=0x%02x ttl=%d flags=0x%02x payload_len=%d" % (
            pkt["type"], pkt["ttl"], pkt["flags"], len(pkt["payload"])))
        print("[SEND] Payload text: %s" % pkt["payload"].decode("utf-8"))
        if pkt["recipient_id"]:
            print("[SEND] Recipient: %s" % pkt["recipient_id"].hex())
    else:
        print("[SEND] Self-decode FAILED!")

    # Try sending
    active = [c for c in _conns if c.is_connected()]
    print("[SEND] Active connections: %d" % len(active))

    for conn in active:
        try:
            _char.notify(conn, raw)
            print("[SEND] Notified %s OK" % conn.device)
        except Exception as e:
            print("[SEND] Notify error: %s" % e)

    # Also try notify(None) for all
    try:
        _char.notify(None, raw)
        print("[SEND] notify(None) OK")
    except Exception as e:
        print("[SEND] notify(None) error: %s" % e)

    # Keep running to maintain connections
    while True:
        await asyncio.sleep(60)


asyncio.run(run())
