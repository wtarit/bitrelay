# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

bitrelay-esp32 is a MicroPython BLE mesh chat node for ESP32, protocol-compatible with [bitchat-android](https://github.com/nicholasgasior/bitchat-android). It implements Bluetooth-only transport with serial terminal chat and message relay functionality. No encryption (Noise protocol) in this MVP — only ANNOUNCE, MESSAGE, LEAVE, and FRAGMENT packet types.

## Deployment

```bash
# Install aioble on ESP32
mpremote mip install aioble

# Copy all files to ESP32
mpremote cp config.py identity.py protocol.py ble_mesh.py relay.py terminal.py main.py :

# Run (auto-starts on boot if main.py is on flash)
mpremote run main.py
```

There are no tests, linter, or build system — this is bare MicroPython deployed directly to hardware.

## Architecture

The system uses a callback-wired architecture with `uasyncio` for concurrency. All components run as concurrent coroutines via `asyncio.gather` in `main.py`.

**Data flow:** BLE receives raw bytes → `relay.py` queues them → decodes packet → dedup check → process by type (display via terminal callback) → relay with TTL-1 to all other peers via BLE broadcast.

**Key design decisions:**
- BLE receive callback (`ble_mesh.on_receive`) is synchronous — it appends to a list that `relay.process_loop()` drains asynchronously, avoiding blocking the BLE stack.
- The ESP32 runs dual-role BLE simultaneously: GATT server (accepts connections via `aioble.advertise`) and GATT client (scans and connects to peers). Both use the same service/characteristic UUIDs.
- Server connections send data via `characteristic.notify()`, client connections via `characteristic.write()`.
- Identity (keys + nickname) persists to `identity.json` on flash.

## Protocol Compatibility

All binary formats must match bitchat-android exactly. The reference implementation is in `/home/tarit/projects/bitchat-android/`. Key source files:

- `protocol/BinaryProtocol.kt` — packet header format, flags, encode/decode
- `model/BitchatMessage.kt` — message payload binary format
- `model/IdentityAnnouncement.kt` — announce TLV encoding
- `model/FragmentPayload.kt` — fragment header (13 bytes)
- `protocol/MessagePadding.kt` — PKCS#7 padding with block sizes [256, 512, 1024, 2048]
- `util/AppConstants.kt` — UUIDs, timeouts, thresholds

**Critical protocol details:**
- Packet v1 header is 13 bytes: `version(1) | type(1) | ttl(1) | timestamp(8 BE) | flags(1) | payload_len(2 BE)`
- All multi-byte integers are big-endian
- BROADCAST recipient = 8 bytes of 0xFF
- Peer ID = first 8 bytes of SHA-256 of noise public key
- Decode must try raw data first, then try after PKCS#7 unpad (Android's two-pass decode)
- Fragment header: `frag_id(8) | index(2 BE) | total(2 BE) | orig_type(1)` = 13 bytes

## MicroPython Constraints

- Use `struct` module for binary packing (supports `>BBBQBH` etc.)
- `uasyncio` not `asyncio`; `asyncio.ticks()` not `time.monotonic()`
- No `collections.OrderedDict` with `move_to_end` — dedup uses simple list + dict
- ESP32 BLE supports ~3-4 simultaneous connections max
- `os.urandom()` for random bytes, `hashlib.sha256` available
- No f-strings on older MicroPython — use `%` formatting
