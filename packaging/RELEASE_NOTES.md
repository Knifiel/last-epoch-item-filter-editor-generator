## Last Epoch Item Filter editor/generator (beta)

Edit Last Epoch loot filters outside the game, and generate rules for uniques, leveling, idols,
BiS items, shattering and more - straight from your own game installation.

### Download

- **Windows**: `LastEpochItemFilterEditor-windows.zip` - unzip it anywhere and double-click
  `LastEpochItemFilterEditor.exe`.
- **Linux** (Steam with Proton, Steam Deck, Arch ...): `LastEpochItemFilterEditor-linux.tar.gz` -
  unpack it and run `./LastEpochItemFilterEditor`.

A console window (on Linux a terminal window) opens and the editor opens in your web browser.
Keep the window open while you use the editor; close it to stop. If something goes wrong, the
window stays open with the error, which is also saved to `last-error.txt` in the program's folder
(`%APPDATA%\Last Epoch Item Filter Editor` / `~/.local/share/last-epoch-item-filter-editor`).

### Requirements

- Last Epoch installed through Steam. The program reads item and affix data from your own
  installation - no game data is included in this download. The first start takes a minute or
  two: it reads the game files and downloads two helper tools once (Cpp2IL from GitHub,
  TypeTreeGeneratorAPI from PyPI). Later starts are quick.
- If it can't find the game, it asks for the game folder (Steam: right-click Last Epoch ->
  Manage -> Browse local files) and remembers it.
- Filters are saved to the game's Filters folder; select them in-game in the loot filter menu.
  Files the editor overwrites or deletes are backed up first.

Windows may warn that the program is from an unknown publisher (it isn't code-signed): choose
"More info" -> "Run anyway". Some antivirus programs flag unsigned one-file Python programs by
mistake; the source code and the automated build that produced this file are in the
program's GitHub repository.

Free for non-commercial use only (PolyForm Noncommercial 1.0.0, see `LICENSE`); not for sale.
Not affiliated with or endorsed by Eleventh Hour Games.
