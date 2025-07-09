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
        """Adds a message to the chat history and prints it."""
        self.messages.append(message)
        # In a real CLI, this would be handled by the CLI class to prevent
        # messy output. For now, we print directly.
        print(f"\n[{message.sender}]: {message.content}")

    def add_system_message(self, content: str):
        """Adds a system message to the chat history."""
        sys_msg = BitchatMessage(sender="system", content=content)
        self.add_message(sys_msg)

    def add_peer(self, peer_address: str, peer_nickname: str = "unknown"):
        self.connected_peers.add(peer_address)
        self.peer_nicknames[peer_address] = peer_nickname
        self.add_system_message(
            f"{peer_nickname} ({peer_address}) has connected.")

    def remove_peer(self, peer_address: str):
        if peer_address in self.connected_peers:
            self.connected_peers.remove(peer_address)
            nickname = self.peer_nicknames.pop(peer_address, peer_address)
            self.add_system_message(f"{nickname} has disconnected.")
