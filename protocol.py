import struct
import os
import time
from config import (
    HEADER_SIZE_V1, SENDER_ID_SIZE, RECIPIENT_ID_SIZE, SIGNATURE_SIZE,
    FLAG_HAS_RECIPIENT, FLAG_HAS_SIGNATURE, FLAG_IS_COMPRESSED, FLAG_HAS_ROUTE,
    MFLAG_IS_RELAY, MFLAG_IS_PRIVATE, MFLAG_HAS_ORIGINAL_SENDER,
    MFLAG_HAS_RECIPIENT_NICKNAME, MFLAG_HAS_SENDER_PEER_ID,
    MFLAG_HAS_MENTIONS, MFLAG_HAS_CHANNEL, MFLAG_IS_ENCRYPTED,
    PADDING_BLOCK_SIZES, BROADCAST_RECIPIENT, MESSAGE_TTL,
    MSG_FRAGMENT, FRAGMENT_THRESHOLD, MAX_FRAGMENT_SIZE, FRAGMENT_HEADER_SIZE,
)


# --- PKCS#7 Padding (matching MessagePadding.kt) ---

def optimal_block_size(data_size):
    total = data_size + 16
    for bs in PADDING_BLOCK_SIZES:
        if total <= bs:
            return bs
    return data_size


def pad(data, target_size):
    if len(data) >= target_size:
        return data
    padding_needed = target_size - len(data)
    if padding_needed <= 0 or padding_needed > 255:
        return data
    return data + bytes([padding_needed] * padding_needed)


def unpad(data):
    if not data:
        return data
    last = data[-1]
    pad_len = last & 0xFF
    if pad_len <= 0 or pad_len > len(data):
        return data
    start = len(data) - pad_len
    for i in range(start, len(data)):
        if data[i] != last:
            return data
    return data[:start]


# --- Packet encode/decode (matching BinaryProtocol.kt v1) ---

def encode_packet(msg_type, ttl, sender_id, payload, recipient_id=None, timestamp_ms=None):
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    version = 1
    flags = 0
    if recipient_id is not None:
        flags |= FLAG_HAS_RECIPIENT

    payload_len = len(payload)
    # Header: version(1) + type(1) + ttl(1) + timestamp(8) + flags(1) + payload_len(2) = 13
    header = struct.pack('>BBBQBH', version, msg_type, ttl, timestamp_ms, flags, payload_len)

    buf = bytearray(header)

    # SenderID (8 bytes, zero-padded)
    sid = bytearray(SENDER_ID_SIZE)
    sid[:len(sender_id[:SENDER_ID_SIZE])] = sender_id[:SENDER_ID_SIZE]
    buf.extend(sid)

    # RecipientID
    if recipient_id is not None:
        rid = bytearray(RECIPIENT_ID_SIZE)
        rid[:len(recipient_id[:RECIPIENT_ID_SIZE])] = recipient_id[:RECIPIENT_ID_SIZE]
        buf.extend(rid)

    # Payload
    buf.extend(payload)

    raw = bytes(buf)
    # Apply PKCS#7 padding
    target = optimal_block_size(len(raw))
    return pad(raw, target)


def decode_packet(data):
    # Try raw first, then unpadded (matching BinaryProtocol.decode)
    result = _decode_core(data)
    if result is not None:
        return result
    unpadded = unpad(data)
    if unpadded == data:
        return None
    return _decode_core(unpadded)


