"""Where the program finds its files: next to the sources, or - in the packaged app - bundled
read-only resources plus a per-user folder for everything it writes.

Source checkout: everything lives in the project folder (data/, .cache/, out/, templates/,
config.toml). Packaged app (PyInstaller): the web page and the default config come from the
bundle; game data, cache, output, the template and config.toml live in
%APPDATA%/Last Epoch Item Filter Editor (Windows) or ~/.local/share/last-epoch-item-filter-editor.

Nothing taken from the game ships with the program: data/, the new-filter template and the
class-layout schemas are all produced from the user's own install on first start.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Last Epoch Item Filter Editor"
FROZEN = getattr(sys, "frozen", False)
SOURCE_DIR = Path(__file__).resolve().parent.parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_DIR))   # bundled read-only files


def _user_dir() -> Path:
    if not FROZEN:
        return SOURCE_DIR
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "last-epoch-item-filter-editor"


USER_DIR = _user_dir()
DATA_DIR = USER_DIR / "data"
CACHE_DIR = USER_DIR / ".cache"
OUT_DIR = USER_DIR / "out"
TEMPLATE_FILE = USER_DIR / "templates" / "New filter.xml"
CONFIG_FILE = USER_DIR / "config.toml"
GAME_DIR_FILE = USER_DIR / "game_dir.txt"          # the game folder the user pointed us to, if any
SCHEMA_DIR = USER_DIR / "schema"                   # optional hand-made schemas (none are shipped)


def prepare_user_dir() -> None:
    """Packaged app: create the user folder and copy the default config on first run."""
    if not FROZEN:
        return
    for d in (DATA_DIR, CACHE_DIR, OUT_DIR, TEMPLATE_FILE.parent):
        d.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        shutil.copyfile(RESOURCE_DIR / "config.toml", CONFIG_FILE)


def saved_game_dir() -> Path | None:
    try:
        text = GAME_DIR_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(text) if text else None


def save_game_dir(path: Path) -> None:
    GAME_DIR_FILE.parent.mkdir(parents=True, exist_ok=True)
    GAME_DIR_FILE.write_text(str(path), encoding="utf-8")
