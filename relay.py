import uasyncio as asyncio
import hashlib
import time
import gc
from config import (
    MSG_ANNOUNCE, MSG_MESSAGE, MSG_LEAVE, MSG_FRAGMENT,
    MSG_NOISE_HANDSHAKE, MSG_NOISE_ENCRYPTED, MSG_REQUEST_SYNC,
    BROADCAST_RECIPIENT, MESSAGE_TTL,
    DEDUP_CACHE_SIZE, STALE_PEER_TIMEOUT_S, PEER_CLEANUP_INTERVAL_S,
    FRAGMENT_TIMEOUT_S, FRAGMENT_CLEANUP_INTERVAL_S,
    ANNOUNCE_INTERVAL_S, SENDER_ID_SIZE,
)
from protocol import (
    decode_packet, encode_packet, reencode_with_ttl,
    decode_fragment, create_fragments,
)
from identity import Identity


class DedupCache:
    def __init__(self, max_size=DEDUP_CACHE_SIZE):
        self._max = max_size
        self._hashes = {}  # hash_hex -> timestamp
        self._order = []   # list of hash_hex, oldest first

    def is_duplicate(self, raw_data):
        h = hashlib.sha256(raw_data).digest()[:16]
        hx = ''.join('%02x' % b for b in h)
        if hx in self._hashes:
            return True
        self._hashes[hx] = time.time()
        self._order.append(hx)
        while len(self._order) > self._max:
            old = self._order.pop(0)
            self._hashes.pop(old, None)
        return False