def _decode_core(raw):
    if len(raw) < HEADER_SIZE_V1 + SENDER_ID_SIZE:
        return None
    try:
        version = raw[0]
        if version not in (1, 2):
            return None

        if version == 1:
            header_size = HEADER_SIZE_V1
        else:
            header_size = 15  # v2 uses 4-byte payload length

        msg_type = raw[1]
        ttl = raw[2]
        timestamp_ms = struct.unpack_from('>Q', raw, 3)[0]
        flags = raw[11]

        has_recipient = bool(flags & FLAG_HAS_RECIPIENT)
        has_signature = bool(flags & FLAG_HAS_SIGNATURE)
        is_compressed = bool(flags & FLAG_IS_COMPRESSED)
        has_route = version >= 2 and bool(flags & FLAG_HAS_ROUTE)

        if version >= 2:
            payload_len = struct.unpack_from('>I', raw, 12)[0]
        else:
            payload_len = struct.unpack_from('>H', raw, 12)[0]

        offset = header_size

        # SenderID
        if offset + SENDER_ID_SIZE > len(raw):
            return None
        sender_id = bytes(raw[offset:offset + SENDER_ID_SIZE])
        offset += SENDER_ID_SIZE

        # RecipientID
        recipient_id = None
        if has_recipient:
            if offset + RECIPIENT_ID_SIZE > len(raw):
                return None
            recipient_id = bytes(raw[offset:offset + RECIPIENT_ID_SIZE])
            offset += RECIPIENT_ID_SIZE

        # Route (v2 only, skip over it)
        route = None
        if has_route:
            if offset >= len(raw):
                return None
            route_count = raw[offset]
            offset += 1
            route = []
            for _ in range(route_count):
                if offset + SENDER_ID_SIZE > len(raw):
                    return None
                route.append(bytes(raw[offset:offset + SENDER_ID_SIZE]))
                offset += SENDER_ID_SIZE

        # Payload (handle compressed by skipping original size prefix)
        if is_compressed:
            size_field = 4 if version >= 2 else 2
            if payload_len < size_field:
                return None
            # Skip original size, read compressed data
            # We don't decompress for MVP, just skip
            offset += size_field
            compressed_size = payload_len - size_field
            if offset + compressed_size > len(raw):
                return None
            payload = bytes(raw[offset:offset + compressed_size])
            offset += compressed_size
        else:
            if offset + payload_len > len(raw):
                return None
            payload = bytes(raw[offset:offset + payload_len])
            offset += payload_len

        # Signature
        signature = None
        if has_signature:
            if offset + SIGNATURE_SIZE <= len(raw):
                signature = bytes(raw[offset:offset + SIGNATURE_SIZE])
                offset += SIGNATURE_SIZE

        return {
            "version": version,
            "type": msg_type,
            "ttl": ttl,
            "timestamp_ms": timestamp_ms,
            "flags": flags,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "payload": payload,
            "signature": signature,
            "route": route,
        }
    except Exception:
        return None


def reencode_with_ttl(packet_dict, new_ttl):
    """Re-encode a decoded packet with a new TTL value."""
    return encode_packet(
        msg_type=packet_dict["type"],
        ttl=new_ttl,
        sender_id=packet_dict["sender_id"],
        payload=packet_dict["payload"],
        recipient_id=packet_dict["recipient_id"],
        timestamp_ms=packet_dict["timestamp_ms"],
    )


# --- Message payload encode/decode (matching BitchatMessage.kt) ---

def encode_message_payload(msg_id, sender_name, content, sender_peer_id=None,
                           is_relay=False, original_sender=None):
    buf = bytearray()
    flags = 0
    if is_relay:
        flags |= MFLAG_IS_RELAY
    if original_sender is not None:
        flags |= MFLAG_HAS_ORIGINAL_SENDER
    if sender_peer_id is not None:
        flags |= MFLAG_HAS_SENDER_PEER_ID
    buf.append(flags)

    # Timestamp (8 bytes BE, milliseconds)
    buf.extend(struct.pack('>Q', int(time.time() * 1000)))

    # ID
    id_bytes = msg_id.encode('utf-8')[:255]
    buf.append(len(id_bytes))
    buf.extend(id_bytes)

    # Sender
    sender_bytes = sender_name.encode('utf-8')[:255]
    buf.append(len(sender_bytes))
    buf.extend(sender_bytes)

    # Content
    content_bytes = content.encode('utf-8')[:65535]
    buf.extend(struct.pack('>H', len(content_bytes)))
    buf.extend(content_bytes)

    # Optional: originalSender
    if original_sender is not None:
        orig_bytes = original_sender.encode('utf-8')[:255]
        buf.append(len(orig_bytes))
        buf.extend(orig_bytes)

    # Optional: senderPeerID
    if sender_peer_id is not None:
        peer_bytes = sender_peer_id.encode('utf-8')[:255]
        buf.append(len(peer_bytes))
        buf.extend(peer_bytes)

    return bytes(buf)


