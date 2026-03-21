import uasyncio as asyncio
import aioble
import bluetooth
from config import (
    SERVICE_UUID, CHARACTERISTIC_UUID,
    MAX_CONNECTIONS, SCAN_DURATION_MS, SCAN_INTERVAL_S,
    ADVERTISE_INTERVAL_US,
)

_SERVICE_UUID = bluetooth.UUID(SERVICE_UUID)
_CHAR_UUID = bluetooth.UUID(CHARACTERISTIC_UUID)
_SERVICE_UUID_BYTES = bytes(_SERVICE_UUID)


def _has_bitchat_service(result):
    """Check if scan result advertises bitchat service UUID.

    Uses bytes comparison because MicroPython's bluetooth.UUID
    doesn't implement __hash__, so 'UUID in set' fails even when
    UUID == UUID returns True.
    """
    for svc in result.services():
        if bytes(svc) == _SERVICE_UUID_BYTES:
            return True
    return False


class BLEMesh:
    def __init__(self):
        self.on_receive = None  # callback(data: bytes, ble_addr: str)
        self.on_connect = None  # callback() - called when new connection established
        self._server_conns = {}  # ble_addr -> (connection, last_seen)
        self._client_conns = {}  # ble_addr -> (connection, characteristic, last_seen)
        self._known_addrs = set()  # addresses we've seen (avoid reconnecting)
        self._connecting = set()   # addresses currently being connected to
        self._service = aioble.Service(_SERVICE_UUID)
        self._char = aioble.BufferedCharacteristic(
            self._service, _CHAR_UUID,
            read=True, write=True, notify=True,
            max_len=512,
        )
        aioble.register_services(self._service)

    @property
    def connection_count(self):
        return len(self._server_conns) + len(self._client_conns)

    def _all_addrs(self):
        return set(self._server_conns.keys()) | set(self._client_conns.keys())

    async def start(self):
        await asyncio.gather(
            self._server_task(),
            self._server_read_task(),
            self._client_task(),
            self._cleanup_task(),
        )

    async def _server_task(self):
        """Advertise and accept incoming connections."""
        while True:
            try:
                connection = await aioble.advertise(
                    ADVERTISE_INTERVAL_US,
                    name="bitrelay",
                    services=[_SERVICE_UUID],
                    timeout_ms=None,
                )
                addr = _conn_addr(connection)
                self._server_conns[addr] = (connection, asyncio.ticks())
                asyncio.create_task(self._monitor_server_conn(addr, connection))
                if self.on_connect:
                    asyncio.create_task(self.on_connect())
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)

    async def _monitor_server_conn(self, addr, connection):
        """Wait for a server connection to disconnect, then clean up."""
        try:
            await connection.disconnected(timeout_ms=None)
        except Exception:
            pass
        self._server_conns.pop(addr, None)

    async def _server_read_task(self):
        """Read writes from connected clients via the characteristic."""
        while True:
            try:
                result = await self._char.written()
                # BufferedCharacteristic.written() returns connection only;
                # data is read via char.read(). Regular Characteristic with
                # capture returns (connection, data).
                if isinstance(result, tuple):
                    connection, data = result
                else:
                    connection = result
                    data = self._char.read()
                if data and self.on_receive:
                    addr = _conn_addr(connection)
                    try:
                        self.on_receive(bytes(data), addr)
                    except Exception:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep_ms(100)

    async def _client_task(self):
        """Scan for peers and connect to them."""
        while True:
            try:
                async with aioble.scan(
                    SCAN_DURATION_MS,
                    active=True,
                    interval_us=30000,
                    window_us=30000,
                ) as scanner:
                    async for result in scanner:
                        if not _has_bitchat_service(result):
                            continue
                        addr = _device_addr(result.device)
                        # Skip if already connected (server or client side)
                        if addr in self._all_addrs() or addr in self._connecting:
                            continue
                        if self.connection_count >= MAX_CONNECTIONS:
                            continue
                        self._connecting.add(addr)
                        asyncio.create_task(self._connect_to_peer(result.device, addr))
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(SCAN_INTERVAL_S)

    async def _connect_to_peer(self, device, addr):
        """Connect to a discovered peer and listen for notifications."""
        try:
            connection = await device.connect(timeout_ms=10000)
        except Exception:
            self._connecting.discard(addr)
            return

        try:
            await connection.exchange_mtu(512)
        except Exception:
            pass

        try:
            service = await connection.service(_SERVICE_UUID)
            if service is None:
                connection.disconnect()
                return
            char = await service.characteristic(_CHAR_UUID)
            if char is None:
                connection.disconnect()
                return
            await char.subscribe(notify=True)
        except Exception:
            self._connecting.discard(addr)
            try:
                connection.disconnect()
            except Exception:
                pass
            return

        self._connecting.discard(addr)
        self._client_conns[addr] = (connection, char, asyncio.ticks())
        if self.on_connect:
            asyncio.create_task(self.on_connect())

        # Read notifications until disconnected
        try:
            while connection.is_connected():
                data = await char.notified(timeout_ms=5000)
                if data and self.on_receive:
                    try:
                        self.on_receive(bytes(data), addr)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            self._client_conns.pop(addr, None)
            try:
                connection.disconnect()
            except Exception:
                pass

    async def broadcast(self, data, exclude_addr=None):
        """Send data to all connected peers except exclude_addr."""
        tasks = []
        # Notify server connections
        for addr, (conn, _) in list(self._server_conns.items()):
            if addr == exclude_addr:
                continue
            if not conn.is_connected():
                continue
            tasks.append(self._notify_server(conn, data))

        # Write to client connections
        for addr, (conn, char, _) in list(self._client_conns.items()):
            if addr == exclude_addr:
                continue
            if not conn.is_connected():
                continue
            tasks.append(self._write_client(char, data))

        for t in tasks:
            try:
                await t
            except Exception:
                pass

    async def _notify_server(self, connection, data):
        """Send data to a server-side connection via notification."""
        try:
            self._char.notify(connection, data)
        except Exception as e:
            print("[ble] notify error: %s" % e)

    async def _write_client(self, char, data):
        """Send data to a client-side connection via write."""
        try:
            await char.write(data, response=False)
        except Exception as e:
            print("[ble] write error: %s" % e)

    async def _cleanup_task(self):
        """Periodically remove dead connections."""
        while True:
            await asyncio.sleep(30)
            for addr in list(self._server_conns.keys()):
                conn, _ = self._server_conns[addr]
                if not conn.is_connected():
                    self._server_conns.pop(addr, None)
            for addr in list(self._client_conns.keys()):
                conn, _, _ = self._client_conns[addr]
                if not conn.is_connected():
                    self._client_conns.pop(addr, None)


def _conn_addr(connection):
    """Extract address string from an aioble connection."""
    try:
        device = connection.device
        return str(device)
    except Exception:
        return str(id(connection))


def _device_addr(device):
    """Extract address string from an aioble device."""
    return str(device)
