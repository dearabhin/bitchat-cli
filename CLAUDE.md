# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python CLI port of **bitchat**, a serverless peer-to-peer chat over a Bluetooth LE mesh. It is wire-compatible with the real app (https://github.com/permissionlesstech/bitchat) for **public/broadcast chat**: it can exchange public messages one-hop with a real bitchat phone in range. The binary packet format in `protocol.py` and the BLE service/characteristic UUIDs in `ble_service.py` mirror the upstream Swift implementation — do not change those without re-checking against upstream source, or interop breaks.

**Deliberately out of scope** (not implemented): Noise_XX private messaging, mesh relaying, and acting as a BLE peripheral/advertiser. These are infeasible or very large in pure-Python `bleak`, which is **central-only** — see "Constraints" below.

## Commands

```bash
pip install -r requirements.txt   # bleak, cryptography, prompt-toolkit
python main.py                    # run the app; scans for bitchat peers over BLE
python selftest.py                # offline protocol round-trip + signature tests (no BLE needed)
```

`selftest.py` is the only thing runnable without hardware. `main.py` requires a working Bluetooth LE adapter — without one it starts, prints the logo, and reports that the scan could not start. `selftest.py` needs only `cryptography` (not `bleak`/`prompt-toolkit`), so it runs in CI/headless.

In-app slash commands: `/w` (list known peers by peer-ID → nickname), `/name <nick>` (change nickname + re-announce), `/clear`, `/help`. Any non-slash input is broadcast publicly to connected peers.

## Architecture

Single-process asyncio app. `main.py` → random 8-byte peer ID + `user-xxxx` nickname → `ChatState` → `CLI.run()`.

- **`protocol.py`** — pure serialization, no I/O. The real bitchat wire format:
  - `BitchatPacket.encode()/decode()`: big-endian header `version(1) type(1) ttl(1) timestamp_ms(8) flags(1) payloadLen(2)` + `senderID(8)` + optional `recipientID(8)` + payload + optional `signature(64)`, then PKCS#7 `MessagePadding` to a block size (256/512/1024/2048). Decode also handles v2 (16-byte header, source-route hops it skips) and zlib-compressed inbound payloads.
  - `MessageType` opcodes match upstream: `ANNOUNCE=0x01`, `MESSAGE=0x02` (public, **unencrypted**), `LEAVE=0x03`, `NOISE_HANDSHAKE=0x10`, `NOISE_ENCRYPTED=0x11`, `FRAGMENT=0x20`.
  - `data_for_signing()`: canonical bytes the Ed25519 signature covers — the packet re-encoded with **signature=None and ttl=0** (TTL mutates during relay), padded. The transmitted padding is irrelevant to verification; the receiver reconstructs this canonical form from the decoded fields.
  - `AnnouncementPacket`: TLV (`0x01` nickname, `0x02` X25519 noise pubkey, `0x03` Ed25519 signing pubkey).
  - A **public message's payload is the raw UTF-8 content string** — NOT a TLV/structured blob. The sender nickname is resolved from its peer ID via the ANNOUNCE it sent earlier. `BitchatMessage` is just a local value object for chat history.
  - `FragmentReassembler` reassembles inbound `FRAGMENT` packets (`fragmentID(8) index(2) total(2) originalType(1) data`) into the original encoded inner packet, which is then decoded recursively.
- **`identity.py`** — `IdentityKeys`: per-session X25519 static key + Ed25519 signing key. Exposes raw 32-byte public keys (for ANNOUNCE) and `sign()`. Public chat is unencrypted, but the real app **drops public messages whose signature is missing/invalid**, so every outbound packet must be signed and we must ANNOUNCE our signing key first.
- **`ble_service.py`** — all Bluetooth I/O via `bleak`, central role. Scans with a `detection_callback` and connects **only** to devices whose advertisement contains the bitchat `SERVICE_UUID` (with a per-device attempt cap + cooldown + permanent ignore-set). On connect: validate the characteristic, `start_notify`, and immediately `send_announce()`. Inbound notifications dispatch by `MessageType`; outbound `send_announce`/`send_public_message`/`send_leave` sign → encode → write to every connected client (fragmenting frames over `MAX_FRAME_SIZE`).
- **`chat_state.py`** — `ChatState`: holds `IdentityKeys`, chat history, peers keyed by **8-byte peer-ID hex → nickname** (from ANNOUNCE, NOT BLE MAC), and the set of connected BLE addresses. Shared by reference into `CLI` and `BLEService`.
- **`cli.py`** — `prompt_toolkit` REPL. Owns the `BLEService` and passes it a `redraw_prompt` callback so the async BLE layer can print incoming messages without corrupting the input line (`patch_stdout()` in `run()`). `CLI.run()` launches `BLEService.run()` as a background task and loops on `prompt_async()` concurrently on the same event loop.

## Constraints / gotchas

- **`bleak` is central-only**: this client cannot advertise as a BLE peripheral or relay. It interoperates one hop with bitchat peers in range *while connected to them*; it is not discoverable when idle and does not participate in the multi-hop mesh.
- **Signatures are mandatory** for public messages to be accepted (see `identity.py`). If you change `BitchatPacket.encode()` or `data_for_signing()`, re-run `selftest.py` — the signature test simulates the receiver's verification path.
- **MTU**: transmitted packets are padded to ≥256 bytes, so a single BLE write relies on the ~512-byte MTU that bitchat peers negotiate. Against a peer that only negotiates a small MTU, large writes may fail.
- The bitchat UUIDs and opcodes were verified against upstream `BLEService.swift`, `BinaryProtocol.swift`, `MessageType.swift`, and `Packets.swift`. Re-verify there before changing any wire constant.
