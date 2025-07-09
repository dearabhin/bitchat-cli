# cli.py
import asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.patch_stdout import patch_stdout

from chat_state import ChatState
from ble_service import BLEService
from protocol import BitchatMessage


class CLI:
    """Manages the command-line interface and user input."""

    def __init__(self, state: ChatState):
        self.state = state
        self.ble_service = BLEService(state, self.redraw_prompt)
        self.session = PromptSession(
            completer=WordCompleter([
                "/j", "/m", "/w", "/channels", "/block", "/unblock", "/clear", "/hug", "/slap"
            ], ignore_case=True)
        )

    def redraw_prompt(self):
        """Redraws the input prompt, which can be cleared by incoming messages."""
        self.session.app.invalidate()

    def get_prompt_message(self):
        """Generates the prompt string with the user's nickname."""
        return f"<{self.state.nickname}> "

    async def handle_command(self, text: str):
        """Handles IRC-style commands."""
        parts = text.split(" ")
        cmd = parts[0]
        if cmd == "/w":
            self.state.add_system_message("Connected Peers:")
            if not self.state.connected_peers:
                self.state.add_system_message("  (None)")
            else:
                for peer in self.state.connected_peers:
                    nick = self.state.peer_nicknames.get(peer, "unknown")
                    self.state.add_system_message(f"  - {nick} ({peer})")
        # Add handlers for other commands here...
        else:
            self.state.add_system_message(f"Unknown command: {cmd}")

    async def run(self):
        """Main loop for the CLI."""
        print("--- bitchat for Windows (CLI) ---")
        self.state.add_system_message(
            "Type your message and press Enter. Use /help for commands.")

        # Patch stdout to prevent incoming messages from overwriting user input
        with patch_stdout():
            # Run BLE scanning in the background
            scan_task = asyncio.create_task(
                self.ble_service.scan_and_connect())

            while True:
                try:
                    self.session.message = self.get_prompt_message()
                    input_text = await self.session.prompt_async()

                    if input_text.startswith("/"):
                        await self.handle_command(input_text)
                    elif input_text:
                        message = BitchatMessage(content=input_text)
                        # Display our own message
                        self.state.add_message(message)
                        await self.ble_service.broadcast(message)

                except (EOFError, KeyboardInterrupt):
                    scan_task.cancel()
                    break

            print("Shutting down...")