def decode_message_payload(data):
    if len(data) < 13:
        return None
    try:
        offset = 0
        flags = data[offset]; offset += 1

        is_relay = bool(flags & MFLAG_IS_RELAY)
        is_private = bool(flags & MFLAG_IS_PRIVATE)
        has_original_sender = bool(flags & MFLAG_HAS_ORIGINAL_SENDER)
        has_recipient_nickname = bool(flags & MFLAG_HAS_RECIPIENT_NICKNAME)
        has_sender_peer_id = bool(flags & MFLAG_HAS_SENDER_PEER_ID)
        has_mentions = bool(flags & MFLAG_HAS_MENTIONS)
        has_channel = bool(flags & MFLAG_HAS_CHANNEL)
        is_encrypted = bool(flags & MFLAG_IS_ENCRYPTED)

        # Timestamp
        timestamp_ms = struct.unpack_from('>Q', data, offset)[0]
        offset += 8

        # ID
        id_len = data[offset]; offset += 1
        if offset + id_len > len(data):
            return None
        msg_id = data[offset:offset + id_len].decode('utf-8')
        offset += id_len

        # Sender
        sender_len = data[offset]; offset += 1
        if offset + sender_len > len(data):
            return None
        sender = data[offset:offset + sender_len].decode('utf-8')
        offset += sender_len

        # Content
        if offset + 2 > len(data):
            return None
        content_len = struct.unpack_from('>H', data, offset)[0]
        offset += 2
        if offset + content_len > len(data):
            return None
        if is_encrypted:
            content = ""
            offset += content_len
        else:
            content = data[offset:offset + content_len].decode('utf-8')
            offset += content_len

        # Optional: originalSender
        original_sender = None
        if has_original_sender and offset < len(data):
            length = data[offset]; offset += 1
            if offset + length <= len(data):
                original_sender = data[offset:offset + length].decode('utf-8')
                offset += length

        # Optional: recipientNickname
        recipient_nickname = None
        if has_recipient_nickname and offset < len(data):
            length = data[offset]; offset += 1
            if offset + length <= len(data):
                recipient_nickname = data[offset:offset + length].decode('utf-8')
                offset += length

        # Optional: senderPeerID
        sender_peer_id = None
        if has_sender_peer_id and offset < len(data):
            length = data[offset]; offset += 1
            if offset + length <= len(data):
                sender_peer_id = data[offset:offset + length].decode('utf-8')
                offset += length

        # Optional: mentions
        mentions = None
        if has_mentions and offset < len(data):
            count = data[offset]; offset += 1
            mentions = []
            for _ in range(count):
                if offset >= len(data):
                    break
                length = data[offset]; offset += 1
                if offset + length <= len(data):
                    mentions.append(data[offset:offset + length].decode('utf-8'))
                    offset += length

        # Optional: channel
        channel = None
        if has_channel and offset < len(data):
            length = data[offset]; offset += 1
            if offset + length <= len(data):
                channel = data[offset:offset + length].decode('utf-8')
                offset += length

        return {
            "id": msg_id,
            "sender": sender,
            "content": content,
            "timestamp_ms": timestamp_ms,
            "is_relay": is_relay,
            "is_private": is_private,
            "is_encrypted": is_encrypted,
            "original_sender": original_sender,
            "recipient_nickname": recipient_nickname,
            "sender_peer_id": sender_peer_id,
            "mentions": mentions,
            "channel": channel,
        }
    except Exception:
        return None


# --- Fragment encode/decode (matching FragmentPayload.kt) ---

def encode_fragment(fragment_id, index, total, original_type, data):
    buf = bytearray(FRAGMENT_HEADER_SIZE + len(data))
    buf[0:8] = fragment_id
    struct.pack_into('>HHB', buf, 8, index, total, original_type)
    buf[FRAGMENT_HEADER_SIZE:] = data
    return bytes(buf)


def decode_fragment(payload):
    if len(payload) < FRAGMENT_HEADER_SIZE:
        return None
    fragment_id = bytes(payload[0:8])
    index = struct.unpack_from('>H', payload, 8)[0]
    total = struct.unpack_from('>H', payload, 10)[0]
    original_type = payload[12]
    data = bytes(payload[FRAGMENT_HEADER_SIZE:])
    return {
        "fragment_id": fragment_id,
        "index": index,
        "total": total,
        "original_type": original_type,
        "data": data,
    }


def create_fragments(raw_packet, sender_id, ttl, timestamp_ms=None, recipient_id=None):
    """Split a raw encoded packet into FRAGMENT packets if it exceeds the threshold."""
    if len(raw_packet) <= FRAGMENT_THRESHOLD:
        return [raw_packet]

    # Unpad the raw packet first to get the actual data to fragment
    actual_data = unpad(raw_packet)

    # Calculate overhead for each fragment packet
    # Header(13) + sender(8) + [recipient(8)] + fragment_header(13) + padding slack
    overhead = HEADER_SIZE_V1 + SENDER_ID_SIZE + FRAGMENT_HEADER_SIZE
    if recipient_id is not None:
        overhead += RECIPIENT_ID_SIZE
    max_data = min(FRAGMENT_THRESHOLD - overhead - 16, MAX_FRAGMENT_SIZE)
    if max_data <= 0:
        max_data = MAX_FRAGMENT_SIZE

    fragment_id = os.urandom(8)

    # Determine original type from the packet
    original_type = actual_data[1] if len(actual_data) > 1 else 0

    # Split actual_data into chunks
    chunks = []
    offset = 0
    while offset < len(actual_data):
        chunks.append(actual_data[offset:offset + max_data])
        offset += max_data

    total = len(chunks)
    fragments = []
    for i, chunk in enumerate(chunks):
        frag_payload = encode_fragment(fragment_id, i, total, original_type, chunk)
        frag_packet = encode_packet(
            msg_type=MSG_FRAGMENT,
            ttl=ttl,
            sender_id=sender_id,
            payload=frag_payload,
            recipient_id=recipient_id,
            timestamp_ms=timestamp_ms,
        )
        fragments.append(frag_packet)

    return fragments


def generate_msg_id():
    """Generate a random message ID as uppercase hex string."""
    return ''.join('%02X' % b for b in os.urandom(16))
