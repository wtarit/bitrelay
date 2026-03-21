import time
import os

print("Testing Ed25519...")
t0 = time.ticks_ms()
import ed25519
t1 = time.ticks_ms()
print("Import: %d ms" % time.ticks_diff(t1, t0))

sk = os.urandom(32)
t0 = time.ticks_ms()
pk = ed25519.publickey(sk)
t1 = time.ticks_ms()
print("Keygen: %d ms" % time.ticks_diff(t1, t0))
print("PK: %s" % pk.hex())

msg = b"hello from esp32"
t0 = time.ticks_ms()
sig = ed25519.sign(msg, sk, pk)
t1 = time.ticks_ms()
print("Sign: %d ms" % time.ticks_diff(t1, t0))
print("Sig len: %d" % len(sig))

t0 = time.ticks_ms()
ok = ed25519.verify(sig, msg, pk)
t1 = time.ticks_ms()
print("Verify: %d ms, result=%s" % (time.ticks_diff(t1, t0), ok))
