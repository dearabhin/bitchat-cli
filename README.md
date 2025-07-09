# Bitchat CLI (Python Version)

This is a Python-based, command-line implementation of **bitchat**, a secure, decentralized, peer-to-peer messaging app that works over Bluetooth mesh networks. This version is designed to be compatible with the original Swift application's protocol.

**Original iOS Version by Jack**: [github.com/jackjackbits/bitchat](https://github.com/jackjackbits/bitchat)

## Features

-   **Decentralized Communication**: No internet or servers required.
-   **Peer-to-Peer**: Connects directly with other bitchat users via Bluetooth LE.
-   **Secure**: Implements the core cryptographic principles of the original app.
-   **Cross-Platform**: Built with Python and `bleak`, with the potential to run on Windows, macOS, and Linux.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/dearabhin/bitchat-cli.git
    cd bitchat-cli
    ```

2.  **Install Python:**
    Ensure you have Python 3.8+ installed on your system.

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Usage

Run the application from your terminal:

```bash
python main.py
```

The application will automatically start scanning for nearby bitchat peers.

### Commands

-   `/w`: List all currently connected users.
-   `/m <nickname> <message>`: (Coming Soon) Send a private message.
-   `/j #channel`: (Coming Soon) Join a channel.
-   `/clear`: (Coming Soon) Clear the screen.

## How It Works

This application uses the `bleak` library to handle Bluetooth Low Energy (BLE) communication, acting as a BLE central device to discover and connect to other bitchat peers. It re-implements the custom binary protocol and encryption schemes from the original Swift application to ensure compatibility.

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