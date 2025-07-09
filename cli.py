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
                "/w", "/m", "/j", "/clear", "/help"
            ], ignore_case=True)
        )

    def print_logo(self):
        """Prints the ASCII art logo."""
        green_color = "\033[92m"
        reset_color = "\033[0m"
        logo = f"""
{green_color}
██████╗ ██╗████████╗ ██████╗██╗  ██╗ █████╗ ████████╗
██╔══██╗██║╚══██╔══╝██╔════╝██║  ██║██╔══██╗╚══██╔══╝
██████╔╝██║   ██║   ██║     ███████║███████║   ██║
██╔══██╗██║   ██║   ██║     ██╔══██║██╔══██║   ██║
██████╔╝██║   ██║   ╚██████╗██║  ██║██║  ██║   ██║
╚═════╝ ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝
                    C L I
{reset_color}
        """
        print(logo)

    def redraw_prompt(self):
        """Redraws the input prompt, essential for a smooth UI."""
        self.session.app.invalidate()

    def get_prompt_message(self):
        """Generates the prompt string with the user's nickname."""
        return f"<{self.state.nickname}> "

    async def handle_command(self, text: str):
        """Handles IRC-style commands."""
        parts = text.split(" ")
        cmd = parts[0].lower()

        if cmd == "/w":
            self.state.add_system_message("Connected Peers:")
            if not self.state.connected_peers:
                self.state.add_system_message("  (None) - Still scanning...")
            else:
                for peer in self.state.connected_peers:
                    nick = self.state.peer_nicknames.get(peer, "unknown")
                    self.state.add_system_message(f"  - {nick} ({peer})")
        elif cmd == "/m":
            self.state.add_system_message("Private messaging is coming soon!")
        elif cmd == "/j":
            self.state.add_system_message("Channels are coming soon!")
        elif cmd == "/clear":
            # This is a simple way to clear the screen
            print("\033c", end="")
        elif cmd == "/help":
            self.state.add_system_message("Available Commands:")
            self.state.add_system_message(
                "  /w          - List connected users.")
            self.state.add_system_message(
                "  /m <nick>   - (Coming Soon) Send a private message.")
            self.state.add_system_message(
                "  /j #channel - (Coming Soon) Join a channel.")
            self.state.add_system_message("  /clear      - Clear the screen.")
        else:
            self.state.add_system_message(
                f"Unknown command: {cmd}. Type /help for a list of commands.")

    async def run(self):
        """Main loop for the CLI."""
        self.print_logo()
        self.state.add_system_message("Welcome to Bitchat CLI!")
        self.state.add_system_message(
            "I'm now scanning for other peers over Bluetooth...")
        self.state.add_system_message(
            "Type a message and press Enter to broadcast.")
        self.state.add_system_message("Type /help for a list of commands.")

        with patch_stdout():
            scan_task = asyncio.create_task(
                self.ble_service.scan_and_connect())
            while True:
                try:
                    self.session.message = self.get_prompt_message()
                    input_text = await self.session.prompt_async()

                    if not input_text:
                        continue

                    if input_text.startswith("/"):
                        await self.handle_command(input_text)
                    else:
                        message = BitchatMessage(
                            content=input_text, sender=self.state.nickname)
                        self.state.add_message(message, is_own_message=True)
                        await self.ble_service.broadcast(message)

                except (EOFError, KeyboardInterrupt):
                    scan_task.cancel()
                    break
        print("Shutting down...")