class RelayEngine:
    def __init__(self, ble_mesh, identity):
        self.ble = ble_mesh
        self.identity = identity
        self.on_message = None     # callback(sender, content, is_relay, timestamp_ms)
        self.on_peer_update = None # callback(text)

        self._dedup = DedupCache()
        self._peers = {}           # peer_id_hex -> {nickname, last_seen, ble_addr, noise_pubkey}
        self._fragments = {}       # frag_id_hex -> {parts: {index: bytes}, total, orig_type, ts}
        self._packet_queue = []    # async queue for processing
        self.relay_count = 0       # total messages relayed

        # Wire up BLE receive
        self.ble.on_receive = self._on_raw_receive

    def _on_raw_receive(self, data, ble_addr):
        """Called synchronously from BLE on packet receive. Queue for async processing."""
        self._packet_queue.append((data, ble_addr))

    async def process_loop(self):
        """Main processing loop - drains the packet queue."""
        while True:
            while self._packet_queue:
                data, ble_addr = self._packet_queue.pop(0)
                await self._handle_packet(data, ble_addr)
            await asyncio.sleep_ms(20)

    async def _handle_packet(self, raw_data, source_addr):
        # Dedup
        if self._dedup.is_duplicate(raw_data):
            return

        pkt = decode_packet(raw_data)
        if pkt is None:
            return

        sender_hex = ''.join('%02x' % b for b in pkt["sender_id"])

        # Skip our own packets
        if sender_hex == self.identity.peer_id_hex:
            return

        # Skip message types we don't handle
        if pkt["type"] in (MSG_NOISE_HANDSHAKE, MSG_NOISE_ENCRYPTED, MSG_REQUEST_SYNC):
            return

        # Process by type
        if pkt["type"] == MSG_FRAGMENT:
            await self._handle_fragment(pkt, source_addr, sender_hex)
        elif pkt["type"] == MSG_ANNOUNCE:
            self._handle_announce(pkt, source_addr, sender_hex)
        elif pkt["type"] == MSG_MESSAGE:
            self._handle_message(pkt, sender_hex)
        elif pkt["type"] == MSG_LEAVE:
            self._handle_leave(sender_hex)

        # Relay if TTL > 0
        if pkt["ttl"] > 0:
            new_ttl = pkt["ttl"] - 1
            relayed = reencode_with_ttl(pkt, new_ttl)
            await self.ble.broadcast(relayed, exclude_addr=source_addr)
            self.relay_count += 1

    async def _handle_fragment(self, pkt, source_addr, sender_hex):
        frag = decode_fragment(pkt["payload"])
        if frag is None:
            return

        frag_id_hex = ''.join('%02x' % b for b in frag["fragment_id"])

        if frag_id_hex not in self._fragments:
            self._fragments[frag_id_hex] = {
                "parts": {},
                "total": frag["total"],
                "orig_type": frag["original_type"],
                "ts": time.time(),
            }

        entry = self._fragments[frag_id_hex]
        entry["parts"][frag["index"]] = frag["data"]

        # Check if all fragments received
        if len(entry["parts"]) >= entry["total"]:
            # Reassemble
            reassembled = bytearray()
            for i in range(entry["total"]):
                part = entry["parts"].get(i)
                if part is None:
                    del self._fragments[frag_id_hex]
                    return
                reassembled.extend(part)

            del self._fragments[frag_id_hex]

            # Process reassembled packet (display only, fragments already relayed)
            rpkt = decode_packet(bytes(reassembled))
            if rpkt is None:
                return

            rsender = ''.join('%02x' % b for b in rpkt["sender_id"])
            if rsender == self.identity.peer_id_hex:
                return

            if rpkt["type"] == MSG_ANNOUNCE:
                self._handle_announce(rpkt, source_addr, rsender)
            elif rpkt["type"] == MSG_MESSAGE:
                self._handle_message(rpkt, rsender)
            elif rpkt["type"] == MSG_LEAVE:
                self._handle_leave(rsender)

    def _handle_announce(self, pkt, source_addr, sender_hex):
        announce = self.identity.decode_announce_tlv(pkt["payload"])
        if announce is None:
            return

        is_new = sender_hex not in self._peers
        self._peers[sender_hex] = {
            "nickname": announce["nickname"],
            "last_seen": time.time(),
            "ble_addr": source_addr,
            "noise_pubkey": announce["noise_pubkey"],
        }

        if is_new and self.on_peer_update:
            self.on_peer_update("*** %s joined the mesh" % announce["nickname"])

    def _handle_message(self, pkt, sender_hex):
        # Android sends raw UTF-8 text as the payload
        try:
            content = pkt["payload"].decode("utf-8")
        except Exception:
            return

        # Look up sender nickname from peer registry
        peer = self._peers.get(sender_hex)
        sender = peer["nickname"] if peer else sender_hex[:12]

        # Update last_seen for known peer
        if sender_hex in self._peers:
            self._peers[sender_hex]["last_seen"] = time.time()

        is_relay = pkt["ttl"] < MESSAGE_TTL

        if self.on_message:
            self.on_message(
                sender,
                content,
                is_relay,
                pkt["timestamp_ms"],
            )

    def _handle_leave(self, sender_hex):
        peer = self._peers.pop(sender_hex, None)
        if peer and self.on_peer_update:
            self.on_peer_update("*** %s left the mesh" % peer["nickname"])

    async def send_message(self, content):
        """Send a broadcast chat message."""
        # Android uses raw UTF-8 text as payload
        payload = content.encode("utf-8")
        raw = encode_packet(
            msg_type=MSG_MESSAGE,
            ttl=MESSAGE_TTL,
            sender_id=self.identity.peer_id,
            payload=payload,
            recipient_id=BROADCAST_RECIPIENT,
            sign_fn=self.identity.sign,
        )

        packets = create_fragments(
            raw, self.identity.peer_id, MESSAGE_TTL,
            recipient_id=BROADCAST_RECIPIENT,
        )
        for pkt in packets:
            await self.ble.broadcast(pkt)

    async def send_announce(self):
        """Send an announce packet."""
        payload = self.identity.encode_announce_tlv()
        raw = encode_packet(
            msg_type=MSG_ANNOUNCE,
            ttl=MESSAGE_TTL,
            sender_id=self.identity.peer_id,
            payload=payload,
            sign_fn=self.identity.sign,
        )
        packets = create_fragments(raw, self.identity.peer_id, MESSAGE_TTL)
        conns = self.ble.connection_count
        print("[announce] sending %d pkt(s) to %d conn(s), size=%d" % (len(packets), conns, len(raw)))
        for pkt in packets:
            await self.ble.broadcast(pkt)

    async def send_leave(self):
        """Send a leave packet."""
        raw = encode_packet(
            msg_type=MSG_LEAVE,
            ttl=MESSAGE_TTL,
            sender_id=self.identity.peer_id,
            payload=b'',
        )
        await self.ble.broadcast(raw)

    def get_peers(self):
        """Return dict of known peers."""
        return dict(self._peers)

    async def periodic_announce(self):
        """Periodically send announce packets."""
        # Send initial announce
        await asyncio.sleep(2)
        await self.send_announce()
        while True:
            await asyncio.sleep(ANNOUNCE_INTERVAL_S)
            await self.send_announce()

    async def periodic_cleanup(self):
        """Periodically clean up stale peers and fragments."""
        while True:
            await asyncio.sleep(PEER_CLEANUP_INTERVAL_S)
            now = time.time()

            # Clean stale peers
            stale = [pid for pid, info in self._peers.items()
                     if now - info["last_seen"] > STALE_PEER_TIMEOUT_S]
            for pid in stale:
                peer = self._peers.pop(pid, None)
                if peer and self.on_peer_update:
                    self.on_peer_update("*** %s timed out" % peer["nickname"])

            # Clean stale fragments
            stale_frags = [fid for fid, info in self._fragments.items()
                          if now - info["ts"] > FRAGMENT_TIMEOUT_S]
            for fid in stale_frags:
                del self._fragments[fid]

            gc.collect()
