from pathlib import Path

import pytest

from lefilter import game


@pytest.fixture
def steam(tmp_path, monkeypatch):
    """A Linux Steam root with a second library holding the game and its Proton prefix."""
    root, lib = tmp_path / "Steam", tmp_path / "lib"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "0"\n {{\n  "path" "{root}"\n  "apps" {{ "250900" "1" }}\n }}\n'
        f' "1"\n {{\n  "path" "{lib}"\n  "apps" {{ "{game.APP_ID}" "123" }}\n }}\n}}\n')
    data = lib / "steamapps" / "common" / game.GAME_FOLDER / game.DATA_FOLDER
    data.mkdir(parents=True)
    (data / "build_hash.txt").write_text("abcdef0123456789\n")
    (lib / "steamapps" / f"appmanifest_{game.APP_ID}.acf").write_text('"buildid" "777"')
    monkeypatch.setattr(game, "STEAM_ROOTS", [root])
    monkeypatch.setattr(game, "_registry_steam_roots", lambda: [])
    monkeypatch.setattr(game.os, "name", "posix")
    return root, lib


def test_finds_the_game_in_any_library(steam):
    _, lib = steam
    g = game.find_game()
    assert g.root == lib / "steamapps" / "common" / game.GAME_FOLDER
    assert (g.short_hash, g.steam_build) == ("abcdef012345", "777")


def test_missing_game_says_how_to_point_at_it(steam, tmp_path):
    with pytest.raises(game.GameNotFound, match="--game-dir"):
        game.find_game(tmp_path / "nowhere")


def test_filters_folder_in_the_proton_prefix(steam, monkeypatch):
    _, lib = steam
    monkeypatch.setattr(game, "Path", _NoWslPath)
    filters = lib / game.PROTON_USER / game.FILTERS_SUBPATH
    assert game.find_filters_dir() is None
    filters.mkdir(parents=True)
    assert game.find_filters_dir() == filters


class _NoWslPath(type(Path())):
    """Path whose /mnt/c/Users glob finds nothing, so a WSL machine running the tests isn't searched."""
    def glob(self, pattern, **kw):
        return iter(()) if str(self) == "/mnt/c/Users" else super().glob(pattern, **kw)


def test_prune_cache_keeps_the_current_build(tmp_path):
    for sub in ("game", "cpp2il"):
        for h in ("abcdef012345", "oldbuild0000"):
            (tmp_path / sub / h).mkdir(parents=True)
    (tmp_path / "schema" / "oldbuild0000").mkdir(parents=True)
    removed = game.prune_cache(tmp_path, "abcdef0123456789")
    assert sorted(p.relative_to(tmp_path).as_posix() for p in removed) == ["cpp2il/oldbuild0000", "game/oldbuild0000"]
    assert (tmp_path / "game" / "abcdef012345").is_dir() and (tmp_path / "schema" / "oldbuild0000").is_dir()
