# media.py
#
# Pure (no-I/O) helpers for bitchat file transfers: voice notes, images, and
# generic files. Mirrors the real app's wire format so the CLI interoperates for
# public/broadcast media:
#
#   - BitchatFilePacket  : the TLV payload carried inside a FILE_TRANSFER (0x22)
#                          packet (see BitchatFilePacket.swift upstream).
#   - MIME helpers       : map between file extension, MIME string, and the
#                          three categories the app recognises (image / audio /
#                          file), plus the chat-bubble prefix each uses
#                          (see MimeType.swift upstream).
#
# All disk and process I/O (reading a file to send, writing a received file,
# auto-opening it) lives in ble_service.py; this module is just data + bytes.

from dataclasses import dataclass
from typing import Optional

# Absolute ceiling enforced for any file payload (matches FileTransferLimits.swift).
MAX_PAYLOAD_BYTES = 1 * 1024 * 1024  # 1 MiB

# Generic fallback MIME used when an extension isn't recognised (e.g. video).
OCTET_STREAM = "application/octet-stream"


# --------------------------------------------------------------------------- #
# BitchatFilePacket (TLV payload of a FILE_TRANSFER packet)
# --------------------------------------------------------------------------- #
class _FileTLV:
    FILE_NAME = 0x01
    FILE_SIZE = 0x02
    MIME_TYPE = 0x03
    CONTENT = 0x04


@dataclass
class BitchatFilePacket:
    """TLV payload for a Bluetooth-mesh file transfer (voice note, image, file).

    Wire layout (big-endian lengths), matching the Android/iOS spec:
      0x01 fileName  : UInt16 length, UTF-8                       (optional)
      0x02 fileSize  : length=4, UInt32 value                     (required)
      0x03 mimeType  : UInt16 length, UTF-8                       (optional)
      0x04 content   : UInt32 length, raw bytes                   (required)
    """

    content: bytes
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None

    def encode(self) -> Optional[bytes]:
        """Serialize to the canonical v2 TLV form. Returns None if too large."""
        resolved_size = self.file_size if self.file_size is not None else len(self.content)
        if resolved_size > MAX_PAYLOAD_BYTES or len(self.content) > MAX_PAYLOAD_BYTES:
            return None
        if resolved_size > 0xFFFFFFFF or len(self.content) > 0xFFFFFFFF:
            return None

        out = bytearray()

        if self.file_name is not None:
            name_b = self.file_name.encode("utf-8")
            if len(name_b) <= 0xFFFF:
                out.append(_FileTLV.FILE_NAME)
                out += len(name_b).to_bytes(2, "big")
                out += name_b

        out.append(_FileTLV.FILE_SIZE)
        out += (4).to_bytes(2, "big")
        out += resolved_size.to_bytes(4, "big")

        if self.mime_type is not None:
            mime_b = self.mime_type.encode("utf-8")
            if len(mime_b) <= 0xFFFF:
                out.append(_FileTLV.MIME_TYPE)
                out += len(mime_b).to_bytes(2, "big")
                out += mime_b

        out.append(_FileTLV.CONTENT)
        out += len(self.content).to_bytes(4, "big")
        out += self.content

        return bytes(out)

    @staticmethod
    def decode(data: bytes) -> Optional["BitchatFilePacket"]:
        """Parse the TLV payload, tolerating legacy length encodings.

        Content length is read as 4 bytes (canonical) with a 2-byte fallback;
        fileSize accepts length 4 or 8. Returns None on malformed/empty content.
        """
        cursor = 0
        end = len(data)

        file_name = None
        file_size = None
        mime_type = None
        content = bytearray()

        while cursor < end:
            tlv_type = data[cursor]
            cursor += 1

            if tlv_type == _FileTLV.CONTENT:
                # Canonical 4-byte length, falling back to legacy 2-byte.
                length = None
                if end - cursor >= 4:
                    candidate = int.from_bytes(data[cursor:cursor + 4], "big")
                    if candidate <= end - cursor - 4:
                        length = candidate
                        cursor += 4
                if length is None:
                    if end - cursor < 2:
                        return None
                    length = int.from_bytes(data[cursor:cursor + 2], "big")
                    cursor += 2
            else:
                if end - cursor < 2:
                    return None
                length = int.from_bytes(data[cursor:cursor + 2], "big")
                cursor += 2

            if length < 0 or end - cursor < length:
                return None
            value = data[cursor:cursor + length]
            cursor += length

            if tlv_type == _FileTLV.FILE_NAME:
                file_name = value.decode("utf-8", "replace")
            elif tlv_type == _FileTLV.FILE_SIZE:
                if length in (4, 8):
                    size = int.from_bytes(value, "big")
                    if size > MAX_PAYLOAD_BYTES:
                        return None
                    file_size = size
            elif tlv_type == _FileTLV.MIME_TYPE:
                mime_type = value.decode("utf-8", "replace")
            elif tlv_type == _FileTLV.CONTENT:
                if len(content) + len(value) > MAX_PAYLOAD_BYTES:
                    return None
                content += value
            # Unknown TLVs are skipped for forward-compatibility.

        if not content:
            return None
        return BitchatFilePacket(
            content=bytes(content),
            file_name=file_name,
            file_size=file_size if file_size is not None else len(content),
            mime_type=mime_type,
        )


# --------------------------------------------------------------------------- #
# MIME table (mirrors MimeType.swift)
# --------------------------------------------------------------------------- #
# category -> chat-bubble prefix (each ends with a trailing space, like upstream).
_CATEGORY_PREFIX = {
    "image": "[image] ",
    "audio": "[voice] ",
    "file": "[file] ",
}

# Canonical MIME string -> (category, default file extension).
_MIME_INFO = {
    "image/jpeg": ("image", "jpg"),
    "image/png": ("image", "png"),
    "image/gif": ("image", "gif"),
    "image/webp": ("image", "webp"),
    "audio/mp4": ("audio", "m4a"),
    "audio/m4a": ("audio", "m4a"),
    "audio/aac": ("audio", "m4a"),
    "audio/mpeg": ("audio", "mp3"),
    "audio/mp3": ("audio", "mp3"),
    "audio/wav": ("audio", "wav"),
    "audio/x-wav": ("audio", "wav"),
    "audio/ogg": ("audio", "ogg"),
    "application/pdf": ("file", "pdf"),
    OCTET_STREAM: ("file", "bin"),
}

# File extension -> canonical MIME string (for the send path).
_EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "m4a": "audio/m4a",
    "aac": "audio/aac",
    "mp4": OCTET_STREAM,   # video: carried as a generic file (no upstream video type)
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "pdf": "application/pdf",
}


def mime_for_extension(ext: str) -> str:
    """MIME string for a bare file extension (no dot). Falls back to octet-stream."""
    return _EXT_TO_MIME.get(ext.lower().lstrip("."), OCTET_STREAM)


def category_for_mime(mime: Optional[str]) -> str:
    """One of 'image', 'audio', 'file' for a MIME string (unknown -> 'file')."""
    if mime:
        info = _MIME_INFO.get(mime.lower())
        if info:
            return info[0]
    return "file"


def extension_for_mime(mime: Optional[str]) -> str:
    """Default file extension (no dot) for a MIME string (unknown -> 'bin')."""
    if mime:
        info = _MIME_INFO.get(mime.lower())
        if info:
            return info[1]
    return "bin"


def message_prefix(category: str) -> str:
    """Chat-bubble prefix for a category, e.g. 'image' -> '[image] '."""
    return _CATEGORY_PREFIX.get(category, _CATEGORY_PREFIX["file"])
