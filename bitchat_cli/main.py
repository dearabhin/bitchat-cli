# main.py
import argparse
import asyncio
import os
import sys

from .chat_state import ChatState
from .cli import CLI


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitchat",
        description="Serverless P2P public chat over a Bluetooth LE mesh.",
    )
    parser.add_argument(
        "--ws", action="store_true",
        help="Enable the WebSocket control server (needs the 'ws' extra).",
    )
    parser.add_argument(
        "--ws-host", default="127.0.0.1",
        help="WebSocket bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--ws-port", type=int, default=8787,
        help="WebSocket port, 0 picks a free port (default: 8787).",
    )
    parser.add_argument(
        "--ws-token", default=os.environ.get("BITCHAT_WS_TOKEN"),
        help="Shared token clients must send before issuing commands "
             "(default: $BITCHAT_WS_TOKEN). Required for non-loopback binds.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """
    Initializes and runs the Bitchat CLI application.
    """
    args = _parse_args(argv)

    ws_host = None
    if args.ws:
        try:
            import websockets  # noqa: F401
        except ImportError:
            print(
                "The WebSocket control server needs the 'websockets' package:\n"
                '  pip install "bitchat-cli[ws]"',
                file=sys.stderr,
            )
            raise SystemExit(2)
        ws_host = args.ws_host

    # Generate a unique peer ID for this session
    my_peer_id = os.urandom(8)

    # Initialize application state with a more readable nickname
    state = ChatState(
        nickname=f"user-{my_peer_id.hex()[:4]}", my_peer_id=my_peer_id
    )

    # Create and run the command-line interface
    cli_app = CLI(state, ws_host=ws_host, ws_port=args.ws_port,
                  ws_token=args.ws_token)

    try:
        asyncio.run(cli_app.run())
    except KeyboardInterrupt:
        print("\nExiting bitchat. Goodbye!")


if __name__ == "__main__":
    main()
