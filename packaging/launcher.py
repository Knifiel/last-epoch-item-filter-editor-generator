"""Entry point of the packaged app: runs the editor (`ui`) unless other arguments are given.

Started by double-click, there's either a console window that closes with the program (Windows)
or no terminal at all (Linux file managers). So on Linux the program reopens itself in a
terminal window, and any failure is shown - and saved to last-error.txt in the program's
folder - before the window closes."""
import os
import shutil
import subprocess
import sys
import traceback

from lefilter.__main__ import main
from lefilter.paths import FROZEN, USER_DIR

# Linux terminals and the flag that runs a command in them.
TERMINALS = [("x-terminal-emulator", "-e"), ("konsole", "-e"), ("gnome-terminal", "--"), ("kgx", "--"),
             ("xfce4-terminal", "-x"), ("mate-terminal", "-x"), ("kitty", ""), ("alacritty", "-e"),
             ("wezterm", "start"), ("foot", ""), ("xterm", "-e")]


def _restore_library_path() -> None:
    """The bundled app runs with its own libraries first on LD_LIBRARY_PATH; programs it starts
    (browser, terminal, Cpp2IL) must get the system's back."""
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        os.environ["LD_LIBRARY_PATH"] = original
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)


def _has_terminal() -> bool:
    return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())


def _reopen_in_terminal() -> bool:
    """Linux, started without a terminal (e.g. from a file manager): run again inside one."""
    if os.environ.get("LEFE_IN_TERMINAL") or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    env = {**os.environ, "LEFE_IN_TERMINAL": "1"}
    preferred = os.environ.get("TERMINAL")
    for name, flag in ([(preferred, "-e")] if preferred else []) + TERMINALS:
        exe = shutil.which(name)
        if not exe:
            continue
        try:
            subprocess.Popen([exe, *([flag] if flag else []), sys.executable], env=env, start_new_session=True)
            return True
        except OSError:
            continue
    return False


def _save_error(text: str) -> str:
    path = USER_DIR / "last-error.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)
    except OSError:
        return ""


def _pause() -> None:
    try:
        input("\nPress Enter to close this window.")
    except (EOFError, OSError):
        pass


def run() -> None:
    double_clicked = not sys.argv[1:]
    if FROZEN and sys.platform.startswith("linux"):
        _restore_library_path()
        if double_clicked and not _has_terminal() and _reopen_in_terminal():
            return
    try:
        main(sys.argv[1:] or ["ui"])
    except SystemExit as e:
        if e.code in (0, None):
            raise
        if not isinstance(e.code, int):
            print(e.code, file=sys.stderr)
            _save_error(str(e.code))
        if double_clicked:
            _pause()
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
    except Exception:
        details = traceback.format_exc()
        saved = _save_error(details)
        print(f"{details}\nSomething went wrong (details above" + (f", also saved to {saved}" if saved else "") + ").",
              file=sys.stderr)
        if double_clicked:
            _pause()
        raise SystemExit(1)


if __name__ == "__main__":
    run()
