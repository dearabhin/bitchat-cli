# ble_service.py
import asyncio
from typing import Dict, Optional

from bleak import BleakClient, BleakScanner, BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from chat_state import ChatState
from protocol import BitchatPacket, MessageType, BitchatMessage, BROADCAST_RECIPIENT

# --- Constants ---
SERVICE_UUID = "F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C"
CHARACTERISTIC_UUID = "A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D"


class BLEService:
    """Manages BLE scanning, connections, and data transfer."""

    def __init__(self, state: ChatState, cli_redraw_callback):
        self.state = state
        self.clients: Dict[str, BleakClient] = {}
        self.cli_redraw = cli_redraw_callback

    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Handles incoming data packets from peers."""
        packet = BitchatPacket.unpack(bytes(data))
        if packet:
            # For simplicity, assuming all messages are public chat messages
            message = BitchatMessage.from_payload(packet.payload)
            if message:
                self.state.add_message(message)
                self.cli_redraw()

    async def scan_and_connect(self):
        """Continuously scans for and connects to bitchat peers."""
        scanner = BleakScanner(service_uuids=[SERVICE_UUID])
        while True:
            try:
                devices = await scanner.discover(timeout=5.0)
                for device in devices:
                    if device.address not in self.clients:
                        await self.connect_to_device(device)
            except Exception as e:
                print(f"Scan error: {e}")
            await asyncio.sleep(5)

    async def connect_to_device(self, device: BLEDevice):
        """Establishes a connection with a discovered device."""
        print(f"Found peer: {device.address}. Attempting to connect...")
        client = BleakClient(device, disconnected_callback=self.on_disconnect)
        try:
            await client.connect()
            if client.is_connected:
                self.clients[device.address] = client
                self.state.add_peer(device.address, device.name or "unknown")
                self.cli_redraw()
                await client.start_notify(CHARACTERISTIC_UUID, self.notification_handler)
                # Keep the connection task running
                asyncio.create_task(self.monitor_connection(client))
        except Exception as e:
            print(f"Failed to connect to {device.address}: {e}")

    def on_disconnect(self, client: BleakClient):
        """Handles peer disconnection."""
        address = client.address
        if address in self.clients:
            del self.clients[address]
        self.state.remove_peer(address)
        self.cli_redraw()

    async def monitor_connection(self, client: BleakClient):
        """A simple task to keep the connection alive."""
        while client.is_connected:
            await asyncio.sleep(1)

    async def broadcast(self, message: BitchatMessage):
        """Sends a message to all connected peers."""
        message.sender = self.state.nickname
        packet = BitchatPacket(
            sender_id=self.state.my_peer_id,
            recipient_id=BROADCAST_RECIPIENT,
            payload=message.to_payload()
        )
        data_to_send = packet.pack()

        for client in self.clients.values():
            if client.is_connected:
                try:
                    await client.write_gatt_char(CHARACTERISTIC_UUID, data_to_send, response=False)
                except Exception as e:
                    print(f"Failed to send to {client.address}: {e}")
