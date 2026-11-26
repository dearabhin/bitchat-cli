# ws_server.py
#
# Optional WebSocket control surface for automation.
#
# Every event and command is a JSON object (one per WebSocket text message).
# The server is off unless the CLI is started with --ws. It binds to loopback
# by default; binding to any other interface requires --ws-token.
#
# Events pushed to clients:
#   snapshot      full state when a client (authenticates and) connects
#   message       a public message was sent or received
#   peer_joined / peer_updated / peer_left
#   link_up / link_down      BLE connections came and went
#   nickname      local nickname changed
#   ack / error / pong       replies to client commands (carry request ids)
#
# Commands accepted from clients:
#   {"type":"send","content":"hi","id":"1"}       broadcast a public message
#   {"type":"send_file","path":"/tmp/a.png"}      broadcast image/voice/file
#   {"type":"set_nickname","nickname":"bot"}      rename + re-announce
#   {"type":"announce"}                           re-announce now
#   {"type":"peers"}                              peer list
#   {"type":"history","limit":50}                 recent messages
#   {"type":"ping"}                               liveness check
#   {"type":"auth","token":"..."}                 only when a token is set

import asyncio
import hmac
import json
import logging
from typing import Any, Dict, Optional

try:  # websockets >= 13 (the asyncio implementation)
    from websockets.asyncio.server import serve as _ws_serve
except ImportError:  # websockets 12 and older
    from websockets import serve as _ws_serve

from . import __version__
from .chat_state import ChatState

log = logging.getLogger("bitchat.ws")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
AUTH_TIMEOUT = 10.0
CLIENT_QUEUE_MAX = 500
HISTORY_DEFAULT = 50
HISTORY_MAX = 500


