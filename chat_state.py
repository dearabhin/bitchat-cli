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

    def add_message(self, message: BitchatMessage, is_own_message: bool = False):
        """Adds a message to the chat history and prints it."""
        self.messages.append(message)
        # The CLI class now handles printing to prevent messy output.
        # This logic is handled in the CLI run loop.
        if is_own_message:
            print(f"\n<You>: {message.content}")
        else:
            print(f"\n<{message.sender}>: {message.content}")

    def add_system_message(self, content: str):
        """Adds and prints a system message."""
        # System messages are printed directly for immediate feedback.
        print(f"[SYSTEM] {content}")

    def add_peer(self, peer_address: str, peer_nickname: str = "unknown"):
        """Adds a peer and notifies the user."""
        if peer_address not in self.connected_peers:
            self.connected_peers.add(peer_address)
            self.peer_nicknames[peer_address] = peer_nickname
            self.add_system_message(
                f"Peer '{peer_nickname}' ({peer_address}) has connected.")

    def remove_peer(self, peer_address: str):
        """Removes a peer and notifies the user."""
        if peer_address in self.connected_peers:
            self.connected_peers.remove(peer_address)
            nickname = self.peer_nicknames.pop(peer_address, peer_address)
            self.add_system_message(f"Peer '{nickname}' has disconnected.")
