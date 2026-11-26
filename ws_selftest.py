# ws_selftest.py
#
# Offline checks for the WebSocket control API. No Bluetooth is involved: a
# fake BLE service records what the API asks it to send.
#
#   pip install ".[ws]"
#   python ws_selftest.py

import asyncio
import json
import os

try:  # websockets >= 13
    from websockets.asyncio.client import connect
except ImportError:  # websockets 12 and older
    from websockets import connect

from bitchat_cli.chat_state import ChatState
from bitchat_cli.protocol import BitchatMessage
from bitchat_cli.ws_server import WebSocketServer


class FakeBLE:
    """Records sends instead of touching Bluetooth."""

    def __init__(self, state):
        self.state = state
        self.clients = {}
        self.sent = []
        self.files = []
        self.announces = 0

    async def send_public_message(self, content):
        self.sent.append(content)
        message = BitchatMessage(
            content=content, sender=self.state.nickname,
            sender_id=self.state.my_peer_id_hex, is_self=True,
        )
        self.state.add_message(message)
        return message

    async def send_file(self, path):
        self.files.append(path)
        return True, None

    async def send_announce(self):
        self.announces += 1


passed = 0


def check(name, condition):
    global passed
    if condition:
        passed += 1
        print(f"  ok  - {name}")
    else:
        raise AssertionError(f"FAILED - {name}")


async def recv_json(ws, timeout=5.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


async def recv_until(ws, predicate, timeout=5.0):
    """Collect events until one matches; return (matching_event, all_events)."""
    collected = []
    while True:
        event = await recv_json(ws, timeout)
        collected.append(event)
        if predicate(event):
            return event, collected


def new_state():
    return ChatState("tester", os.urandom(8))


async def start_server(state, ble, token=None):
    server = WebSocketServer(state, ble, "127.0.0.1", 0, token)
    task = asyncio.create_task(server.run())
    await asyncio.wait_for(server._started.wait(), timeout=5)
    return server, task


async def stop_server(server, task):
    await server.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_open_server_events_and_commands():
    state = new_state()
    ble = FakeBLE(state)
    server, task = await start_server(state, ble)
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as ws:
            snapshot = await recv_json(ws)
            check("first event is a snapshot", snapshot["type"] == "snapshot")
            check("snapshot carries the peer id",
                  snapshot["peer_id"] == state.my_peer_id_hex)
            check("snapshot carries history", snapshot["history"] == [])

            await ws.send(json.dumps({"type": "send", "content": "hello",
                                      "id": "req-1"}))
            # The message event (from ChatState) and the ack travel on
            # different paths, so accept either order.
            msg_event, events = await recv_until(
                ws, lambda e: e.get("type") == "message"
                and e.get("content") == "hello"
            )
            check("sent message is echoed as an event",
                  msg_event["is_self"] is True)
            ack = next((e for e in events if e.get("type") == "ack"
                        and e.get("request_id") == "req-1"), None)
            if ack is None:
                ack, _ = await recv_until(
                    ws, lambda e: e.get("type") == "ack"
                    and e.get("request_id") == "req-1"
                )
            check("send command is acked", ack["ok"] is True)
            check("send command reached BLE", ble.sent == ["hello"])

            state.set_peer("0011223344556677", "android")
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "peer_joined"
            )
            check("peer_joined is pushed", event["nickname"] == "android")

            state.set_nickname("renamed")
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "nickname"
            )
            check("nickname change is pushed", event["nickname"] == "renamed")

            state.add_message(BitchatMessage(
                content="incoming", sender="android",
                sender_id="0011223344556677",
            ))
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "message"
                and e.get("content") == "incoming"
            )
            check("remote message is pushed", event["sender"] == "android")

            await ws.send(json.dumps({"type": "set_nickname",
                                      "nickname": "bot", "id": "req-2"}))
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "ack"
                and e.get("request_id") == "req-2"
            )
            check("set_nickname is acked", event["ok"] is True)
            check("set_nickname updates state", state.nickname == "bot")
            check("set_nickname re-announces", ble.announces == 1)

            await ws.send(json.dumps({"type": "peers", "id": "req-3"}))
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "peers"
            )
            check("peers reply lists the peer",
                  event["peers"] == [{"peer_id": "0011223344556677",
                                      "nickname": "android"}])

            await ws.send(json.dumps({"type": "history", "limit": 1,
                                      "id": "req-4"}))
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "history"
            )
            check("history honours the limit", len(event["messages"]) == 1)

            await ws.send(json.dumps({"type": "ping", "id": "req-5"}))
            event, _ = await recv_until(ws, lambda e: e.get("type") == "pong")
            check("ping gets a pong", event["request_id"] == "req-5")

            await ws.send(json.dumps({"type": "send_file",
                                      "path": "/tmp/x.png", "id": "req-6"}))
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "ack"
                and e.get("request_id") == "req-6"
            )
            check("send_file is acked", event["ok"] is True)
            check("send_file reached BLE", ble.files == ["/tmp/x.png"])

            await ws.send(json.dumps({"type": "nope", "id": "req-7"}))
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "ack"
                and e.get("request_id") == "req-7"
            )
            check("unknown commands are rejected", event["ok"] is False)
    finally:
        await stop_server(server, task)


async def test_browser_origin_rejected_without_token():
    state = new_state()
    ble = FakeBLE(state)
    server, task = await start_server(state, ble)
    try:
        try:
            async with connect(f"ws://127.0.0.1:{server.port}",
                               origin="http://evil.example") as ws:
                await recv_json(ws)
            rejected = False
        except Exception:
            rejected = True
        check("browser origins are rejected without a token", rejected)
    finally:
        await stop_server(server, task)


async def test_token_authentication():
    state = new_state()
    ble = FakeBLE(state)
    server, task = await start_server(state, ble, token="s3cret")
    try:
        uri = f"ws://127.0.0.1:{server.port}"

        async with connect(uri) as ws:
            first = await recv_json(ws)
            check("token server asks for auth", first["type"] == "auth_required")
            await ws.send(json.dumps({"type": "auth", "token": "wrong"}))
            event = await recv_json(ws)
            check("wrong token is rejected", event["type"] == "error")
            try:
                await asyncio.wait_for(ws.recv(), timeout=5)
                closed = False
            except Exception:
                closed = True
            check("wrong token closes the connection", closed)
        check("nothing was sent before auth", ble.sent == [])

        async with connect(uri) as ws:
            first = await recv_json(ws)
            check("new connection asks for auth again",
                  first["type"] == "auth_required")
            await ws.send(json.dumps({"type": "auth", "token": "s3cret"}))
            event, _ = await recv_until(
                ws, lambda e: e.get("type") == "snapshot"
            )
            check("correct token gets a snapshot", event["type"] == "snapshot")
    finally:
        await stop_server(server, task)


async def test_refuses_open_non_loopback_bind():
    server = WebSocketServer(new_state(), FakeBLE(new_state()),
                             "0.0.0.0", 0, token=None)
    try:
        await server.run()
        refused = False
    except RuntimeError:
        refused = True
    check("non-loopback bind without a token is refused", refused)


async def main():
    print("Running bitchat-cli WebSocket self-tests...\n")
    for test in (
        test_open_server_events_and_commands,
        test_browser_origin_rejected_without_token,
        test_token_authentication,
        test_refuses_open_non_loopback_bind,
    ):
        print(f"{test.__name__}:")
        await test()
    print(f"\nAll {passed} checks passed. ✅")


if __name__ == "__main__":
    asyncio.run(main())
