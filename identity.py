import os
import json
import hashlib
from config import TLV_NICKNAME, TLV_NOISE_PUBKEY, TLV_SIGNING_PUBKEY, MAX_NICKNAME_LENGTH

IDENTITY_FILE = "identity.json"


class Identity:
    def __init__(self):
        self.nickname = "esp32"
        self.noise_pubkey = b''
        self.signing_pubkey = b''
        self.peer_id = b''

    @property
    def peer_id_hex(self):
        return ''.join('%02x' % b for b in self.peer_id)

    def load_or_create(self):
        try:
            with open(IDENTITY_FILE, "r") as f:
                data = json.load(f)
            self.nickname = data["nickname"]
            self.noise_pubkey = bytes.fromhex(data["noise_pubkey"])
            self.signing_pubkey = bytes.fromhex(data["signing_pubkey"])
            self.peer_id = hashlib.sha256(self.noise_pubkey).digest()[:8]
        except (OSError, KeyError, ValueError):
            self.noise_pubkey = os.urandom(32)
            self.signing_pubkey = os.urandom(32)
            self.peer_id = hashlib.sha256(self.noise_pubkey).digest()[:8]
            self._save()

    def set_nickname(self, name):
        name = name.strip()[:MAX_NICKNAME_LENGTH]
        if name:
            self.nickname = name
            self._save()

    def _save(self):
        data = {
            "nickname": self.nickname,
            "noise_pubkey": ''.join('%02x' % b for b in self.noise_pubkey),
            "signing_pubkey": ''.join('%02x' % b for b in self.signing_pubkey),
        }
        with open(IDENTITY_FILE, "w") as f:
            json.dump(data, f)

    def encode_announce_tlv(self):
        result = bytearray()
        nick_bytes = self.nickname.encode('utf-8')[:255]
        result.append(TLV_NICKNAME)
        result.append(len(nick_bytes))
        result.extend(nick_bytes)
        result.append(TLV_NOISE_PUBKEY)
        result.append(len(self.noise_pubkey))
        result.extend(self.noise_pubkey)
        result.append(TLV_SIGNING_PUBKEY)
        result.append(len(self.signing_pubkey))
        result.extend(self.signing_pubkey)
        return bytes(result)

    @staticmethod
    def decode_announce_tlv(data):
        offset = 0
        nickname = None
        noise_pubkey = None
        signing_pubkey = None
        while offset + 2 <= len(data):
            tlv_type = data[offset]
            length = data[offset + 1]
            offset += 2
            if offset + length > len(data):
                return None
            value = data[offset:offset + length]
            offset += length
            if tlv_type == TLV_NICKNAME:
                nickname = value.decode('utf-8')
            elif tlv_type == TLV_NOISE_PUBKEY:
                noise_pubkey = bytes(value)
            elif tlv_type == TLV_SIGNING_PUBKEY:
                signing_pubkey = bytes(value)
            # Skip unknown TLV types for forward compatibility
        if nickname is not None and noise_pubkey is not None and signing_pubkey is not None:
            return {"nickname": nickname, "noise_pubkey": noise_pubkey, "signing_pubkey": signing_pubkey}
        return None
