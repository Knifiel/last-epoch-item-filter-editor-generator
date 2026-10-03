"""Locate the Last Epoch install and snapshot the files the extractor reads.

The game directory is only ever read. Files are copied into
.cache/game/<build-hash>/ first, so extraction works while the game is
running or patching, and repeat runs don't re-read hundreds of MB from /mnt.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

APP_ID = "899770"
GAME_FOLDER = "Last Epoch"
DATA_FOLDER = "Last Epoch_Data"

HOME = Path.home()
FLATPAK_HOME = HOME / ".var/app/com.valvesoftware.Steam"   # Flatpak Steam's home folder as seen from outside
# Windows (plus the registry, see _steam_roots), WSL, and native / Flatpak / Snap Steam on Linux.
STEAM_ROOTS = [
    Path(r"C:\Program Files (x86)\Steam"),
    Path(r"C:\Program Files\Steam"),
    Path("/mnt/c/Program Files (x86)/Steam"),
    Path("/mnt/c/Program Files/Steam"),
    HOME / ".steam/steam",
    HOME / ".steam/root",
    HOME / ".local/share/Steam",
    FLATPAK_HOME / ".local/share/Steam",
    HOME / "snap/steam/common/.local/share/Steam",
]

FILTERS_SUBPATH = Path("AppData/LocalLow/Eleventh Hour Games/Last Epoch/Filters")
# Linux runs the Windows build through Proton; its user folder lives in the app's Wine prefix.
PROTON_USER = Path("steamapps/compatdata") / APP_ID / "pfx/drive_c/users/steamuser"

# Snapshot name -> path (glob) relative to the game root. Addressables bundles
# may carry a content hash in their file name, hence the globs.
SNAPSHOT_FILES = {
    "resources.assets": f"{DATA_FOLDER}/resources.assets",
    "globalgamemanagers": f"{DATA_FOLDER}/globalgamemanagers",
    "PermaLoad.bundle": f"{DATA_FOLDER}/StreamingAssets/LEAssetBundles/PermaLoad.bundle",
    "monoscripts.bundle": f"{DATA_FOLDER}/StreamingAssets/LEAssetBundles/monoscripts.bundle",
    "strings_en.bundle": f"{DATA_FOLDER}/StreamingAssets/aa/StandaloneWindows64/localization-string-tables-english(en)_*.bundle",
    "strings_shared.bundle": f"{DATA_FOLDER}/StreamingAssets/aa/StandaloneWindows64/localization-assets-shared_*.bundle",
}
# Every game locale's string tables (not the dev / key variants), for the editor's language selector.
LOCALE_GLOB = f"{DATA_FOLDER}/StreamingAssets/aa/StandaloneWindows64/localization-string-tables-*_assets_all.bundle"
LOCALE_RE = re.compile(r"^localization-string-tables-(.+)_assets_all\.bundle$")
# Only needed to regenerate the UniqueList schema after a patch changes its layout.
IL2CPP_FILES = {
    "GameAssembly.dll": "GameAssembly.dll",
    "global-metadata.dat": f"{DATA_FOLDER}/il2cpp_data/Metadata/global-metadata.dat",
}


class GameNotFound(Exception):
    pass


@dataclass
class Game:
    root: Path
    build_hash: str
    steam_build: str | None

    @property
    def short_hash(self) -> str:
        return self.build_hash[:12]


def to_local_path(path: str) -> Path:
    """Map a Windows path from Steam's config onto this OS (WSL mounts drives at /mnt/<letter>)."""
    m = re.match(r"^([A-Za-z]):[\\/]?(.*)$", path)
    if os.name == "nt" or not m:
        return Path(path)
    return Path("/mnt", m[1].lower(), m[2].replace("\\", "/"))


def _registry_steam_roots() -> list[Path]:
    """Steam's install folder as Windows records it (Steam may live on any drive)."""
    try:
        import winreg
    except ImportError:
        return []
    roots = []
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                roots.append(Path(winreg.QueryValueEx(k, value)[0]))
        except OSError:
            continue
    return roots


def _steam_roots() -> list[Path]:
    roots, seen = [], set()
    for root in _registry_steam_roots() + STEAM_ROOTS:
        try:
            key = root.resolve()
        except OSError:
            continue
        if key not in seen and root.is_dir():
            seen.add(key)
            roots.append(root)
    return roots


def _outside_sandbox(path: Path, steam_root: Path) -> Path:
    """Flatpak Steam writes paths as it sees them inside its sandbox, where its home folder is
    FLATPAK_HOME: map those onto the real folder."""
    try:
        if not path.exists() and steam_root.resolve().is_relative_to(FLATPAK_HOME.resolve()) and path.is_relative_to(HOME):
            return FLATPAK_HOME / path.relative_to(HOME)
    except OSError:
        pass
    return path


