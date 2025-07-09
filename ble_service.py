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
                    if device.address not in self.clients:
                        # Non-blocking connection attempt
                        asyncio.create_task(self.connect_to_device(device))
            except BleakError as e:
                self.state.add_system_message(f"[ERROR] Scan failed: {e}")
            except Exception as e:
                self.state.add_system_message(
                    f"[ERROR] An unexpected error occurred during scan: {e}")
            await asyncio.sleep(5)  # Scan interval

    async def connect_to_device(self, device: BLEDevice):
        """Establishes a connection with a discovered device."""
        self.state.add_system_message(
            f"Found peer: {device.address}. Attempting to connect...")
        client = BleakClient(device, disconnected_callback=self.on_disconnect)
        try:
            await client.connect()
            if client.is_connected:
                self.clients[device.address] = client
                self.state.add_peer(device.address, device.name or "unknown")
                self.cli_redraw()
                await client.start_notify(CHARACTERISTIC_UUID, self.notification_handler)
                # This will keep the connection alive until a disconnect event
                await self.monitor_connection(client)
        except BleakError as e:
            self.state.add_system_message(
                f"[ERROR] Failed to connect to {device.address}: {e}")
        except Exception as e:
            self.state.add_system_message(
                f"[ERROR] Connection error with {device.address}: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()

    def on_disconnect(self, client: BleakClient):
        """Handles peer disconnection."""
        address = client.address
        if address in self.clients:
            del self.clients[address]
        self.state.remove_peer(address)
        self.cli_redraw()

    async def monitor_connection(self, client: BleakClient):
        """A simple task to keep the connection alive by waiting for disconnect."""
        disconnected_event = asyncio.Event()
        client.set_disconnected_callback(lambda _: disconnected_event.set())
        await disconnected_event.wait()

    async def broadcast(self, message: BitchatMessage):
        """Sends a message to all connected peers."""
        packet = BitchatPacket(
            sender_id=self.state.my_peer_id,
            recipient_id=BROADCAST_RECIPIENT,
            payload=message.to_payload()
        )
        data_to_send = packet.pack()

        # Create a list of tasks to send to all peers concurrently
        tasks = []
        for client in self.clients.values():
            if client.is_connected:
                tasks.append(self.send_to_peer(client, data_to_send))

        if tasks:
            await asyncio.gather(*tasks)

    async def send_to_peer(self, client: BleakClient, data: bytes):
        """Sends data to a single peer with error handling."""
        try:
            await client.write_gatt_char(CHARACTERISTIC_UUID, data, response=False)
        except BleakError as e:
            self.state.add_system_message(
                f"[ERROR] Failed to send to {client.address}: {e}")
        except Exception as e:
            self.state.add_system_message(
                f"[ERROR] Unexpected error sending to {client.address}: {e}")
