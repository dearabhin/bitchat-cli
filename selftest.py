# selftest.py
#
# Offline checks for the bitchat wire protocol implementation. These do NOT
# touch Bluetooth; they verify that encoding/decoding round-trips and that our
# signatures match the canonical form the real app verifies against.
#
#   python selftest.py

import os

from cryptography.hazmat.primitives.asymmetric import ed25519

from identity import IdentityKeys
from protocol import (
    AnnouncementPacket,
    BitchatPacket,
    MessagePadding,
    MessageType,
    FragmentReassembler,
    SIGNATURE_SIZE,
)

passed = 0


def check(name, condition):
    global passed
    if condition:
        passed += 1
        print(f"  ok  - {name}")
    else:
        raise AssertionError(f"FAILED - {name}")


def test_padding():
    check("optimal block size small -> 256", MessagePadding.optimal_block_size(50) == 256)
    check("optimal block size 300 -> 512", MessagePadding.optimal_block_size(300) == 512)
    data = b"hello world"
    padded = MessagePadding.pad(data, 256)
    check("padded length is block size", len(padded) == 256)
    check("unpad restores original", MessagePadding.unpad(padded) == data)


def test_packet_roundtrip():
    pkt = BitchatPacket(
        type=MessageType.MESSAGE,
        sender_id=os.urandom(8),
        recipient_id=None,
        payload=b"gm from the CLI",
        ttl=7,
    )
    decoded = BitchatPacket.decode(pkt.encode())
    check("packet decodes", decoded is not None)
    check("type preserved", decoded.type == MessageType.MESSAGE)
    check("sender preserved", decoded.sender_id == pkt.sender_id)
    check("payload preserved (padding ignored)", decoded.payload == pkt.payload)
    check("ttl preserved", decoded.ttl == 7)

    # With recipient + signature flags.
    pkt2 = BitchatPacket(
        type=MessageType.ANNOUNCE, sender_id=os.urandom(8),
        recipient_id=b"\xff" * 8, payload=b"x" * 100, signature=os.urandom(SIGNATURE_SIZE),
    )
    d2 = BitchatPacket.decode(pkt2.encode())
    check("recipient preserved", d2.recipient_id == b"\xff" * 8)
    check("signature preserved", d2.signature == pkt2.signature)
    check("payload preserved w/ sig", d2.payload == pkt2.payload)


def test_signature_matches_canonical():
    keys = IdentityKeys()
    pkt = BitchatPacket(
        type=MessageType.MESSAGE, sender_id=os.urandom(8),
        recipient_id=None, payload=b"signed message", ttl=7,
    )
    pkt.signature = keys.sign(pkt.data_for_signing())
    wire = pkt.encode()

    # The receiver decodes, reconstructs the canonical bytes from decoded fields
    # (ttl forced to 0, no signature) and verifies. Simulate that here.
    decoded = BitchatPacket.decode(wire)
    canonical = decoded.data_for_signing()
    pub = ed25519.Ed25519PublicKey.from_public_bytes(keys.signing_public_key_bytes())
    try:
        pub.verify(decoded.signature, canonical)
        ok = True
    except Exception:
        ok = False
    check("ed25519 signature verifies against canonical bytes", ok)
    check("canonical bytes are ttl-independent",
          BitchatPacket.decode(wire).data_for_signing() == pkt.data_for_signing())


def test_announce():
    keys = IdentityKeys()
    ann = AnnouncementPacket(
        nickname="user-abcd",
        noise_public_key=keys.noise_public_key_bytes(),
        signing_public_key=keys.signing_public_key_bytes(),
    )
    decoded = AnnouncementPacket.decode(ann.encode())
    check("announce decodes", decoded is not None)
    check("nickname preserved", decoded.nickname == "user-abcd")
    check("noise key preserved (32B)", decoded.noise_public_key == keys.noise_public_key_bytes())
    check("signing key preserved (32B)", decoded.signing_public_key == keys.signing_public_key_bytes())


def test_fragment_reassembly():
    sender = os.urandom(8)
    # A large inner packet that would exceed one BLE write.
    inner = BitchatPacket(
        type=MessageType.MESSAGE, sender_id=sender, recipient_id=None,
        payload=b"A" * 1500, ttl=7,
    )
    inner_bytes = inner.encode()

    fragment_id = os.urandom(8)
    chunk = 400
    chunks = [inner_bytes[i:i + chunk] for i in range(0, len(inner_bytes), chunk)]
    total = len(chunks)

    reasm = FragmentReassembler()
    result = None
    for index, c in enumerate(chunks):
        payload = (fragment_id + index.to_bytes(2, "big") + total.to_bytes(2, "big")
                   + bytes([int(MessageType.MESSAGE)]) + c)
        frag = BitchatPacket(type=MessageType.FRAGMENT, sender_id=sender, payload=payload)
        result = reasm.add(frag)
    check("fragments reassemble", result == inner_bytes)
    rebuilt = BitchatPacket.decode(result)
    check("reassembled packet decodes", rebuilt is not None and rebuilt.payload == b"A" * 1500)


def test_public_message_payload_is_raw():
    # Public message payload must be the raw UTF-8 content (not a TLV blob).
    content = "hello, mesh 👋"
    pkt = BitchatPacket(type=MessageType.MESSAGE, sender_id=os.urandom(8),
                        payload=content.encode("utf-8"))
    decoded = BitchatPacket.decode(pkt.encode())
    check("public payload is raw utf-8 content",
          decoded.payload.decode("utf-8") == content)


if __name__ == "__main__":
    print("Running bitchat-cli protocol self-tests...\n")
    for test in (
        test_padding,
        test_packet_roundtrip,
        test_signature_matches_canonical,
        test_announce,
        test_fragment_reassembly,
        test_public_message_payload_is_raw,
    ):
        print(f"{test.__name__}:")
        test()
    print(f"\nAll {passed} checks passed. ✅")