def _steam_libraries(steam_root: Path) -> list[tuple[Path, bool]]:
    """(library path, has Last Epoch) for every library in libraryfolders.vdf, plus the Steam
    folder itself (its default library)."""
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    text = vdf.read_text(encoding="utf-8", errors="replace") if vdf.is_file() else ""
    paths = list(re.finditer(r'"path"\s+"([^"]+)"', text))
    libs = []
    for i, m in enumerate(paths):
        end = paths[i + 1].start() if i + 1 < len(paths) else len(text)
        has_app = re.search(rf'"{APP_ID}"\s+"', text[m.end():end]) is not None
        libs.append((_outside_sandbox(to_local_path(m[1].replace("\\\\", "\\")), steam_root), has_app))
    if not any(_same(lib, steam_root) for lib, _ in libs):
        libs.append((steam_root, False))
    return libs


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def _read_steam_build(library: Path) -> str | None:
    acf = library / "steamapps" / f"appmanifest_{APP_ID}.acf"
    if not acf.is_file():
        return None
    m = re.search(r'"buildid"\s+"(\d+)"', acf.read_text(encoding="utf-8", errors="replace"))
    return m[1] if m else None


def find_game(game_dir: Path | None = None) -> Game:
    candidates: list[Path] = []
    if game_dir:
        candidates.append(Path(game_dir))
    else:
        for steam_root in _steam_roots():
            libs = _steam_libraries(steam_root)
            # Libraries that list the app first, then the rest as a fallback.
            for lib, has_app in sorted(libs, key=lambda x: not x[1]):
                candidates.append(lib / "steamapps" / "common" / GAME_FOLDER)
    for root in candidates:
        hash_file = root / DATA_FOLDER / "build_hash.txt"
        if hash_file.is_file():
            build_hash = hash_file.read_text(encoding="utf-8").strip()
            return Game(root=root, build_hash=build_hash, steam_build=_read_steam_build(root.parent.parent.parent))
    tried = "\n  ".join(str(c) for c in candidates) or "(no Steam libraries found)"
    raise GameNotFound(f"Last Epoch install not found. Tried:\n  {tried}\n"
                       "Pass the game folder (the one containing 'Last Epoch_Data') with --game-dir.")


def _resolve(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise GameNotFound(f"expected exactly one file matching {root / pattern}, found {len(matches)}")
    return matches[0]


def snapshot(game: Game, cache_root: Path, include_il2cpp: bool = False) -> Path:
    """Copy the files we read into .cache/game/<hash>/ (once per game build)."""
    dest = cache_root / "game" / game.short_hash
    dest.mkdir(parents=True, exist_ok=True)
    files = dict(SNAPSHOT_FILES)
    if include_il2cpp:
        files.update(IL2CPP_FILES)
    for name, pattern in files.items():
        _copy(_resolve(game.root, pattern), dest / name)
    for src in game.root.glob(LOCALE_GLOB):
        if "(dev)" not in src.name and "(key)" not in src.name:
            _copy(src, dest / "locales" / src.name)
    return dest


def _copy(src: Path, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    shutil.copyfile(src, tmp)
    tmp.replace(target)


def locale_bundles(snap: Path) -> list[tuple[str, str, Path]]:
    """(code, label, bundle) for each snapshotted locale: ("de", "German", ...), ("es-es", "Spanish (spain)", ...)."""
    out = []
    for p in sorted((snap / "locales").glob("*.bundle")):
        m = LOCALE_RE.match(p.name)
        if not m:
            continue
        groups = re.findall(r"\(([^)]+)\)", m[1])
        if not groups:
            continue
        label = m[1].split("(")[0].capitalize() + (f" ({', '.join(groups[:-1])})" if len(groups) > 1 else "")
        out.append((groups[-1], label, p))
    return out


_filters_dir: Path | None = None   # --filters-dir


def use_filters_dir(path: Path | None) -> None:
    """Use this folder as the game's loot-filter folder instead of looking for it (--filters-dir)."""
    global _filters_dir
    _filters_dir = path


def find_filters_dir() -> Path | None:
    """The game's loot-filter folder (the most recently used one if there are several: several
    Windows users, or several Proton prefixes), or the one --filters-dir named."""
    if _filters_dir is not None:
        return _filters_dir
    if os.name == "nt":
        candidates = [Path(os.environ.get("USERPROFILE", "")) / FILTERS_SUBPATH]
    else:
        candidates = list(Path("/mnt/c/Users").glob(f"*/{FILTERS_SUBPATH.as_posix()}"))
        for steam_root in _steam_roots():
            for lib, _ in _steam_libraries(steam_root):
                candidates.append(lib / PROTON_USER / FILTERS_SUBPATH)
    existing = [c for c in candidates if c.is_dir()]
    return max(existing, key=lambda p: p.stat().st_mtime) if existing else None


def prune_cache(cache_root: Path, keep_hash: str) -> list[Path]:
    """Remove game snapshots and Cpp2IL output of other game builds (a few hundred MB each)."""
    removed = []
    for sub in ("game", "cpp2il"):
        for d in (cache_root / sub).glob("*"):
            if d.is_dir() and d.name != keep_hash[:12]:
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d)
    return removed
