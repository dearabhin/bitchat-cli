# cli.py
import asyncio
import os

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.patch_stdout import patch_stdout

from . import __version__, theme
from .ble_service import BLEService
from .chat_state import ChatState


class CLI:
    """Command-line interface and input loop."""

    def __init__(self, state: ChatState, ws_host: str = None,
                 ws_port: int = 8787, ws_token: str = None):
        self.state = state
        self.ble_service = BLEService(state, self.redraw_prompt)
        self.ws_host = ws_host
        self.ws_port = ws_port
        self.ws_token = ws_token
        self.ws_server = None
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
        # ANSI(...) so prompt_toolkit renders the colour codes (a plain print()
        # under patch_stdout() would show the escape sequences literally).
        print_formatted_text(ANSI(line))
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
                self.state.set_nickname(new_nick)
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
            candidate = os.path.expanduser(text.strip())
            if os.path.isfile(candidate):
                # A bare file path starts with '/', so it looks like a command.
                self._out(theme.warn(f"To send a file, use:  /send {text.strip()}"))
            else:
                self._out(theme.warn(f"Unknown command: {cmd}. Type /help for commands."))

    async def _run_ws(self):
        try:
            await self.ws_server.start()
            auth = "token required" if self.ws_token else "no token"
            self._out(theme.system(
                f"WebSocket control on ws://{self.ws_server.host}:"
                f"{self.ws_server.port} ({auth})."
            ))
            await self.ws_server.wait_closed()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - keep the chat running
            self._out(theme.error(f"WebSocket control server stopped: {e}"))

    async def run(self):
        print_formatted_text(ANSI(theme.banner(
            self.state.nickname, self.state.my_peer_id_hex, __version__)))

        ble_task = None
        ws_task = None
        try:
            with patch_stdout():
                ble_task = asyncio.create_task(self.ble_service.run())
                if self.ws_host is not None:
                    from .ws_server import WebSocketServer
                    self.ws_server = WebSocketServer(
                        self.state, self.ble_service, self.ws_host,
                        self.ws_port, self.ws_token,
                    )
                    ws_task = asyncio.create_task(self._run_ws())
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
            if ws_task:
                ws_task.cancel()
            await self.ble_service.stop()
            if self.ws_server is not None:
                await self.ws_server.stop()
            print(theme.system("Shutdown complete."))
