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
                # Display the message and redraw the prompt
                print(f"\n<{message.sender}>: {message.content}")
                self.cli_redraw()

    async def scan_and_connect(self):
        """Continuously scans for and connects to bitchat peers."""
        scanner = BleakScanner(service_uuids=[SERVICE_UUID])
        print("[SYSTEM] Scanner started...")
        while True:
            try:
                devices = await scanner.discover(timeout=5.0)
                for device in devices:
                    if device.address not in self.clients and device.address not in self.connecting_peers:
                        self.connecting_peers.add(device.address)
                        asyncio.create_task(self.connect_to_device(device))
            except BleakError as e:
                print(
                    f"[SYSTEM] [ERROR] Scan failed: {e}. Please check your Bluetooth adapter.")
            await asyncio.sleep(5)

    async def connect_to_device(self, device: BLEDevice):
        """Establishes and validates a connection with retries."""
        for attempt in range(MAX_CONNECT_ATTEMPTS):
            try:
                print(
                    f"[SYSTEM] Attempting to connect to {device.address} (Attempt {attempt + 1}/{MAX_CONNECT_ATTEMPTS})...")
                self.cli_redraw()

                client = BleakClient(
                    device, disconnected_callback=self.on_disconnect)
                async with asyncio.timeout(CONNECTION_TIMEOUT):
                    await client.connect()

                if client.is_connected:
                    # Validate the peer has the correct characteristic
                    if any(char.uuid == CHARACTERISTIC_UUID for service in client.services for char in service.characteristics):
                        peer_name = device.name or "unknown"
                        print(
                            f"[SYSTEM] Peer {peer_name} ({device.address}) validated. Connection successful.")
                        self.clients[device.address] = client
                        self.state.add_peer(device.address, peer_name)
                        await client.start_notify(CHARACTERISTIC_UUID, self.notification_handler)
                        self.cli_redraw()
                        return  # Success, exit the retry loop and function
                    else:
                        print(
                            f"[SYSTEM] Device {device.address} is not a valid bitchat peer. Ignoring.")
                        await client.disconnect()
                        # No need to retry for invalid peers
                        return
            except asyncio.TimeoutError:
                print(
                    f"[SYSTEM] [WARN] Connection to {device.address} timed out.")
            except BleakError as e:
                print(
                    f"[SYSTEM] [WARN] Connection to {device.address} failed: {e}")
            except Exception as e:
                print(
                    f"[SYSTEM] [ERROR] An unexpected error occurred with {device.address}: {e}")
                break  # Don't retry on unexpected errors
            finally:
                # If we are not connected after an attempt, ensure the client is cleaned up
                if not client.is_connected:
                    # Bleak may not call on_disconnect for a failed connect attempt
                    self.on_disconnect(client)

            if attempt < MAX_CONNECT_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY)

        print(
            f"[SYSTEM] Failed to connect to {device.address} after {MAX_CONNECT_ATTEMPTS} attempts.")
        self.cli_redraw()

    def on_disconnect(self, client: BleakClient):
        """Handles peer disconnection and cleans up resources."""
        address = client.address
        # This callback can be triggered for devices we failed to connect to,
        # so we check if they were ever truly 'connected'.
        if address in self.state.connected_peers:
            nickname = self.state.peer_nicknames.get(address, address)
            self.state.remove_peer(address)
            print(f"\n[SYSTEM] Peer '{nickname}' has disconnected.")
            self.cli_redraw()

        if address in self.clients:
            del self.clients[address]
        self.connecting_peers.discard(address)

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
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_client_addr = list(self.clients.keys())[i]
                    print(
                        f"[SYSTEM] [ERROR] Failed to send message to {failed_client_addr}: {result}")
