# identity.py
#
# Cryptographic identity for a bitchat session. Public chat is NOT encrypted,
# but every peer must ANNOUNCE two raw public keys and sign its packets so the
# real app will list it as a peer and accept its broadcasts:
#
#   * a static X25519 key  -> "noise" public key (used for the Noise handshake,
#                             which we don't implement; we only advertise it).
#                             The wire peer ID is SHA-256(noise pubkey)[:8].
#   * an Ed25519 signing key -> signs each packet's canonical bytes
#
# This mirrors the key pair stored by NoiseEncryptionService in the Swift app.

import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

_RAW = serialization.Encoding.Raw
_RAW_PUB = serialization.PublicFormat.Raw


def peer_id_from_noise_public_key(noise_public_key: bytes) -> bytes:
    """The 8-byte wire peer ID for a Noise (X25519) public key.

    Both official clients derive a peer's ID as the first 8 bytes of
    SHA-256(noise static public key) and reject ANNOUNCE packets whose
    senderID does not match that derivation. A random sender ID therefore
    makes this client invisible to the real app.
    """
    return hashlib.sha256(noise_public_key).digest()[:8]


def verify_signature(signature: bytes, data: bytes,
                     signing_public_key: bytes) -> bool:
    """Verify an Ed25519 packet signature against a raw 32-byte public key."""
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(signing_public_key).verify(
            signature, data
        )
        return True
    except (InvalidSignature, ValueError):
        return False


class IdentityKeys:
    """Holds a session's X25519 static key and Ed25519 signing key."""

    def __init__(self):
        self._static_key = x25519.X25519PrivateKey.generate()
        self._signing_key = ed25519.Ed25519PrivateKey.generate()

    def noise_public_key_bytes(self) -> bytes:
        """Raw 32-byte X25519 public key for the ANNOUNCE packet."""
        return self._static_key.public_key().public_bytes(
            encoding=_RAW, format=_RAW_PUB
        )

    def peer_id_bytes(self) -> bytes:
        """8-byte peer ID the official apps expect in packet senderIDs."""
        return peer_id_from_noise_public_key(self.noise_public_key_bytes())

    def signing_public_key_bytes(self) -> bytes:
        """Raw 32-byte Ed25519 public key for the ANNOUNCE packet."""
        return self._signing_key.public_key().public_bytes(
            encoding=_RAW, format=_RAW_PUB
        )

    def sign(self, data: bytes) -> bytes:
        """Ed25519 signature (64 bytes) over the packet's canonical bytes."""
        return self._signing_key.sign(data)
