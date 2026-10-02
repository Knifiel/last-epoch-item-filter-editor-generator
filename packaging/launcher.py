"""Entry point of the packaged app: runs the editor (`ui`) unless other arguments are given.

Double-clicked, the console window would vanish with any error message, so failures wait for
Enter before closing."""
import sys

from lefilter.__main__ import main


def run() -> None:
    args = sys.argv[1:] or ["ui"]
    try:
        main(args)
    except SystemExit as e:
        if e.code not in (0, None):
            if not isinstance(e.code, int):
                print(e.code, file=sys.stderr)
            if not sys.argv[1:]:   # started by double-click
                input("\nPress Enter to close this window.")
            raise SystemExit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
