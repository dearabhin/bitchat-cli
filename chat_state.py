# chat_state.py
from typing import Dict, List, Optional, Set
from protocol import BitchatMessage


class ChatState:
    """Manages the application's state, equivalent to ChatViewModel."""

    def __init__(self, nickname: str, my_peer_id: bytes):
        self.nickname = nickname
        self.my_peer_id = my_peer_id
        self.messages: List[BitchatMessage] = []
        self.connected_peers: Set[str] = set()
        self.peer_nicknames: Dict[str, str] = {}
        self.current_channel: Optional[str] = None

    def add_message(self, message: BitchatMessage):
        """Adds a message to the chat history."""
        self.messages.append(message)

    def add_peer(self, peer_address: str, peer_nickname: str = "unknown"):
        """Adds a peer to the state."""
        if peer_address not in self.connected_peers:
            self.connected_peers.add(peer_address)
            self.peer_nicknames[peer_address] = peer_nickname

    def remove_peer(self, peer_address: str):
        """Removes a peer from the state."""
        if peer_address in self.connected_peers:
            self.connected_peers.remove(peer_address)
            self.peer_nicknames.pop(peer_address, None)
