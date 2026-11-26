# main.py
import asyncio
from .chat_state import ChatState
from .cli import CLI


def main():
    """
    Initializes and runs the Bitchat CLI application.
    """
    # ChatState derives the wire peer ID from the Noise public key (required by
    # the official apps) and picks a readable "user-xxxx" nickname from it.
    state = ChatState()

    # Create and run the command-line interface
    cli_app = CLI(state)

    try:
        asyncio.run(cli_app.run())
    except KeyboardInterrupt:
        print("\nExiting bitchat. Goodbye!")


if __name__ == "__main__":
    main()
