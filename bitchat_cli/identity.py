# identity.py
#
# Cryptographic identity for a bitchat session. Public chat is NOT encrypted,
# but every peer must ANNOUNCE two raw public keys and sign its packets so the
# real app will list it as a peer and accept its broadcasts:
#
#   * a static X25519 key  -> "noise" public key (used for the Noise handshake,
#                             which we don't implement; we only advertise it)
#   * an Ed25519 signing key -> signs each packet's canonical bytes
#
# This mirrors the key pair stored by NoiseEncryptionService in the Swift app.

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

_RAW = serialization.Encoding.Raw
_RAW_PUB = serialization.PublicFormat.Raw


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

    def signing_public_key_bytes(self) -> bytes:
        """Raw 32-byte Ed25519 public key for the ANNOUNCE packet."""
        return self._signing_key.public_key().public_bytes(
            encoding=_RAW, format=_RAW_PUB
        )

    def sign(self, data: bytes) -> bytes:
        """Ed25519 signature (64 bytes) over the packet's canonical bytes."""
        return self._signing_key.sign(data)
