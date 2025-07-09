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
CONNECTION_TIMEOUT = 15.0  # Increased timeout for more reliability
MAX_CONNECT_ATTEMPTS = 3   # Number of times to retry a connection
RETRY_DELAY = 2            # Seconds to wait before retrying


class BLEService:
    """Manages BLE scanning and connections with a robust, retry-based strategy."""

    def __init__(self, state: ChatState, cli_redraw_callback):
        self.state = state
        self.clients: Dict[str, BleakClient] = {}
        self.connecting_peers: set = set()
        self.cli_redraw = cli_redraw_callback

    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Handles incoming data packets from peers."""
        packet = BitchatPacket.unpack(bytes(data))
        if packet and packet.sender_id != self.state.my_peer_id:
            message = BitchatMessage.from_payload(packet.payload)
            if message:
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
                    if device.address not in self.clients and device.address not in self.connecting_peers:
                        self.connecting_peers.add(device.address)
                        asyncio.create_task(self.connect_to_device(device))
            except BleakError as e:
                self.state.add_system_message(
                    f"[ERROR] Scan failed: {e}. Please check your Bluetooth adapter.")
            await asyncio.sleep(5)

    async def connect_to_device(self, device: BLEDevice):
        """Establishes and validates a connection with retries."""
        for attempt in range(MAX_CONNECT_ATTEMPTS):
            try:
                self.state.add_system_message(
                    f"Attempting to connect to {device.address} (Attempt {attempt + 1}/{MAX_CONNECT_ATTEMPTS})...")

                async with asyncio.timeout(CONNECTION_TIMEOUT):
                    client = BleakClient(
                        device, disconnected_callback=self.on_disconnect)
                    await client.connect()

                    if client.is_connected:
                        # Validate the peer has the correct characteristic
                        if any(char.uuid == CHARACTERISTIC_UUID for service in client.services for char in service.characteristics):
                            self.state.add_system_message(
                                f"Peer {device.address} validated. Connection successful.")
                            self.clients[device.address] = client
                            self.state.add_peer(
                                device.address, device.name or "unknown")
                            self.cli_redraw()
                            await client.start_notify(CHARACTERISTIC_UUID, self.notification_handler)
                            # This will block until disconnect
                            await self.monitor_connection(client)
                            return  # Exit successfully
                        else:
                            self.state.add_system_message(
                                f"Device {device.address} is not a valid bitchat peer. Ignoring.")
                            await client.disconnect()
                            return  # Exit, no need to retry for invalid peers

            except asyncio.TimeoutError:
                self.state.add_system_message(
                    f"[WARN] Connection to {device.address} timed out.")
            except BleakError as e:
                self.state.add_system_message(
                    f"[WARN] Connection to {device.address} failed: {e}")
            except Exception as e:
                self.state.add_system_message(
                    f"[ERROR] An unexpected error occurred with {device.address}: {e}")
                break  # Don't retry on unexpected errors

            # If not the last attempt, wait before retrying
            if attempt < MAX_CONNECT_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY)

        self.state.add_system_message(
            f"Failed to connect to {device.address} after {MAX_CONNECT_ATTEMPTS} attempts.")
        self.connecting_peers.discard(device.address)

    def on_disconnect(self, client: BleakClient):
        """Handles peer disconnection and cleans up resources."""
        address = client.address
        if address in self.clients:
            del self.clients[address]
        self.connecting_peers.discard(address)
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

        tasks = [
            client.write_gatt_char(CHARACTERISTIC_UUID,
                                   data_to_send, response=False)
            for client in self.clients.values() if client.is_connected
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
