# ble_service.py
#
# BLE transport for bitchat. Runs `bleak` as a BLE *central*: it scans for
# devices advertising the bitchat service UUID, connects, subscribes to the
# bitchat characteristic for notifications, and writes packets to it.
#
# Scope: public (broadcast) chat only. We announce ourselves and sign every
# packet (the real app drops unsigned public messages), parse inbound announce/
# message/leave/fragment packets, and ignore Noise (private) traffic.
#
# Note: `bleak` is central-only, so this client cannot advertise as a peripheral
# or relay; it interoperates one hop with bitchat peers that are in range while
# it stays connected to them.

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Set

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from . import theme
from .chat_state import ChatState
from .media import (
    BitchatFilePacket,
    MAX_PAYLOAD_BYTES,
    category_for_mime,
    extension_for_mime,
    message_prefix,
    mime_for_extension,
)
from .protocol import (
    AnnouncementPacket,
    BitchatMessage,
    BitchatPacket,
    DEFAULT_TTL,
    FragmentReassembler,
    MessageType,
)

# Real bitchat UUIDs (mainnet). Lower-cased to compare against advertisement data.
SERVICE_UUID = "f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c"
CHARACTERISTIC_UUID = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"

CONNECTION_TIMEOUT = 15.0       # seconds for a single connect attempt
MAX_CONNECT_ATTEMPTS = 3        # before a device is permanently ignored
RETRY_COOLDOWN = 15.0           # seconds to wait before re-attempting a device
ANNOUNCE_INTERVAL = 30.0        # seconds between periodic re-announces
MAX_FRAME_SIZE = 480            # bytes before a packet is fragmented for BLE
FRAGMENT_PACING = 0.005         # seconds between BLE writes when sending a fragment train

# Where received media (images, voice notes, files) is saved.
DOWNLOAD_DIR = Path.home() / ".bitchat" / "downloads"