def is_loopback_host(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost") or host.startswith("127.")


class WebSocketServer:
    """Serves the chat as JSON events and accepts control commands."""

    def __init__(self, state: ChatState, ble_service, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, token: Optional[str] = None):
        self.state = state
        self.ble = ble_service
        self.host = host
        self.port = port
        self.token = token or None
        self._server = None
        self._clients: Dict[Any, asyncio.Queue] = {}
        self._started = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self):
        """Bind the socket and start delivering events."""
        if self._server is not None:
            return
        if not is_loopback_host(self.host) and not self.token:
            raise RuntimeError(
                f"refusing to listen on {self.host} without --ws-token"
            )
        self.state.add_listener(self._on_state_event)
        try:
            self._server = await _ws_serve(
                self._handler, self.host, self.port,
                ping_interval=20, ping_timeout=20, max_queue=32,
                # Without a token, accept only clients that send no Origin
                # header. This stops a random web page from driving the CLI
                # over ws://127.0.0.1. With a token, a browser UI is allowed.
                origins=[None] if self.token is None else None,
            )
        except Exception:
            self.state.remove_listener(self._on_state_event)
            raise
        sockets = getattr(self._server, "sockets", None) or []
        if sockets:
            self.port = sockets[0].getsockname()[1]
        self._started.set()
        log.info("WebSocket control listening on ws://%s:%s",
                 self.host, self.port)

    async def wait_closed(self):
        if self._server is not None:
            await self._server.wait_closed()

    async def run(self):
        await self.start()
        await self.wait_closed()

    async def stop(self):
        server, self._server = self._server, None
        if server is not None:
            server.close()
            try:
                await server.wait_closed()
            except Exception:  # noqa: BLE001 - already closing
                pass
        self.state.remove_listener(self._on_state_event)

    # ------------------------------------------------------------------ #
    # State -> clients
    # ------------------------------------------------------------------ #
    def _on_state_event(self, event: dict):
        # Called synchronously from ChatState on the event loop. Offering
        # directly (rather than via a task) keeps state events and command
        # acks in program order for each client.
        for queue in list(self._clients.values()):
            self._offer(queue, event)

    @staticmethod
    def _offer(queue: asyncio.Queue, event: dict):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # A slow client must not stall the chat: drop its oldest event.
            try:
                queue.get_nowait()
                queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    # ------------------------------------------------------------------ #
    # Client handling
    # ------------------------------------------------------------------ #
    async def _handler(self, ws):
        queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_MAX)
        self._clients[ws] = queue
        writer = asyncio.create_task(self._writer(ws, queue))
        try:
            if self.token is not None:
                await ws.send(json.dumps({"type": "auth_required"}))
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
                except asyncio.TimeoutError:
                    await ws.close(code=4001, reason="authentication timeout")
                    return
                msg = self._parse(raw)
                if (msg is None or msg.get("type") != "auth"
                        or not self._token_ok(msg.get("token"))):
                    await ws.send(json.dumps(
                        {"type": "error", "error": "authentication failed"}
                    ))
                    await ws.close(code=4003, reason="authentication failed")
                    return
                self._offer(queue, {"type": "auth_ok"})

            self._offer(queue, self._snapshot())

            async for raw in ws:
                msg = self._parse(raw)
                if msg is None:
                    self._offer(queue, {
                        "type": "error", "error": "invalid JSON object",
                    })
                    continue
                await self._handle_command(queue, msg)
        except Exception as e:  # noqa: BLE001 - connection-level failures
            log.debug("WebSocket client ended: %s", e)
        finally:
            self._clients.pop(ws, None)
            writer.cancel()
            try:
                await writer
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _writer(self, ws, queue: asyncio.Queue):
        while True:
            event = await queue.get()
            try:
                await ws.send(json.dumps(event, separators=(",", ":")))
            except Exception:  # noqa: BLE001 - client went away
                return

    def _token_ok(self, supplied) -> bool:
        if self.token is None:
            return True
        return (isinstance(supplied, str)
                and hmac.compare_digest(supplied, self.token))

    @staticmethod
    def _parse(raw) -> Optional[dict]:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return msg if isinstance(msg, dict) else None

    def _snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "version": __version__,
            "nickname": self.state.nickname,
            "peer_id": self.state.my_peer_id_hex,
            "peers": self.state.peer_list(),
            "links": sorted(self.state.connected_addresses),
            "history": [m.to_dict() for m in self.state.messages[-HISTORY_DEFAULT:]],
        }

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #
    async def _handle_command(self, queue: asyncio.Queue, msg: dict):
        request_id = msg.get("id")
        kind = msg.get("type")

        def ack(ok: bool, error: Optional[str] = None, **extra):
            reply = {"type": "ack", "request_id": request_id, "ok": ok}
            if error:
                reply["error"] = error
            reply.update(extra)
            self._offer(queue, reply)

        if kind == "send":
            content = msg.get("content")
            if not isinstance(content, str) or not content.strip():
                return ack(False, "content must be a non-empty string")
            message = await self.ble.send_public_message(content)
            return ack(True, message=message.to_dict(),
                       links=len(getattr(self.ble, "clients", None) or {}))

        if kind == "send_file":
            path = msg.get("path")
            if not isinstance(path, str) or not path:
                return ack(False, "path must be a non-empty string")
            ok, error = await self.ble.send_file(path)
            return ack(ok, error)

        if kind == "set_nickname":
            nickname = msg.get("nickname")
            if not isinstance(nickname, str) or not nickname.strip():
                return ack(False, "nickname must be a non-empty string")
            nickname = nickname.strip()
            if len(nickname.encode("utf-8")) > 255:
                return ack(False, "nickname is longer than 255 bytes")
            self.state.set_nickname(nickname)
            await self.ble.send_announce()
            return ack(True)

        if kind == "announce":
            await self.ble.send_announce()
            return ack(True)

        if kind == "peers":
            self._offer(queue, {
                "type": "peers", "request_id": request_id,
                "peers": self.state.peer_list(),
                "links": sorted(self.state.connected_addresses),
            })
            return None

        if kind == "history":
            try:
                limit = int(msg.get("limit", HISTORY_DEFAULT))
            except (TypeError, ValueError):
                return ack(False, "limit must be an integer")
            limit = max(1, min(limit, HISTORY_MAX))
            self._offer(queue, {
                "type": "history", "request_id": request_id,
                "messages": [m.to_dict() for m in self.state.messages[-limit:]],
            })
            return None

        if kind == "ping":
            self._offer(queue, {"type": "pong", "request_id": request_id})
            return None

        if kind == "auth":
            # Already authenticated (token is None) or a duplicate auth frame.
            if self.token is None or self._token_ok(msg.get("token")):
                return ack(True)
            return ack(False, "authentication failed")

        return ack(False, f"unknown command: {kind!r}")
