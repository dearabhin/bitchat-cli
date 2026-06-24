# cli.py
import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.patch_stdout import patch_stdout

from ble_service import BLEService
from chat_state import ChatState


class CLI:
    """Command-line interface and input loop."""

    def __init__(self, state: ChatState):
        self.state = state
        self.ble_service = BLEService(state, self.redraw_prompt)
        self.session = PromptSession(
            completer=WordCompleter(
                ["/w", "/name", "/send", "/file", "/clear", "/help"], ignore_case=True
            )
        )

    def print_logo(self):
        green, reset = "\033[92m", "\033[0m"
        print(f"""{green}
██████╗ ██╗████████╗ ██████╗██╗  ██╗ █████╗ ████████╗
██╔══██╗██║╚══██╔══╝██╔════╝██║  ██║██╔══██╗╚══██╔══╝
██████╔╝██║   ██║   ██║     ███████║███████║   ██║
██╔══██╗██║   ██║   ██║     ██╔══██║██╔══██║   ██║
██████╔╝██║   ██║   ╚██████╗██║  ██║██║  ██║   ██║
╚═════╝ ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝
                    C L I
{reset}""")

    def redraw_prompt(self):
        if self.session.app:
            self.session.app.invalidate()

    def get_prompt_message(self):
        return f"<{self.state.nickname}> "

    async def handle_command(self, text: str):
        parts = text.split(" ")
        cmd = parts[0].lower()

        if cmd == "/w":
            print("[SYSTEM] Known peers:")
            if not self.state.peer_nicknames:
                print("  (none yet) - still scanning / waiting for announces...")
            else:
                for peer_id, nick in self.state.peer_nicknames.items():
                    print(f"  - {nick} ({peer_id})")
        elif cmd == "/name":
            new_nick = text[len("/name"):].strip()
            if not new_nick:
                print("[SYSTEM] Usage: /name <new nickname>")
            else:
                self.state.nickname = new_nick
                await self.ble_service.send_announce()
                print(f"[SYSTEM] Nickname changed to '{new_nick}'.")
        elif cmd in ("/send", "/file"):
            path = text[len(cmd):].strip().strip('"').strip("'")
            if not path:
                print(f"[SYSTEM] Usage: {cmd} <path-to-file>")
            else:
                await self.ble_service.send_file(path)
        elif cmd == "/clear":
            print("\033c", end="")
        elif cmd == "/help":
            print("[SYSTEM] Available commands:")
            print("  /w            - List known peers.")
            print("  /name <nick>  - Change your nickname and re-announce.")
            print("  /send <path>  - Send an image, voice note, or file to peers.")
            print("  /clear        - Clear the screen.")
            print("  /help         - Show this help message.")
        else:
            print(f"[SYSTEM] Unknown command: {cmd}. Type /help for commands.")

    async def run(self):
        self.print_logo()
        print(f"[SYSTEM] Welcome to Bitchat CLI! Your nickname is {self.state.nickname}.")
        print(f"[SYSTEM] Your peer ID is {self.state.my_peer_id_hex}.")
        print("[SYSTEM] Messages are broadcast publicly to bitchat peers in range.")
        print("[SYSTEM] Type a message and press Enter to send, or /help for commands.")

        ble_task = None
        try:
            with patch_stdout():
                ble_task = asyncio.create_task(self.ble_service.run())
                while True:
                    self.session.message = self.get_prompt_message
                    text = await self.session.prompt_async()
                    if not text.strip():
                        continue
                    if text.startswith("/"):
                        await self.handle_command(text)
                    else:
                        await self.ble_service.send_public_message(text)
                        print(f"<{self.state.nickname}>: {text}")
        except (EOFError, KeyboardInterrupt):
            print("\n[SYSTEM] Shutting down...")
        finally:
            if ble_task:
                ble_task.cancel()
            await self.ble_service.stop()
            print("[SYSTEM] Shutdown complete.")