class BLEService:
    """Central-role BLE transport speaking the real bitchat public-chat protocol."""

    def __init__(self, state: ChatState, cli_redraw_callback):
        self.state = state
        self.cli_redraw = cli_redraw_callback
        self.clients: Dict[str, BleakClient] = {}      # BLE address -> client
        self._connecting: Set[str] = set()
        self._ignored: Set[str] = set()                # confirmed non-peers / dead
        self._attempts: Dict[str, int] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._reassembler = FragmentReassembler()
        self._scanner: BleakScanner = None
        self._running = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def run(self):
        """Start scanning and keep re-announcing while connected."""
        self._running = True
        self._scanner = BleakScanner(
            detection_callback=self._on_detection, service_uuids=[SERVICE_UUID]
        )
        try:
            await self._scanner.start()
        except BleakError as e:
            self._err(f"Could not start Bluetooth scan: {e}. "
                      f"Check that a Bluetooth adapter is present and enabled.")
            return
        self._sys("Scanning for bitchat peers over Bluetooth…")

        try:
            while self._running:
                await asyncio.sleep(ANNOUNCE_INTERVAL)
                if self.clients:
                    await self.send_announce()
        except asyncio.CancelledError:
            raise

    async def stop(self):
        self._running = False
        try:
            if self.clients:
                await self.send_leave()
        except Exception:
            pass
        if self._scanner is not None:
            try:
                await self._scanner.stop()
            except Exception:
                pass
        disconnects = [
            c.disconnect() for c in list(self.clients.values()) if c.is_connected
        ]
        if disconnects:
            await asyncio.gather(*disconnects, return_exceptions=True)

    # ------------------------------------------------------------------ #
    # Discovery & connection (the fix for the "connect to everything" storm)
    # ------------------------------------------------------------------ #
    def _on_detection(self, device: BLEDevice, adv: AdvertisementData):
        if not self._running:
            return
        addr = device.address
        if addr in self.clients or addr in self._connecting or addr in self._ignored:
            return
        if time.monotonic() < self._cooldown_until.get(addr, 0.0):
            return
        # Only connect to devices actually advertising the bitchat service.
        advertised = [u.lower() for u in (adv.service_uuids or [])]
        if SERVICE_UUID not in advertised:
            return
        self._connecting.add(addr)
        asyncio.create_task(self._connect(device))

    async def _connect(self, device: BLEDevice):
        addr = device.address
        attempts = self._attempts.get(addr, 0) + 1
        self._attempts[addr] = attempts
        client = BleakClient(device, disconnected_callback=self._on_disconnect)
        try:
            await asyncio.wait_for(client.connect(), timeout=CONNECTION_TIMEOUT)

            if not self._has_characteristic(client):
                self._sys(f"{addr} is not a bitchat peer; ignoring.")
                self._ignored.add(addr)
                await client.disconnect()
                return

            self.clients[addr] = client
            self.state.add_connection(addr)
            await client.start_notify(CHARACTERISTIC_UUID, self._on_notify)
            self._ok(f"Connected to a bitchat peer ({addr}).")
            await self.send_announce()  # introduce ourselves so they list us
        except (asyncio.TimeoutError, BleakError) as e:
            reason = "timed out" if isinstance(e, asyncio.TimeoutError) else str(e)
            self._fail_device(addr, reason)
            await self._safe_disconnect(client)
        except Exception as e:  # noqa: BLE001 - never let a connect kill the loop
            self._err(f"Unexpected error with {addr}: {e}")
            self._ignored.add(addr)
            await self._safe_disconnect(client)
        finally:
            self._connecting.discard(addr)

    def _fail_device(self, addr: str, reason: str):
        if self._attempts.get(addr, 0) >= MAX_CONNECT_ATTEMPTS:
            self._warn(f"Giving up on {addr} after {MAX_CONNECT_ATTEMPTS} attempts ({reason}).")
            self._ignored.add(addr)
        else:
            self._cooldown_until[addr] = time.monotonic() + RETRY_COOLDOWN

    @staticmethod
    def _has_characteristic(client: BleakClient) -> bool:
        for service in client.services:
            for char in service.characteristics:
                if char.uuid.lower() == CHARACTERISTIC_UUID:
                    return True
        return False

    @staticmethod
    async def _safe_disconnect(client: BleakClient):
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            pass

    def _on_disconnect(self, client: BleakClient):
        addr = client.address
        self.clients.pop(addr, None)
        self._connecting.discard(addr)
        if addr in self.state.connected_addresses:
            self.state.remove_connection(addr)
            self._leave(f"Disconnected from {addr}")

    # ------------------------------------------------------------------ #
    # Inbound packet handling
    # ------------------------------------------------------------------ #
    def _on_notify(self, _characteristic, data: bytearray):
        packet = BitchatPacket.decode(bytes(data))
        if packet is not None:
            self._dispatch(packet)

    def _dispatch(self, packet: BitchatPacket):
        if packet.sender_id == self.state.my_peer_id:
            return  # our own packet relayed back to us

        if packet.type == MessageType.FRAGMENT:
            inner = self._reassembler.add(packet)
            if inner is not None:
                reassembled = BitchatPacket.decode(inner)
                if reassembled is not None:
                    self._dispatch(reassembled)
            return

        if packet.type == MessageType.ANNOUNCE:
            self._handle_announce(packet)
        elif packet.type == MessageType.MESSAGE:
            self._handle_message(packet)
        elif packet.type == MessageType.LEAVE:
            self._handle_leave(packet)
        elif packet.type == MessageType.FILE_TRANSFER:
            self._handle_file(packet)
        # NOISE_HANDSHAKE / NOISE_ENCRYPTED / others: private traffic, ignored.

    def _handle_announce(self, packet: BitchatPacket):
        ann = AnnouncementPacket.decode(packet.payload)
        if ann is None:
            return
        peer_id = packet.sender_id.hex()
        if self.state.set_peer(peer_id, ann.nickname):
            self._join(f"{ann.nickname} is now online")

    def _handle_message(self, packet: BitchatPacket):
        try:
            content = packet.payload.decode("utf-8")
        except UnicodeDecodeError:
            return
        peer_id = packet.sender_id.hex()
        sender = self.state.nickname_for(peer_id)
        self.state.add_message(
            BitchatMessage(content=content, sender=sender, timestamp=packet.timestamp)
        )
        self._chat(sender, content, ts_ms=packet.timestamp)

    def _handle_leave(self, packet: BitchatPacket):
        peer_id = packet.sender_id.hex()
        nickname = self.state.nickname_for(peer_id)
        self.state.remove_peer(peer_id)
        self._leave(f"{nickname} went offline")

    def _handle_file(self, packet: BitchatPacket):
        """Decode a received FILE_TRANSFER payload, save it to disk, auto-open."""
        fp = BitchatFilePacket.decode(packet.payload)
        if fp is None:
            return
        category = category_for_mime(fp.mime_type)
        filename = self._safe_filename(fp.file_name, fp.mime_type)
        try:
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            path = DOWNLOAD_DIR / filename
            path.write_bytes(fp.content)
        except OSError as e:  # noqa: BLE001
            self._warn(f"Failed to save received media: {e}")
            return

        peer_id = packet.sender_id.hex()
        sender = self.state.nickname_for(peer_id)
        content = f"{message_prefix(category)}{filename}"
        self.state.add_message(
            BitchatMessage(content=content, sender=sender, timestamp=packet.timestamp)
        )
        self._media(sender, category, filename, path=path, ts_ms=packet.timestamp)
        self._open_file(path)

    @staticmethod
    def _safe_filename(name, mime) -> str:
        """A safe basename for a received file (no path traversal)."""
        base = os.path.basename(name) if name else ""
        base = base.replace("\x00", "").strip().lstrip(".")
        if not base or base in ("", "."):
            ext = extension_for_mime(mime)
            base = f"{int(time.time() * 1000)}.{ext}"
        return base

    def _open_file(self, path: Path):
        """Best-effort, non-blocking open with the OS default viewer."""
        try:
            if sys.platform == "darwin":
                cmd = ["open", str(path)]
            elif sys.platform.startswith("win"):
                cmd = ["cmd", "/c", "start", "", str(path)]
            else:
                cmd = ["xdg-open", str(path)]
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:  # noqa: BLE001 - opener missing/unavailable is non-fatal
            pass

    # ------------------------------------------------------------------ #
    # Outbound packets
    # ------------------------------------------------------------------ #
    def _sign(self, packet: BitchatPacket) -> BitchatPacket:
        packet.signature = self.state.identity.sign(packet.data_for_signing())
        return packet

    async def send_announce(self):
        ann = AnnouncementPacket(
            nickname=self.state.nickname,
            noise_public_key=self.state.identity.noise_public_key_bytes(),
            signing_public_key=self.state.identity.signing_public_key_bytes(),
        )
        payload = ann.encode()
        if payload is None:
            return
        packet = self._sign(BitchatPacket(
            type=MessageType.ANNOUNCE, sender_id=self.state.my_peer_id,
            recipient_id=None, payload=payload, ttl=DEFAULT_TTL,
        ))
        await self._broadcast(packet)

    async def send_public_message(self, content: str) -> BitchatMessage:
        packet = self._sign(BitchatPacket(
            type=MessageType.MESSAGE, sender_id=self.state.my_peer_id,
            recipient_id=None, payload=content.encode("utf-8"), ttl=DEFAULT_TTL,
        ))
        await self._broadcast(packet)
        message = BitchatMessage(content=content, sender=self.state.nickname)
        self.state.add_message(message)
        self._chat(self.state.nickname, content, is_self=True)
        return message

    async def send_leave(self):
        packet = self._sign(BitchatPacket(
            type=MessageType.LEAVE, sender_id=self.state.my_peer_id,
            recipient_id=None, payload=self.state.nickname.encode("utf-8"),
            ttl=DEFAULT_TTL,
        ))
        await self._broadcast(packet)

    async def send_file(self, path: str):
        """Read a file from disk and broadcast it as a FILE_TRANSFER packet."""
        p = Path(path).expanduser()
        try:
            content = p.read_bytes()
        except OSError as e:  # noqa: BLE001
            self._warn(f"Could not read '{path}': {e}")
            return
        if len(content) > MAX_PAYLOAD_BYTES:
            self._warn(
                f"'{p.name}' is {len(content)} bytes; the limit is "
                f"{MAX_PAYLOAD_BYTES} bytes (1 MiB). Not sent."
            )
            return
        if not content:
            self._warn(f"'{p.name}' is empty. Not sent.")
            return

        mime = mime_for_extension(p.suffix)
        category = category_for_mime(mime)
        fp = BitchatFilePacket(
            content=content, file_name=p.name, file_size=len(content), mime_type=mime,
        )
        payload = fp.encode()
        if payload is None:
            self._warn(f"'{p.name}' could not be encoded for transfer. Not sent.")
            return

        packet = self._sign(BitchatPacket(
            type=MessageType.FILE_TRANSFER, sender_id=self.state.my_peer_id,
            recipient_id=None, payload=payload, ttl=DEFAULT_TTL, version=2,
        ))
        await self._broadcast(packet)

        content_str = f"{message_prefix(category)}{p.name}"
        self.state.add_message(
            BitchatMessage(content=content_str, sender=self.state.nickname)
        )
        self._media(self.state.nickname, category, f"{p.name} ({len(content)} bytes)",
                    is_self=True)

    async def _broadcast(self, packet: BitchatPacket):
        encoded = packet.encode()
        fragmented = len(encoded) > MAX_FRAME_SIZE
        frames = self._fragment(encoded, packet.type) if fragmented else [encoded]
        failed = []  # (addr, reason) of links to tear down after this pass
        for addr, client in list(self.clients.items()):
            if not client.is_connected:
                failed.append((addr, "link down"))
                continue
            for frame in frames:
                try:
                    await client.write_gatt_char(CHARACTERISTIC_UUID, frame, response=False)
                except Exception as e:  # noqa: BLE001
                    # A write error (e.g. BlueZ stale characteristic) means the
                    # link is dead even if is_connected still reports True. Drop
                    # it once rather than retrying on every message/announce.
                    failed.append((addr, str(e)))
                    break
                # Pace long fragment trains so the peer's BLE buffers can drain.
                if fragmented:
                    await asyncio.sleep(FRAGMENT_PACING)
        for addr, reason in failed:
            await self._drop_client(addr, reason)

    async def _drop_client(self, addr: str, reason: str = ""):
        """Tear down a dead link and let the scanner reconnect later."""
        client = self.clients.pop(addr, None)
        if client is None:
            return
        self.state.remove_connection(addr)
        # Hold off immediate reconnection so we don't tight-loop on a bad peer.
        self._cooldown_until[addr] = time.monotonic() + RETRY_COOLDOWN
        self._leave(f"Lost connection to {addr}" + (f" ({reason})" if reason else ""))
        await self._safe_disconnect(client)

    def _fragment(self, encoded_packet: bytes, original_type: int) -> List[bytes]:
        """Split an oversized encoded packet into FRAGMENT packets."""
        fragment_id = os.urandom(8)
        chunk_size = MAX_FRAME_SIZE - 40  # room for fragment + packet headers
        chunks = [encoded_packet[i:i + chunk_size]
                  for i in range(0, len(encoded_packet), chunk_size)]
        total = len(chunks)
        frames = []
        for index, chunk in enumerate(chunks):
            payload = (fragment_id + index.to_bytes(2, "big") + total.to_bytes(2, "big")
                       + bytes([int(original_type)]) + chunk)
            frag = BitchatPacket(
                type=MessageType.FRAGMENT, sender_id=self.state.my_peer_id,
                recipient_id=None, payload=payload, ttl=DEFAULT_TTL,
            )
            frames.append(frag.encode())
        return frames

    # ------------------------------------------------------------------ #
    # Output helpers — all chat/system output flows through here so the
    # styling (see theme.py) stays consistent and the prompt is redrawn.
    # ------------------------------------------------------------------ #
    def _emit(self, line: str):
        print(line)
        self.cli_redraw()

    def _sys(self, msg: str):
        self._emit(theme.system(msg))

    def _ok(self, msg: str):
        self._emit(theme.ok(msg))

    def _warn(self, msg: str):
        self._emit(theme.warn(msg))

    def _err(self, msg: str):
        self._emit(theme.error(msg))

    def _join(self, msg: str):
        self._emit(theme.join(msg))

    def _leave(self, msg: str):
        self._emit(theme.leave(msg))

    def _chat(self, sender: str, content: str, ts_ms=None, is_self: bool = False):
        self._emit(theme.chat(sender, content, ts_ms=ts_ms, is_self=is_self))

    def _media(self, sender: str, category: str, label: str, path=None,
               ts_ms=None, is_self: bool = False):
        self._emit(theme.media(sender, category, label, path=path,
                               ts_ms=ts_ms, is_self=is_self))
