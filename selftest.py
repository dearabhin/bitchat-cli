# selftest.py
#
# Offline checks for the bitchat wire protocol implementation. These do NOT
# touch Bluetooth; they verify that encoding/decoding round-trips and that our
# signatures match the canonical form the real app verifies against.
#
#   python selftest.py

import os

from cryptography.hazmat.primitives.asymmetric import ed25519

from bitchat_cli.identity import IdentityKeys
from bitchat_cli.media import (
    BitchatFilePacket,
    MAX_PAYLOAD_BYTES,
    category_for_mime,
    message_prefix,
    mime_for_extension,
)
from bitchat_cli.protocol import (
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


def test_file_packet_roundtrip():
    # A PNG-ish blob with name + mime.
    content = b"\x89PNG\r\n\x1a\n" + b"Z" * 500
    fp = BitchatFilePacket(
        content=content, file_name="photo.png", file_size=len(content),
        mime_type="image/png",
    )
    encoded = fp.encode()
    check("file packet encodes", encoded is not None)
    d = BitchatFilePacket.decode(encoded)
    check("file packet decodes", d is not None)
    check("content preserved", d.content == content)
    check("file_name preserved", d.file_name == "photo.png")
    check("mime preserved", d.mime_type == "image/png")
    check("file_size preserved", d.file_size == len(content))

    # Minimal packet: content only (no name / mime).
    bare = BitchatFilePacket(content=b"\x00\x01\x02\x03")
    db = BitchatFilePacket.decode(bare.encode())
    check("bare file packet decodes", db is not None and db.content == b"\x00\x01\x02\x03")
    check("bare file_size defaults to content length", db.file_size == 4)


def test_file_packet_oversize_rejected():
    huge = BitchatFilePacket(content=b"\x00" * (MAX_PAYLOAD_BYTES + 1))
    check("oversize file packet rejected by encode", huge.encode() is None)


def test_file_transfer_packet_wrap():
    # A FILE_TRANSFER BitchatPacket carrying a file TLV must round-trip the bytes.
    content = b"\xff\xd8\xff" + b"J" * 2000  # jpeg-ish, big enough to need fragmenting
    fp = BitchatFilePacket(content=content, file_name="clip.jpg", mime_type="image/jpeg")
    payload = fp.encode()
    pkt = BitchatPacket(
        type=MessageType.FILE_TRANSFER, sender_id=os.urandom(8),
        recipient_id=None, payload=payload, ttl=7,
    )
    decoded = BitchatPacket.decode(pkt.encode())
    check("file-transfer packet decodes", decoded is not None)
    check("file-transfer type preserved", decoded.type == MessageType.FILE_TRANSFER)
    inner = BitchatFilePacket.decode(decoded.payload)
    check("inner file content recovered", inner is not None and inner.content == content)


def test_file_fragment_reassembly():
    # A file packet exceeding one BLE write reassembles back to identical bytes.
    sender = os.urandom(8)
    fp = BitchatFilePacket(content=b"M" * 4000, file_name="big.bin",
                           mime_type="application/octet-stream")
    inner = BitchatPacket(
        type=MessageType.FILE_TRANSFER, sender_id=sender, recipient_id=None,
        payload=fp.encode(), ttl=7,
    )
    inner_bytes = inner.encode()

    fragment_id = os.urandom(8)
    chunk = 440
    chunks = [inner_bytes[i:i + chunk] for i in range(0, len(inner_bytes), chunk)]
    total = len(chunks)
    reasm = FragmentReassembler()
    result = None
    for index, c in enumerate(chunks):
        payload = (fragment_id + index.to_bytes(2, "big") + total.to_bytes(2, "big")
                   + bytes([int(MessageType.FILE_TRANSFER)]) + c)
        frag = BitchatPacket(type=MessageType.FRAGMENT, sender_id=sender, payload=payload)
        result = reasm.add(frag)
    check("file fragments reassemble", result == inner_bytes)
    rebuilt = BitchatPacket.decode(result)
    check("reassembled file packet decodes",
          rebuilt is not None and BitchatFilePacket.decode(rebuilt.payload).content == b"M" * 4000)


def test_mime_helpers():
    check("jpg -> image/jpeg", mime_for_extension(".jpg") == "image/jpeg")
    check("m4a -> audio category", category_for_mime("audio/m4a") == "audio")
    check("mp4 video -> octet-stream", mime_for_extension("mp4") == "application/octet-stream")
    check("octet-stream -> file category", category_for_mime("application/octet-stream") == "file")
    check("image prefix", message_prefix("image") == "[image] ")
    check("audio prefix is [voice]", message_prefix("audio") == "[voice] ")


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
        test_file_packet_roundtrip,
        test_file_packet_oversize_rejected,
        test_file_transfer_packet_wrap,
        test_file_fragment_reassembly,
        test_mime_helpers,
        test_public_message_payload_is_raw,
    ):
        print(f"{test.__name__}:")
        test()
    print(f"\nAll {passed} checks passed. ✅")
