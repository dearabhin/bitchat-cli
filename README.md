<div align="center">

# bitchat-cli

**Serverless, peer-to-peer chat over a Bluetooth LE mesh — right in your terminal.**

Wire-compatible with the [bitchat](https://github.com/permissionlesstech/bitchat) app for **public chat**:
exchange text, images, voice notes, and files one hop with a real bitchat phone in range.

[![PyPI version](https://img.shields.io/pypi/v/bitchat-cli?style=flat-square&logo=pypi&logoColor=white&color=2ea44f)](https://pypi.org/project/bitchat-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/bitchat-cli?style=flat-square&logo=python&logoColor=white)](https://pypi.org/project/bitchat-cli/)
[![GitHub stars](https://img.shields.io/github/stars/dearabhin/bitchat-cli?style=flat-square&logo=github&color=yellow)](https://github.com/dearabhin/bitchat-cli/stargazers)
[![Publish](https://img.shields.io/github/actions/workflow/status/dearabhin/bitchat-cli/publish.yml?style=flat-square&logo=githubactions&logoColor=white&label=publish)](https://github.com/dearabhin/bitchat-cli/actions/workflows/publish.yml)
[![Latest release](https://img.shields.io/github/v/release/dearabhin/bitchat-cli?style=flat-square&logo=github&color=orange)](https://github.com/dearabhin/bitchat-cli/releases)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey?style=flat-square)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](#-contributing)

<img src="https://raw.githubusercontent.com/dearabhin/bitchat-cli/main/bitchat.png" alt="bitchat-cli terminal UI" width="660">

</div>

---

## ✨ Features

- 🛰️ **Serverless & decentralized** — no internet, accounts, or servers. Just Bluetooth.
- 📡 **Talks to the real app** — interoperates with [bitchat](https://github.com/permissionlesstech/bitchat) on iOS/Android for public/broadcast chat.
- 🖼️ **Media support** — send and receive **images, voice notes, and files** (`/send <path>`); received media is saved to `~/.bitchat/downloads/` and opened automatically.
- 🔐 **Signed messages** — every packet is Ed25519-signed, matching the format the app requires.
- 🎨 **Themed terminal UI** — timestamps, a stable color per peer, and clear status glyphs. Honors `NO_COLOR`.
- 🐍 **Pure Python** — built on [`bleak`](https://github.com/hbldh/bleak), runs on Linux, macOS, and Windows.

## 📦 Installation

> Requires **Python 3.8+** and a working **Bluetooth LE** adapter.

**From PyPI (recommended):**

```bash
pip install bitchat-cli
```

**From source:**

```bash
git clone https://github.com/dearabhin/bitchat-cli.git
cd bitchat-cli
pip install -e .
```

## 🚀 Usage

Once installed, launch it from anywhere:

```bash
bitchat          # or: bitchat-cli
```

From a source checkout you can also run `python -m bitchat_cli`.

It immediately starts scanning for nearby bitchat peers, connects to any in range, and broadcasts whatever you type. Type a message and press **Enter** to send it publicly.

## 💬 Commands

| Command | Description |
| --- | --- |
| `<message>` | Any text not starting with `/` is broadcast publicly to peers. |
| `/send <path>` | Send an image, voice note, or file to peers (alias: `/file`). |
| `/w` | List known peers (peer ID → nickname). |
| `/name <nickname>` | Change your nickname and re-announce. |
| `/clear` | Clear the screen. |
| `/help` | Show the list of available commands. |

## 🔧 How it works

bitchat-cli uses [`bleak`](https://github.com/hbldh/bleak) as a BLE **central** that discovers, connects to, and exchanges packets with real bitchat peers in range. It implements bitchat's binary wire protocol — announce / leave / public-message / file-transfer packets, PKCS#7 padding, fragment reassembly, and Ed25519 packet signing — so it can take part in **public chat** with the official app.

> [!NOTE]
> **Scope & limitations.** Only public/broadcast chat is supported. Private (Noise-encrypted) messaging, multi-hop mesh relaying, and advertising as a BLE **peripheral** are not implemented — `bleak` is central-only, so this client works one hop with peers it is connected to and is not itself discoverable when idle.

## 🧪 Protocol self-test

Verify the wire-protocol implementation without any Bluetooth hardware (needs only `cryptography`):

```bash
python selftest.py
```

Run it from a source checkout — it imports the `bitchat_cli` package and covers packet encode/decode, signatures, fragmentation, and the media file format.

## 🤝 Contributing

Contributions are welcome!

1. Fork the repository and clone your fork.
2. Install in editable mode: `pip install -e .`
3. Create a branch, make your change, and run `python selftest.py`.
4. Open a Pull Request with a clear description.

## 🙌 Credits

An independent Python port of [**bitchat**](https://github.com/permissionlesstech/bitchat) — the serverless BLE-mesh chat app. All the wire-format credit belongs to the upstream project; this CLI just speaks its language.

## 📄 License

Released under the [GNU GPL-3.0](LICENSE).
