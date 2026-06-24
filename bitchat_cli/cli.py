# cli.py
import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.patch_stdout import patch_stdout

from . import __version__, theme
from .ble_service import BLEService
from .chat_state import ChatState


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

    def redraw_prompt(self):
        if self.session.app:
            self.session.app.invalidate()

    def get_prompt_message(self):
        # ANSI() lets prompt_toolkit render the coloured prompt correctly.
        return ANSI(theme.prompt(self.state.nickname))

    def _out(self, line: str):
        print(line)
        self.redraw_prompt()

    async def handle_command(self, text: str):
        parts = text.split(" ")
        cmd = parts[0].lower()

        if cmd == "/w":
            if not self.state.peer_nicknames:
                self._out(theme.system("No peers yet — still scanning / waiting for announces…"))
            else:
                n = len(self.state.peer_nicknames)
                self._out(theme.system(f"Known peers ({n}):"))
                for peer_id, nick in self.state.peer_nicknames.items():
                    name = theme.sgr(nick, theme.BOLD, theme.nick_color(nick))
                    self._out(f"  {name} {theme.sgr(peer_id, theme.PATH)}")
        elif cmd == "/name":
            new_nick = text[len("/name"):].strip()
            if not new_nick:
                self._out(theme.warn("Usage: /name <new nickname>"))
            else:
                old = self.state.nickname
                self.state.nickname = new_nick
                await self.ble_service.send_announce()
                self._out(theme.system(f"Nickname changed from '{old}' to '{new_nick}'."))
        elif cmd in ("/send", "/file"):
            path = text[len(cmd):].strip().strip('"').strip("'")
            if not path:
                self._out(theme.warn(f"Usage: {cmd} <path-to-file>"))
            else:
                await self.ble_service.send_file(path)
        elif cmd == "/clear":
            print("\033c", end="")
        elif cmd == "/help":
            self._out(theme.system("Commands:"))
            for name, desc in (
                ("/w", "List known peers."),
                ("/name <nick>", "Change your nickname and re-announce."),
                ("/send <path>", "Send an image, voice note, or file to peers."),
                ("/clear", "Clear the screen."),
                ("/help", "Show this help message."),
            ):
                cmd_col = theme.sgr(name.ljust(14), theme.BOLD, theme.BRAND)
                self._out(f"  {cmd_col} {theme.sgr(desc, theme.SYS)}")
        else:
            self._out(theme.warn(f"Unknown command: {cmd}. Type /help for commands."))

    async def run(self):
        print(theme.banner(self.state.nickname, self.state.my_peer_id_hex, __version__))

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
                        # send_public_message renders the local echo via the theme.
                        await self.ble_service.send_public_message(text)
        except (EOFError, KeyboardInterrupt):
            print("\n" + theme.system("Shutting down…"))
        finally:
            if ble_task:
                ble_task.cancel()
            await self.ble_service.stop()
            print(theme.system("Shutdown complete."))
