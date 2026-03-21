# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

bitrelay-esp32 is a MicroPython BLE mesh chat node for ESP32, protocol-compatible with [bitchat-android](https://github.com/nicholasgasior/bitchat-android). It implements Bluetooth-only transport with serial terminal chat and message relay functionality. Supports ANNOUNCE, MESSAGE, LEAVE, and FRAGMENT packet types with Ed25519 signatures. No Noise protocol encryption in this MVP.

## Deployment

```bash
# Install aioble on ESP32 (one-time)
mpremote mip install aioble

# Copy all files to ESP32
mpremote connect /dev/ttyUSB0 cp config.py identity.py protocol.py ble_mesh.py relay.py terminal.py main.py ed25519.py sha512.py :

# Run
mpremote connect /dev/ttyUSB0 run main.py
```

There are no tests, linter, or build system — this is bare MicroPython deployed directly to hardware. WiFi credentials in `config.py` must be set for NTP time sync.

## Architecture

The system uses a callback-wired architecture with `uasyncio` for concurrency. All components run as concurrent coroutines via `asyncio.gather` in `main.py`.

**Startup sequence:** NTP time sync via WiFi (then WiFi off) → load identity → create BLE mesh → create relay engine → wire callbacks → run all tasks concurrently.

**Data flow:** BLE receives raw bytes → `relay.py` queues them → decodes packet → dedup check → process by type (display via terminal callback) → relay with TTL-1 to all other peers via BLE broadcast.

**Key design decisions:**
- BLE receive callback (`ble_mesh.on_receive`) is synchronous — it appends to a list that `relay.process_loop()` drains asynchronously, avoiding blocking the BLE stack.
- The ESP32 runs dual-role BLE simultaneously: GATT server (accepts connections via `aioble.advertise`) and GATT client (scans and connects to peers). Both use the same service/characteristic UUIDs.
- Server connections send data via `characteristic.notify()`, client connections via `characteristic.write()`.
- Identity (Ed25519 keys + nickname) persists to `identity.json` on flash.
- `on_connect` callback triggers an ANNOUNCE 500ms after any new BLE connection, so peers recognize each other promptly.
- Relay preserves the original Ed25519 signature (computed with TTL=0) and only patches the TTL byte.

**Crypto stack:** `ed25519.py` and `sha512.py` are pure-Python implementations needed because MicroPython lacks native Ed25519/SHA-512. Signing is slow (~1s per operation) but only happens on outbound packets.

## Protocol Compatibility

All binary formats must match bitchat-android exactly. The reference implementation is in `/home/tarit/projects/bitchat-android/`. Key source files:

- `protocol/BinaryProtocol.kt` — packet header format, flags, encode/decode
- `model/BitchatMessage.kt` — message payload binary format
- `model/IdentityAnnouncement.kt` — announce TLV encoding
- `model/FragmentPayload.kt` — fragment header (13 bytes)
- `protocol/MessagePadding.kt` — PKCS#7 padding with block sizes [256, 512, 1024, 2048]
- `util/AppConstants.kt` — UUIDs, timeouts, thresholds
- `mesh/SecurityManager.kt` — signature verification flow

**Critical protocol details:**
- Packet v1 header is 14 bytes: `version(1) | type(1) | ttl(1) | timestamp(8 BE) | flags(1) | payload_len(2 BE)`. Note: Android's `HEADER_SIZE_V1 = 13` is a cosmetic bug in their code; actual headers are 14 bytes.
- All multi-byte integers are big-endian
- BROADCAST recipient = 8 bytes of 0xFF
- Peer ID = first 8 bytes of SHA-256 of noise public key
- Decode must try raw data first, then try after PKCS#7 unpad (Android's two-pass decode)
- Fragment header: `frag_id(8) | index(2 BE) | total(2 BE) | orig_type(1)` = 13 bytes
- Signatures are Ed25519 over the packet built with TTL=0, no signature, then PKCS#7 padded. Android extracts the signing key from the ANNOUNCE TLV itself for verification.
- Timestamps must be Unix epoch milliseconds. MicroPython's `time.time()` uses a 2000-01-01 epoch — add `EPOCH_OFFSET` (946684800) before converting to millis, otherwise Android rejects packets as stale (>180s age check in MessageHandler).

## MicroPython Constraints

- Use `struct` module for binary packing (supports `>BBBQBH` etc.)
- `uasyncio` not `asyncio`; `asyncio.ticks()` not `time.monotonic()`
- No `collections.OrderedDict` with `move_to_end` — dedup uses simple list + dict
- ESP32 BLE supports ~3-4 simultaneous connections max
- `os.urandom()` for random bytes, `hashlib.sha256` available, but no `hashlib.sha512` (hence `sha512.py`)
- No f-strings on older MicroPython — use `%` formatting

## Debugging

```bash
# Read Android app logs for ESP32 interactions
adb logcat | grep -E "987ab327|esp32|SecurityManager|MessageHandler|PacketProcessor"

# Check if ESP32 serial device is available
mpremote devs
```
