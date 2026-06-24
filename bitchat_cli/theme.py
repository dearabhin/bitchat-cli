# theme.py
#
# Centralised terminal styling for the chat UI: a small semantic colour palette
# plus formatters for chat lines, media, system notices, and events. Everything
# degrades to plain text when output isn't a TTY or NO_COLOR is set, so logs and
# redirected output stay clean.

import hashlib
import os
import sys
import time


def _color_enabled() -> bool:
    # https://no-color.org/ — any value (even empty) disables colour.
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("BITCHAT_FORCE_COLOR"):
        return True
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


ENABLED = _color_enabled()


def _fg(n: int) -> str:
    """256-colour foreground SGR parameter."""
    return f"38;5;{n}"


def sgr(text: str, *codes: str) -> str:
    """Wrap text in SGR codes (no-op when colour is disabled)."""
    if not ENABLED or not codes:
        return text
    return "".join(f"\033[{c}m" for c in codes) + text + "\033[0m"


# --- Semantic palette (256-colour) --------------------------------------- #
BOLD = "1"
DIM = "2"
BRAND = _fg(42)     # bitchat green — logo, prompt, accents
OWN = _fg(45)       # your own nickname (teal)
TIME = _fg(240)     # timestamps (dim grey)
SYS = _fg(245)      # neutral system info
OK = _fg(42)        # success / connected
JOIN = _fg(42)      # peer came online
LEAVE = _fg(244)    # peer went offline
ERR = _fg(203)      # errors (soft red)
WARN = _fg(214)     # warnings (amber)
MEDIA = _fg(212)    # media labels (pink)
PATH = _fg(240)     # file paths (dim)
LABEL = _fg(244)    # banner field labels

# A spread of legible colours assigned to peer nicknames by hash, so each peer
# keeps a stable, distinct colour across the session. Excludes the reserved
# OWN/system hues above to avoid confusion.
_NICK_PALETTE = [_fg(n) for n in (
    39, 75, 81, 114, 150, 156, 180, 215, 211, 209, 176, 147, 84, 222, 117, 110,
)]

_MEDIA_ICON = {"image": "🖼", "audio": "🎙", "file": "📎"}


def nick_color(name: str) -> str:
    if not name:
        return SYS
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    return _NICK_PALETTE[h % len(_NICK_PALETTE)]


def _hm(ts_ms=None) -> str:
    t = time.localtime(ts_ms / 1000) if ts_ms else time.localtime()
    return time.strftime("%H:%M", t)


# --- Line formatters ----------------------------------------------------- #
def chat(sender: str, content: str, ts_ms=None, is_self: bool = False) -> str:
    color = OWN if is_self else nick_color(sender)
    return f"{sgr(_hm(ts_ms), TIME)}  {sgr(sender, BOLD, color)}  {content}"


def media(sender: str, category: str, label: str, path=None,
          ts_ms=None, is_self: bool = False) -> str:
    color = OWN if is_self else nick_color(sender)
    icon = _MEDIA_ICON.get(category, _MEDIA_ICON["file"])
    body = sgr(f"{icon} {label}", MEDIA)
    if path is not None:
        body += " " + sgr(f"→ {path}", PATH)
    return f"{sgr(_hm(ts_ms), TIME)}  {sgr(sender, BOLD, color)}  {body}"


def system(msg: str) -> str:
    return f"{sgr('·', SYS)} {sgr(msg, SYS)}"


def ok(msg: str) -> str:
    return f"{sgr('✓', BOLD, OK)} {sgr(msg, OK)}"


def join(msg: str) -> str:
    return f"{sgr('→', BOLD, JOIN)} {sgr(msg, JOIN)}"


def leave(msg: str) -> str:
    return f"{sgr('←', LEAVE)} {sgr(msg, LEAVE)}"


def warn(msg: str) -> str:
    return f"{sgr('!', BOLD, WARN)} {sgr(msg, WARN)}"


def error(msg: str) -> str:
    return f"{sgr('✗', BOLD, ERR)} {sgr(msg, ERR)}"


def prompt(nick: str) -> str:
    """The input prompt string (wrap in prompt_toolkit ANSI() before use)."""
    return f"{sgr(nick, BOLD, BRAND)}{sgr(' ❯ ', BRAND)}"


# --- Multi-line blocks --------------------------------------------------- #
_LOGO = r"""
██████╗ ██╗████████╗ ██████╗██╗  ██╗ █████╗ ████████╗
██╔══██╗██║╚══██╔══╝██╔════╝██║  ██║██╔══██╗╚══██╔══╝
██████╔╝██║   ██║   ██║     ███████║███████║   ██║
██╔══██╗██║   ██║   ██║     ██╔══██║██╔══██║   ██║
██████╔╝██║   ██║   ╚██████╗██║  ██║██║  ██║   ██║
╚═════╝ ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝"""


def banner(nickname: str, peer_id: str, version: str) -> str:
    """The startup welcome block."""
    logo = sgr(_LOGO, BRAND)
    tag = sgr(f"C L I  ·  v{version}", BOLD, BRAND)
    field = lambda k, v, c: f"{sgr(k, LABEL)} {sgr(v, BOLD, c)}"
    lines = [
        logo,
        f"                  {tag}",
        "",
        "  " + field("you", nickname, OWN) + sgr("   ·   ", LABEL) + field("peer", peer_id, SYS),
        "  " + sgr("Messages are broadcast publicly to bitchat peers in range.", SYS),
        "  " + sgr("Type a message and press Enter, or ", SYS)
        + sgr("/help", BOLD, BRAND) + sgr(" for commands.", SYS),
    ]
    return "\n".join(lines)
