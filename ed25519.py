"""Minimal Ed25519 implementation for MicroPython (RFC 8032)."""

from sha512 import sha512 as _sha512_digest

# Curve parameters
_Q = (1 << 255) - 19
_L = (1 << 252) + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _Q - 2, _Q) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)  # sqrt(-1)

# Base point
_BY = 4 * pow(5, _Q - 2, _Q) % _Q
_BX = _xrecover(_BY) if False else None  # set below


def _sha512(m):
    return _sha512_digest(m)


def _xrecover(y):
    xx = (y * y - 1) * pow(_D * y * y + 1, _Q - 2, _Q)
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = x * _I % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


_BX = _xrecover(_BY)
_B = (_BX, _BY, 1, _BX * _BY % _Q)  # Extended coordinates


def _edwards_add(P, Q):
    x1, y1, z1, t1 = P
    x2, y2, z2, t2 = Q
    a = (y1 - x1) * (y2 - x2) % _Q
    b = (y1 + x1) * (y2 + x2) % _Q
    c = t1 * 2 * _D * t2 % _Q
    d = z1 * 2 * z2 % _Q
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    x3 = e * f % _Q
    y3 = g * h % _Q
    t3 = e * h % _Q
    z3 = f * g % _Q
    return (x3, y3, z3, t3)


def _edwards_double(P):
    x1, y1, z1, _ = P
    a = x1 * x1 % _Q
    b = y1 * y1 % _Q
    c = 2 * z1 * z1 % _Q
    h = a + b
    e = h - (x1 + y1) * (x1 + y1) % _Q
    g = a - b
    f = c + g
    x3 = e * f % _Q
    y3 = g * h % _Q
    t3 = e * h % _Q
    z3 = f * g % _Q
    return (x3, y3, z3, t3)


def _scalarmult(P, e):
    if e == 0:
        return (0, 1, 1, 0)
    Q = (0, 1, 1, 0)  # identity
    while e > 0:
        if e & 1:
            Q = _edwards_add(Q, P)
        P = _edwards_double(P)
        e >>= 1
    return Q


def _encode_point(P):
    x, y, z, _ = P
    zi = pow(z, _Q - 2, _Q)
    x = x * zi % _Q
    y = y * zi % _Q
    bits = [(y >> i) & 1 for i in range(256)]
    bits[255] = x & 1
    return bytes([sum([bits[i * 8 + j] << j for j in range(8)]) for i in range(32)])


def _decode_point(s):
    y = int.from_bytes(s, 'little') & ((1 << 255) - 1)
    x = _xrecover(y)
    if s[31] & 0x80:
        if x == 0:
            return None
        x = _Q - x
    P = (x, y, 1, x * y % _Q)
    # Verify on curve
    if not _is_on_curve(P):
        return None
    return P


def _is_on_curve(P):
    x, y, z, _ = P
    zi = pow(z, _Q - 2, _Q)
    x = x * zi % _Q
    y = y * zi % _Q
    return (-x * x + y * y - 1 - _D * x * x * y * y) % _Q == 0


def _clamp(k):
    k_list = list(k)
    k_list[0] &= 248
    k_list[31] &= 127
    k_list[31] |= 64
    return bytes(k_list)


def _hint_from_bytes(h):
    return int.from_bytes(h, 'little')


def publickey(sk):
    """Derive 32-byte public key from 32-byte private key."""
    h = _sha512(sk)
    a = _hint_from_bytes(_clamp(h[:32]))
    A = _scalarmult(_B, a)
    return _encode_point(A)


def sign(msg, sk, pk=None):
    """Sign message with private key. Returns 64-byte signature."""
    if pk is None:
        pk = publickey(sk)
    h = _sha512(sk)
    a = _hint_from_bytes(_clamp(h[:32]))
    # r = SHA-512(h[32:64] || msg)
    r = _hint_from_bytes(_sha512(h[32:] + msg)) % _L
    R = _scalarmult(_B, r)
    Rs = _encode_point(R)
    # S = (r + SHA-512(Rs || pk || msg) * a) mod l
    S = (r + _hint_from_bytes(_sha512(Rs + pk + msg)) * a) % _L
    return Rs + S.to_bytes(32, 'little')


def verify(sig, msg, pk):
    """Verify 64-byte signature on message with public key."""
    if len(sig) != 64:
        return False
    Rs = sig[:32]
    S = _hint_from_bytes(sig[32:])
    if S >= _L:
        return False
    A = _decode_point(pk)
    R = _decode_point(Rs)
    if A is None or R is None:
        return False
    h = _hint_from_bytes(_sha512(Rs + pk + msg))
    # Check: [8][S]B = [8]R + [8][h]A
    sB = _scalarmult(_B, S)
    hA = _scalarmult(A, h)
    RhA = _edwards_add(R, hA)
    return _encode_point(sB) == _encode_point(RhA)
