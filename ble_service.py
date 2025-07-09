# ble_service.py
import asyncio
from typing import Dict
from bleak import BleakClient, BleakScanner, BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from chat_state import ChatState
from protocol import BitchatPacket, BitchatMessage, BROADCAST_RECIPIENT

# --- Constants ---
SERVICE_UUID = "F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C"
CHARACTERISTIC_UUID = "A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D"
CONNECTION_TIMEOUT = 10.0  # seconds


class BLEService:
    """Manages BLE scanning, connections, and data transfer with improved stability."""

    def __init__(self, state: ChatState, cli_redraw_callback):
        self.state = state
        self.clients: Dict[str, BleakClient] = {}
        self.connecting_peers: set = set()  # Keep track of connection attempts
        self.cli_redraw = cli_redraw_callback

    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Handles incoming data packets from peers."""
        packet = BitchatPacket.unpack(bytes(data))
        if packet:
            message = BitchatMessage.from_payload(packet.payload)
            if message:
                # Make sure the sender is not ourselves
                if packet.sender_id != self.state.my_peer_id:
                    self.state.add_message(message)
                    self.cli_redraw()

    async def scan_and_connect(self):
        """Continuously scans for and connects to bitchat peers."""
        scanner = BleakScanner(service_uuids=[SERVICE_UUID])
        self.state.add_system_message("Scanner started...")
        while True:
            try:
                devices = await scanner.discover(timeout=5.0)
                for device in devices:
                    # Attempt to connect only if not already connected or attempting
                    if device.address not in self.clients and device.address not in self.connecting_peers:
                        self.connecting_peers.add(device.address)
                        asyncio.create_task(self.connect_to_device(device))
            except BleakError as e:
                self.state.add_system_message(
                    f"[ERROR] Scan failed: {e}. Please check your Bluetooth adapter.")
            await asyncio.sleep(5)

    async def connect_to_device(self, device: BLEDevice):
        """Establishes and validates a connection with a discovered device."""
        self.state.add_system_message(
            f"Found peer: {device.address}. Validating...")

        client = BleakClient(device, disconnected_callback=self.on_disconnect)
        try:
            await asyncio.wait_for(client.connect(), timeout=CONNECTION_TIMEOUT)

            if client.is_connected:
                # IMPORTANT: Validate that this is a true bitchat peer
                # by checking for the specific characteristic.
                chat_char = None
                for service in client.services:
                    for char in service.characteristics:
                        if char.uuid == CHARACTERISTIC_UUID:
                            chat_char = char
                            break
                    if chat_char:
                        break

                if not chat_char:
                    # This is not a valid bitchat peer, disconnect silently.
                    self.state.add_system_message(
                        f"Device {device.address} is not a valid bitchat peer. Ignoring.")
                    await client.disconnect()
                    return

                # If validation passes, we have a real peer!
                self.clients[device.address] = client
                self.state.add_peer(device.address, device.name or "unknown")
                self.cli_redraw()

                await client.start_notify(chat_char, self.notification_handler)

                # Keep the connection alive by waiting for a disconnect event.
                await self.monitor_connection(client)

        except asyncio.TimeoutError:
            self.state.add_system_message(
                f"[WARN] Connection attempt to {device.address} timed out.")
        except BleakError as e:
            # This will catch "Device not found" and other BLE-related issues
            self.state.add_system_message(
                f"[WARN] Failed to connect to {device.address}: {e}")
        except Exception as e:
            self.state.add_system_message(
                f"[ERROR] Unexpected connection error with {device.address}: {e}")
        finally:
            # Ensure the peer is removed from the "connecting" set
            self.connecting_peers.discard(device.address)
            if client.is_connected and device.address not in self.clients:
                await client.disconnect()

    def on_disconnect(self, client: BleakClient):
        """Handles peer disconnection and cleans up resources."""
        address = client.address
        if address in self.clients:
            del self.clients[address]

        self.state.remove_peer(address)
        self.cli_redraw()

    async def monitor_connection(self, client: BleakClient):
        """Waits until the client is disconnected."""
        while client.is_connected:
            await asyncio.sleep(1)

    async def broadcast(self, message: BitchatMessage):
        """Sends a message to all connected and validated peers."""
        message.sender = self.state.nickname
        packet = BitchatPacket(
            sender_id=self.state.my_peer_id,
            recipient_id=BROADCAST_RECIPIENT,
            payload=message.to_payload()
        )
        data_to_send = packet.pack()

        tasks = []
        for client in self.clients.values():
            if client.is_connected:
                tasks.append(
                    client.write_gatt_char(
                        CHARACTERISTIC_UUID, data_to_send, response=False)
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
