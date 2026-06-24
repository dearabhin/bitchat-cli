# chat_state.py
from typing import Dict, List, Set

from .identity import IdentityKeys
from .protocol import BitchatMessage


class ChatState:
    """In-memory application state shared between the CLI and the BLE service."""

    def __init__(self, nickname: str, my_peer_id: bytes):
        self.nickname = nickname
        self.my_peer_id = my_peer_id              # 8 random bytes
        self.identity = IdentityKeys()
        self.messages: List[BitchatMessage] = []

        # Peers are identified by their 8-byte peer ID (hex), learned from
        # ANNOUNCE packets — NOT by BLE MAC address.
        self.peer_nicknames: Dict[str, str] = {}  # peer_id_hex -> nickname

        # BLE transport connections, tracked separately for link management.
        self.connected_addresses: Set[str] = set()

    @property
    def my_peer_id_hex(self) -> str:
        return self.my_peer_id.hex()

    def add_message(self, message: BitchatMessage):
        self.messages.append(message)

    # --- Peer identity (from ANNOUNCE) ---
    def set_peer(self, peer_id_hex: str, nickname: str) -> bool:
        """Record/update a peer's nickname. Returns True if newly seen."""
        is_new = peer_id_hex not in self.peer_nicknames
        self.peer_nicknames[peer_id_hex] = nickname
        return is_new

    def remove_peer(self, peer_id_hex: str):
        self.peer_nicknames.pop(peer_id_hex, None)

    def nickname_for(self, peer_id_hex: str) -> str:
        return self.peer_nicknames.get(peer_id_hex, peer_id_hex[:8])

    # --- BLE transport links ---
    def add_connection(self, address: str):
        self.connected_addresses.add(address)

    def remove_connection(self, address: str):
        self.connected_addresses.discard(address)
