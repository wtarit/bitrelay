import uasyncio as asyncio
import gc
import time
import network
import ntptime
from config import WIFI_SSID, WIFI_PASSWORD
from identity import Identity
from ble_mesh import BLEMesh
from relay import RelayEngine
from terminal import Terminal


def sync_time():
    """Connect to WiFi briefly to sync time via NTP, then disconnect."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(20):
        if wlan.isconnected():
            break
        time.sleep_ms(500)
    if wlan.isconnected():
        try:
            ntptime.settime()
            print("[ntp] Time synced")
        except Exception as e:
            print("[ntp] Sync failed: %s" % e)
    else:
        print("[ntp] WiFi connect failed")
    wlan.active(False)


async def main():
    # 0. Sync time via NTP
    sync_time()
    gc.collect()

    # 1. Load or create identity
    identity = Identity()
    identity.load_or_create()

    # 2. Create BLE mesh
    ble = BLEMesh()

    # 3. Create relay engine
    relay = RelayEngine(ble, identity)

    # Send announce when a new BLE connection is established
    async def _on_connect():
        await asyncio.sleep_ms(500)  # brief delay for connection to stabilize
        await relay.send_announce()

    ble.on_connect = _on_connect

    # 4. Create terminal
    def get_info():
        return {
            "peer_id": identity.peer_id_hex,
            "nickname": identity.nickname,
            "connections": ble.connection_count,
            "peers": len(relay.get_peers()),
        }

    terminal = Terminal(
        send_message_cb=relay.send_message,
        set_nick_cb=identity.set_nickname,
        get_peers_cb=relay.get_peers,
        get_info_cb=get_info,
        quit_cb=relay.send_leave,
        send_announce_cb=relay.send_announce,
    )

    # Wire relay callbacks to terminal
    relay.on_message = terminal.display_message
    relay.on_peer_update = terminal.display_system

    # 5. Run all tasks
    gc.collect()
    await asyncio.gather(
        ble.start(),
        relay.process_loop(),
        relay.periodic_announce(),
        relay.periodic_cleanup(),
        terminal.run(),
    )


try:
    asyncio.run(main())
except SystemExit:
    pass
except KeyboardInterrupt:
    print("\nExiting...")
