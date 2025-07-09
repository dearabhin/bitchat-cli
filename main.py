# main.py
import asyncio
import os

from chat_state import ChatState
from cli import CLI


def main():
    # Generate a unique peer ID for this session
    my_peer_id = os.urandom(8)

    # Initialize application state
    state = ChatState(
        nickname=f"win-user-{my_peer_id.hex()[:4]}", my_peer_id=my_peer_id)

    # Create and run the command-line interface
    cli_app = CLI(state)

    try:
        asyncio.run(cli_app.run())
    except KeyboardInterrupt:
        print("\nExiting bitchat. Goodbye!")


if __name__ == "__main__":
    main()
