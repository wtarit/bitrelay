import uasyncio as asyncio
import aioble
import bluetooth

SERVICE_UUID = bluetooth.UUID("F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C")

async def scan():
    print("Our SERVICE_UUID: %s (type=%s)" % (SERVICE_UUID, type(SERVICE_UUID)))
    print("Scanning for BLE devices (10 seconds)...")
    print("-" * 50)
    bitchat_found = 0

    async with aioble.scan(
        10000,
        active=True,
        interval_us=30000,
        window_us=30000,
    ) as scanner:
        async for result in scanner:
            services = result.services()
            if not services:
                continue

            # Check each service UUID
            for svc in services:
                svc_str = str(svc).lower()
                if 'f47b5e2d' in svc_str:
                    bitchat_found += 1
                    name = result.name() if result.name() else "(no name)"
                    print("BITCHAT PEER #%d:" % bitchat_found)
                    print("  Name: %s" % name)
                    print("  RSSI: %d" % result.rssi)
                    print("  Device: %s" % str(result.device))
                    print("  Service UUID: %s (type=%s)" % (svc, type(svc)))
                    print("  Match via 'in': %s" % (SERVICE_UUID in services))
                    print("  Match via '==': %s" % (SERVICE_UUID == svc))
                    print("  Our bytes: %s" % bytes(SERVICE_UUID))
                    print("  Their bytes: %s" % bytes(svc))
                    print("-" * 50)
                    break

            if bitchat_found >= 5:
                break

    print("Found %d bitchat advertisements." % bitchat_found)

asyncio.run(scan())
