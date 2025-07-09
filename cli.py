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
        # Pass the redraw callback to the service
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
        if self.session.app:
            self.session.app.invalidate()

    def get_prompt_message(self):
        """Generates the prompt string with the user's nickname."""
        return f"<{self.state.nickname}> "

    async def handle_command(self, text: str):
        """Handles IRC-style commands."""
        parts = text.split(" ")
        cmd = parts[0].lower()

        if cmd == "/w":
            print("[SYSTEM] Connected Peers:")
            if not self.state.connected_peers:
                print("  (None) - Still scanning...")
            else:
                for peer in self.state.connected_peers:
                    nick = self.state.peer_nicknames.get(peer, "unknown")
                    print(f"  - {nick} ({peer})")
        elif cmd == "/m":
            print("[SYSTEM] Private messaging is coming soon!")
        elif cmd == "/j":
            print("[SYSTEM] Channels are coming soon!")
        elif cmd == "/clear":
            # This is a simple way to clear the screen
            print("\033c", end="")
        elif cmd == "/help":
            print("[SYSTEM] Available Commands:")
            print("  /w          - List connected users.")
            print("  /m <nick>   - (Coming Soon) Send a private message.")
            print("  /j #channel - (Coming Soon) Join a channel.")
            print("  /clear      - Clear the screen.")
            print("  /help       - Show this help message.")
        else:
            print(
                f"[SYSTEM] Unknown command: {cmd}. Type /help for a list of commands.")

    async def run(self):
        """Main loop for the CLI."""
        self.print_logo()
        print(
            f"[SYSTEM] Welcome to Bitchat CLI! Your nickname is {self.state.nickname}.")
        print("[SYSTEM] All messages are broadcast publicly to connected peers.")
        print("[SYSTEM] I'm now scanning for other peers over Bluetooth...")
        print(
            "[SYSTEM] Type a message and press Enter to broadcast, or /help for commands.")

        scan_task = None
        try:
            with patch_stdout():
                scan_task = asyncio.create_task(
                    self.ble_service.scan_and_connect())
                while True:
                    self.session.message = self.get_prompt_message
                    input_text = await self.session.prompt_async()

                    if not input_text.strip():
                        continue

                    if input_text.startswith("/"):
                        await self.handle_command(input_text)
                    else:
                        message = BitchatMessage(
                            content=input_text, sender=self.state.nickname)
                        # Add to local state
                        self.state.add_message(message)
                        # Print your own message immediately
                        print(f"\n<You>: {message.content}")
                        # Broadcast to peers
                        await self.ble_service.broadcast(message)

        except (EOFError, KeyboardInterrupt):
            print("\n[SYSTEM] Shutting down...")
            if scan_task:
                scan_task.cancel()

            print("[SYSTEM] Disconnecting from peers...")
            disconnect_tasks = [
                client.disconnect() for client in self.ble_service.clients.values() if client.is_connected
            ]
            if disconnect_tasks:
                await asyncio.gather(*disconnect_tasks, return_exceptions=True)
            print("[SYSTEM] All peers disconnected.")

        print("[SYSTEM] Shutdown complete.")
