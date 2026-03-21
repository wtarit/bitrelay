import uasyncio as asyncio
import gc
from identity import Identity
from ble_mesh import BLEMesh
from relay import RelayEngine
from terminal import Terminal


async def main():
    # 1. Load or create identity
    identity = Identity()
    identity.load_or_create()

    # 2. Create BLE mesh
    ble = BLEMesh()

    # 3. Create relay engine
    relay = RelayEngine(ble, identity)

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
