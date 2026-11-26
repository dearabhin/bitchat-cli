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

        # Optional synchronous event listeners (see the WebSocket control API).
        self._listeners = []

    @property
    def my_peer_id_hex(self) -> str:
        return self.my_peer_id.hex()

    # --- Event listeners ---
    def add_listener(self, callback):
        """Register a callback receiving structured state events (dicts)."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback):
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _emit(self, event: dict):
        for callback in list(self._listeners):
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - a listener must not break chat
                pass

    def add_message(self, message: BitchatMessage):
        self.messages.append(message)
        self._emit({"type": "message", **message.to_dict()})

    # --- Peer identity (from ANNOUNCE) ---
    def set_peer(self, peer_id_hex: str, nickname: str) -> bool:
        """Record/update a peer's nickname. Returns True if newly seen."""
        previous = self.peer_nicknames.get(peer_id_hex)
        is_new = previous is None
        self.peer_nicknames[peer_id_hex] = nickname
        if is_new or previous != nickname:
            self._emit({
                "type": "peer_joined" if is_new else "peer_updated",
                "peer_id": peer_id_hex,
                "nickname": nickname,
            })
        return is_new

    def remove_peer(self, peer_id_hex: str):
        nickname = self.peer_nicknames.pop(peer_id_hex, None)
        if nickname is not None:
            self._emit({
                "type": "peer_left",
                "peer_id": peer_id_hex,
                "nickname": nickname,
            })

    def nickname_for(self, peer_id_hex: str) -> str:
        return self.peer_nicknames.get(peer_id_hex, peer_id_hex[:8])

    def set_nickname(self, nickname: str):
        self.nickname = nickname
        self._emit({"type": "nickname", "nickname": nickname})

    def peer_list(self):
        return [
            {"peer_id": peer_id, "nickname": nickname}
            for peer_id, nickname in self.peer_nicknames.items()
        ]

    # --- BLE transport links ---
    def add_connection(self, address: str):
        if address not in self.connected_addresses:
            self.connected_addresses.add(address)
            self._emit({"type": "link_up", "address": address})

    def remove_connection(self, address: str):
        if address in self.connected_addresses:
            self.connected_addresses.discard(address)
            self._emit({"type": "link_down", "address": address})
