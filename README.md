# Bitchat CLI (Python Version)

This is a Python-based, command-line implementation of **bitchat**, a secure, decentralized, peer-to-peer messaging app that works over Bluetooth mesh networks. This version is designed to be compatible with the original Swift application's protocol.

**Original iOS Version by Jack**: [github.com/jackjackbits/bitchat](https://github.com/jackjackbits/bitchat)

## Features

-   **Decentralized Communication**: No internet or servers required.
-   **Peer-to-Peer**: Connects directly with other bitchat users via Bluetooth LE.
-   **Secure**: Implements the core cryptographic principles of the original app.
-   **Cross-Platform**: Built with Python and `bleak`, with the potential to run on Windows, macOS, and Linux.

## Installation

Requires Python 3.8+ and a working Bluetooth LE adapter.

### From PyPI (recommended)

```bash
pip install bitchat-cli
```

### From source

```bash
git clone https://github.com/dearabhin/bitchat-cli.git
cd bitchat-cli
pip install -e .
```

## Usage

Once installed, run it from anywhere:

```bash
bitchat-cli      # or simply: bitchat
```

From a source checkout you can also run `python -m bitchat_cli`.

The application will automatically start scanning for nearby bitchat peers and broadcast your public messages to them.

### Commands

-   `/w`: List known peers (peer ID → nickname).
-   `/name <nickname>`: Change your nickname and re-announce.
-   `/send <path>` (alias `/file`): Send an image, voice note, or file to peers.
-   `/clear`: Clear the screen.
-   `/help`: Show the list of available commands.

Any text that does not start with `/` is sent as a public (broadcast) message.

## How It Works

This application uses the `bleak` library for Bluetooth Low Energy (BLE) communication, acting as a BLE **central** that discovers, connects to, and exchanges packets with real bitchat peers in range. It implements bitchat's binary wire protocol — announce/leave/public-message packets, PKCS#7 padding, fragment reassembly, and Ed25519 packet signing — so it can take part in **public chat** with the official app.

**Scope and limitations:** Only public/broadcast chat is supported. Private (Noise-encrypted) messaging, multi-hop mesh relaying, and advertising as a BLE peripheral are **not** implemented — `bleak` is central-only, so this client works one hop with peers it is connected to and is not itself discoverable when idle.

### Protocol self-test

You can verify the wire-protocol implementation without any Bluetooth hardware:

```bash
python selftest.py
```

(Run from a source checkout; it imports the `bitchat_cli` package and needs only `cryptography`.)

# Contributing to bitchat-cli

We welcome contributions from everyone! Here’s how you can help.

## Getting Started
1. Fork the repository.
2. Clone your fork: `git clone https://github.com/dearabhin/bitchat-cli.git`
3. Install the dependencies: `pip install -r requirements.txt`

## Submitting Changes
- Create a new branch for your feature or fix.
- Write a clear commit message.
- Open a Pull Request with a detailed description of your changes.