import uasyncio as asyncio
import aioble
import bluetooth

SERVICE_UUID = bluetooth.UUID("F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C")
CHAR_UUID = bluetooth.UUID("A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D")
SERVICE_BYTES = bytes(SERVICE_UUID)


async def test():
    print("Scanning for bitchat peer...")
    target = None

    async with aioble.scan(10000, active=True, interval_us=30000, window_us=30000) as scanner:
        async for result in scanner:
            for svc in result.services():
                if bytes(svc) == SERVICE_BYTES:
                    target = result.device
                    print("Found: %s  RSSI=%d" % (target, result.rssi))
                    break
            if target:
                break

    if not target:
        print("No bitchat peer found!")
        return

    print("Connecting to %s..." % target)
    try:
        connection = await target.connect(timeout_ms=10000)
    except Exception as e:
        print("Connect failed: %s" % e)
        return

    print("Connected! Exchanging MTU...")
    try:
        await connection.exchange_mtu(512)
    except Exception as e:
        print("MTU exchange failed (non-fatal): %s" % e)

    print("Discovering service...")
    try:
        service = await connection.service(SERVICE_UUID)
        if service is None:
            print("Service not found!")
            connection.disconnect()
            return
        print("Service found: %s" % service)
    except Exception as e:
        print("Service discovery failed: %s" % e)
        connection.disconnect()
        return

    print("Discovering characteristic...")
    try:
        char = await service.characteristic(CHAR_UUID)
        if char is None:
            print("Characteristic not found!")
            connection.disconnect()
            return
        print("Characteristic found: %s" % char)
    except Exception as e:
        print("Characteristic discovery failed: %s" % e)
        connection.disconnect()
        return

    print("Subscribing to notifications...")
    try:
        await char.subscribe(notify=True)
        print("Subscribed!")
    except Exception as e:
        print("Subscribe failed: %s" % e)
        connection.disconnect()
        return

    print("Waiting for data (30 seconds)...")
    for i in range(30):
        try:
            data = await char.notified(timeout_ms=1000)
            if data:
                print("RECEIVED %d bytes: %s" % (len(data), data[:50].hex()))
        except asyncio.TimeoutError:
            if i % 5 == 0:
                print("  ...waiting (%ds)" % i)
        except Exception as e:
            print("Error: %s" % e)
            break

    print("Disconnecting...")
    connection.disconnect()
    print("Done.")

asyncio.run(test())
