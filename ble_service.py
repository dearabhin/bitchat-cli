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
import time
from typing import Dict, List, Set

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from chat_state import ChatState
from protocol import (
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
            self._sys(f"[ERROR] Could not start Bluetooth scan: {e}. "
                      f"Check that a Bluetooth adapter is present and enabled.")
            return
        self._sys("Scanning for bitchat peers over Bluetooth...")

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
            self._sys(f"Connected to a bitchat peer ({addr}).")
            await self.send_announce()  # introduce ourselves so they list us
        except (asyncio.TimeoutError, BleakError) as e:
            reason = "timed out" if isinstance(e, asyncio.TimeoutError) else str(e)
            self._fail_device(addr, reason)
            await self._safe_disconnect(client)
        except Exception as e:  # noqa: BLE001 - never let a connect kill the loop
            self._sys(f"[ERROR] Unexpected error with {addr}: {e}")
            self._ignored.add(addr)
            await self._safe_disconnect(client)
        finally:
            self._connecting.discard(addr)

    def _fail_device(self, addr: str, reason: str):
        if self._attempts.get(addr, 0) >= MAX_CONNECT_ATTEMPTS:
            self._sys(f"Giving up on {addr} after {MAX_CONNECT_ATTEMPTS} attempts ({reason}).")
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
            self._sys(f"Disconnected from {addr}.")

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
        # NOISE_HANDSHAKE / NOISE_ENCRYPTED / others: private traffic, ignored.

    def _handle_announce(self, packet: BitchatPacket):
        ann = AnnouncementPacket.decode(packet.payload)
        if ann is None:
            return
        peer_id = packet.sender_id.hex()
        if self.state.set_peer(peer_id, ann.nickname):
            self._sys(f"'{ann.nickname}' is now online.")

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
        self._print(f"<{sender}>: {content}")

    def _handle_leave(self, packet: BitchatPacket):
        peer_id = packet.sender_id.hex()
        nickname = self.state.nickname_for(peer_id)
        self.state.remove_peer(peer_id)
        self._sys(f"'{nickname}' went offline.")

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
        return message

    async def send_leave(self):
        packet = self._sign(BitchatPacket(
            type=MessageType.LEAVE, sender_id=self.state.my_peer_id,
            recipient_id=None, payload=self.state.nickname.encode("utf-8"),
            ttl=DEFAULT_TTL,
        ))
        await self._broadcast(packet)

    async def _broadcast(self, packet: BitchatPacket):
        encoded = packet.encode()
        frames = [encoded] if len(encoded) <= MAX_FRAME_SIZE else self._fragment(encoded, packet.type)
        for addr, client in list(self.clients.items()):
            if not client.is_connected:
                continue
            for frame in frames:
                try:
                    await client.write_gatt_char(CHARACTERISTIC_UUID, frame, response=False)
                except Exception as e:  # noqa: BLE001
                    self._sys(f"[WARN] Failed to send to {addr}: {e}")
                    break

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
    # Output helpers
    # ------------------------------------------------------------------ #
    def _sys(self, msg: str):
        print(f"\n[SYSTEM] {msg}")
        self.cli_redraw()

    def _print(self, msg: str):
        print(f"\n{msg}")
        self.cli_redraw()
