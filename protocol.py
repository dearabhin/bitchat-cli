# protocol.py
import struct
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

# --- Constants based on the original project ---
VERSION = 1
HEADER_SIZE = 13
SENDER_ID_SIZE = 8
RECIPIENT_ID_SIZE = 8
SIGNATURE_SIZE = 64
BROADCAST_RECIPIENT = b'\xff' * RECIPIENT_ID_SIZE

class MessageType(Enum):
    ANNOUNCE = 0x01
    KEY_EXCHANGE = 0x02
    LEAVE = 0x03
    MESSAGE = 0x04

class Flags:
    HAS_RECIPIENT = 0x01
    HAS_SIGNATURE = 0x02

@dataclass
class BitchatPacket:
    """
    Represents a data packet in the bitchat network, mirroring the Swift implementation.
    """
    version: int = VERSION
    type: MessageType = MessageType.MESSAGE
    ttl: int = 7
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    sender_id: bytes = b'\x00' * SENDER_ID_SIZE
    recipient_id: Optional[bytes] = None
    payload: bytes = b''
    signature: Optional[bytes] = None

    def pack(self) -> bytes:
        """Packs the packet into its binary format for transmission."""
        flags = 0
        if self.recipient_id is not None:
            flags |= Flags.HAS_RECIPIENT
        if self.signature is not None:
            flags |= Flags.HAS_SIGNATURE

        header_format = f'>BB B Q B H {SENDER_ID_SIZE}s'
        header = struct.pack(
            header_format,
            self.version,
            self.type.value,
            self.ttl,
            self.timestamp,
            flags,
            len(self.payload),
            self.sender_id
        )

        packed_data = header
        if self.recipient_id:
            packed_data += self.recipient_id
        packed_data += self.payload
        if self.signature:
            packed_data += self.signature

        return packed_data

    @staticmethod
    def unpack(data: bytes) -> Optional['BitchatPacket']:
        """Unpacks binary data into a BitchatPacket object."""
        sender_id_offset = struct.calcsize('>BB B Q B H')
        if len(data) < sender_id_offset + SENDER_ID_SIZE:
            return None

        version, msg_type_val, ttl, timestamp, flags, payload_len = struct.unpack(
            '>BB B Q B H', data[:sender_id_offset]
        )

        if version != VERSION:
            return None

        sender_id = data[sender_id_offset:sender_id_offset + SENDER_ID_SIZE]
        offset = sender_id_offset + SENDER_ID_SIZE

        recipient_id = None
        if flags & Flags.HAS_RECIPIENT:
            if len(data) < offset + RECIPIENT_ID_SIZE:
                return None
            recipient_id = data[offset:offset + RECIPIENT_ID_SIZE]
            offset += RECIPIENT_ID_SIZE

        if len(data) < offset + payload_len:
            return None
        payload = data[offset:offset + payload_len]
        offset += payload_len

        signature = None
        if flags & Flags.HAS_SIGNATURE:
            if len(data) < offset + SIGNATURE_SIZE:
                return None
            signature = data[offset:offset + SIGNATURE_SIZE]

        return BitchatPacket(
            version=version,
            type=MessageType(msg_type_val),
            ttl=ttl,
            timestamp=timestamp,
            sender_id=sender_id,
            recipient_id=recipient_id,
            payload=payload,
            signature=signature
        )

@dataclass
class BitchatMessage:
    """
    Represents a user message payload, mirroring the Swift implementation.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = ""
    content: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    is_private: bool = False
    channel: Optional[str] = None

    def to_payload(self) -> bytes:
        """Serializes the message into a byte payload for the packet."""
        # Simple JSON-like serialization for demonstration.
        # A more compact binary format would be better for production.
        return f"id:{self.id}|s:{self.sender}|c:{self.content}|t:{self.timestamp}|p:{self.is_private}|ch:{self.channel or ''}".encode()

    @staticmethod
    def from_payload(payload: bytes) -> Optional['BitchatMessage']:
        """Deserializes a byte payload into a BitchatMessage."""
        try:
            parts = payload.decode().split('|')
            msg_data = {p.split(':', 1)[0]: p.split(':', 1)[1] for p in parts}
            return BitchatMessage(
                id=msg_data.get('id', ''),
                sender=msg_data.get('s', 'unknown'),
                content=msg_data.get('c', ''),
                timestamp=int(msg_data.get('t', 0)),
                is_private=msg_data.get('p') == 'True',
                channel=msg_data.get('ch') or None
            )
        except (IndexError, ValueError):
            return None