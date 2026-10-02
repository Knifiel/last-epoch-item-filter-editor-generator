## Last Epoch Item Filter editor/generator (beta)

Edit Last Epoch loot filters outside the game, and generate rules for uniques, leveling, idols,
BiS items, shattering and more - straight from your own game installation.

### What's new in v0.2.0

- **Leveling: jewelry and belts** with a build affix now show until the leveling cap (60)
  instead of switching off at 30. Belts moved from the armour rules to the jewelry ones.
- **Leveling: good bases** for every slot (weapons, off-hands, armour, jewelry, belts). Pick them
  in the Leveling tab; each slot's good bases get their own rule above the rest, with a stronger
  look, that stays on until the cap. Defaults: the jewelry and belt bases with resistance
  implicits that Raxxanterax's S5 filter picks for the campaign (Gold Ring, Bone and Gold
  Amulet, Spidersilk Sash, a few class relics).
- **Leveling: attribute toggles** (strength, dexterity, intelligence, attunement, vitality). They
  count like damage stats, also on weapons, and each adds the two-hander-only All Attributes.
- **Idols and Idol Altars generator**: the idol tab now also makes the idol altar rules - your
  preferred altars with your preferred altar affixes (with a beam), and below them a plainer
  rule for every other altar. The BiS section no longer has an altar rule.
- **Free up rules…** (Rules tab) for the 200-rule limit: remove section separators, the campaign
  leveling rules, or the rules for the most common uniques at 0-2 LP - with a preview, and
  Ctrl+Z to undo.

Upgrading from v0.1.0: your settings keep working. The `config.toml` in the program's folder
isn't replaced, so the new options use their defaults; delete it to get the new default with the
new options described. *Rebuild template* (New dialog) gives the new-filter template the new
layout.

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
Not affiliated with or endorsed by Eleventh Hour Games: this is a third-party program they aren't
responsible for, so please don't contact their support about it.
