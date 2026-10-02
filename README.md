# Last Epoch Item Filter editor/generator

Edit Last Epoch loot filters outside the game, and generate the tedious parts of them from the
game's own data: unique and set item rules, a leveling section for your build, idol rules,
best-in-slot, exalted, T8 and shatter rules - in a local web editor that works like the in-game
one, but with a rule list you can actually scroll through.

Free for non-commercial use ([license](#license)). Not affiliated with Eleventh Hour Games.

## Why

I liked Raxxsterax's approach to loot filters, but maintaining one by hand - and filling in
filters in-game - was a pain on my laptop: once a filter has a lot of rules, scrolling through
them in the game's menu gets slow. I also prefer to prepare a filter before making a character,
and having the whole thing outside the game saves a lot of time.

## Download and run

You need Last Epoch installed through Steam (Windows, or Linux with Proton / Steam Deck). The
program reads all item data from **your own game installation** - no game data comes with it.

1. Download the latest release from the [Releases page](../../releases/latest):
   `LastEpochItemFilterEditor-windows.zip` or `LastEpochItemFilterEditor-linux.tar.gz`.
2. Unpack it anywhere and start `LastEpochItemFilterEditor` (on Windows double-click the `.exe`;
   Windows may warn that it's from an unknown publisher - "More info" -> "Run anyway"; it isn't
   code-signed, and some antivirus programs flag unsigned one-file Python programs by mistake).
3. A console window opens (on Linux a terminal window) and the editor opens in your browser.
   Keep the window open while you use the editor; close it to stop.

The first start reads the game files and takes a minute or two: it also downloads two helper
tools once, [Cpp2IL](https://github.com/SamboyCoding/Cpp2IL) from GitHub and
[TypeTreeGeneratorAPI](https://github.com/K0lb3/TypeTreeGeneratorAPI) from PyPI (see
[How the data is read](#how-the-data-is-read)). Later starts are quick, and after a game patch it
re-reads the game by itself. If the game isn't found, the program asks for its folder (Steam:
right-click Last Epoch -> Manage -> Browse local files) and remembers it. If something goes wrong,
the window stays open with the error, which is also saved to `last-error.txt` in the program's
folder (below).

Filters are saved straight into the game's Filters folder; pick them in-game in the loot filter
menu. Every file the editor overwrites or deletes is backed up first. The program's own files
(game data it read, cache, backups, `config.toml`) live in `%APPDATA%\Last Epoch Item Filter Editor`
on Windows and `~/.local/share/last-epoch-item-filter-editor` on Linux.

## What it does

- **[Editor](#the-editor)**: every rule and condition the game has, drag-and-drop ordering,
  undo/redo, an item tester that shows which rule catches an item and why, affix values as the
  game shows them ("+24-30% Cold Penetration") with per-tier tables, and the game's own names in
  any of its languages.
- **New filter from a template**: legendary/unique and set rules grouped by drop rarity, LP and
  Weaver's Will, exalted and T8 rules, a BiS section, shatter rules, class item hide rules and a
  hide-everything-else rule, set up for the class you pick.
- **[Leveling generator](#leveling-section)**: pick damage types, build focus and weapon types;
  get campaign rules whose bases switch over every 10 levels.
- **[Idol generator](#idol-generator)**: per idol size and class, every affix that can roll on it.
- After a patch, **↻ [A] rules** refreshes the generated rules with new and changed uniques.

## Running from source

Python 3.12+:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m lefilter ui
```

The Last Epoch install is found through Steam's library list (Windows, WSL, native/Flatpak
Steam with Proton); pass `--game-dir` if that fails. Run from source, everything the program
writes stays in the project folder (`data/`, `.cache/`, `out/`, `templates/`).

### Command line

```bash
.venv/bin/python -m lefilter build              # template from [template].base -> out/<name>.xml + .md report
.venv/bin/python -m lefilter build --install    # ...and copy the filter into the game's Filters folder
.venv/bin/python -m lefilter build --standalone # only the generated rules, no base-filter rules
.venv/bin/python -m lefilter stats              # unique counts per category and LPL range
.venv/bin/python -m lefilter extract            # just refresh data/uniques.json
.venv/bin/python -m lefilter ui                 # filter editor + leveling generator in the browser
.venv/bin/python -m lefilter leveling           # print what the [leveling] config section generates
```

`build` re-extracts the game data by itself when the installed game build differs
from `data/uniques.json`. The report next to the XML lists every group with its
rules and member uniques (name, type, LPL, reroll chance) - check it after a patch.

## Configuring

Everything about the rules lives in `config.toml`: groups, LPL split points,
LP / WW thresholds, colours, emphasis, beams, sounds, section separators, which
base-filter rules the template keeps, and a pick list of build-defining Weaver's
Will uniques (normally left empty and done in-game, where rolls can be filtered too).
Groups and rules are written top-to-bottom in in-game order; the game applies the
first matching rule from the top.

Colours and sounds are the game's own numbers: create a rule in-game with the look
you want, then copy the number from the saved XML (`<color>`, `<SoundId>`).

## The template

With `[template] base` set (by default the editor's new-filter template,
`templates/New filter.xml`, generated when missing), the output is built from that filter:

- only base rules matched by a `keep` entry are carried over (by name, rarity,
  "blanket" = no item-type condition, section, or the catch-all hide rule), byte-for-byte
  and in their original order; everything else is left out;
- section separators - condition-less rules named with `----`/`====` - come along
  whenever a rule in their section is kept;
- the generated block goes where the first rule matching `drop` (the hand-made unique
  rules it replaces) was; rules from a previous run (names starting with `rule_prefix`,
  `[A] ` by default) are always replaced;
- optional `keep_above` patterns move kept rules directly above the generated block so
  they win over it.

Without `keep`, every base rule is kept (a plain merge). The base file is never modified. Generated filters carry an `[auto-uniques ...]`
tag in their description; `--install` refuses to overwrite a filter without that
tag unless `--force` is given, and backs up whatever it overwrites to `.cache/backups/`.
Keep editing the base filter in-game and re-run `build` to refresh the template; copy
the template in-game for each build and fill in the build slots there.

## Build slots

Every generated section (except the top one) ends with an empty, disabled
`EDIT FOR YOUR BUILD - <section>` rule (`[build_slots]` in the config). Being below
the section's rules, it only sees items those rules let fall through to the bottom
hide rule - e.g. a common 0LP unique while the COMMON 0LP rules are disabled. Add
the uniques/sets you want in-game (rolls can be filtered there too) and enable it.
Generated rules start with `[A] `, so if you ever use a filled-in filter as `base`,
rename the slot first or the next run replaces it.

## Class item hide rules

`[class_hide]` adds one disabled rule per class, e.g. `[A] Hide non-Sentinel class
non-legendary items`: it hides normal/magic/rare class-specific items that only the other
four classes can use. In the template they close the section before the generated block
(right after the exalted rules), so they also apply before the leveling rules. In a
build's copy, enable the one for its class (or list classes in `enabled_for`).

## How the data is read

Everything comes from the local client and stays on your computer. Nothing taken from the game
is part of this repository or its releases, and neither are the two tools that read the game's
code: they're downloaded on first use (pinned versions, checked against known SHA-256 sums).

| data | source in the client |
|---|---|
| unique list (IDs, LPL, reroll chance, flags) | `UniqueList` in `resources.assets` |
| base items: types, bases, level requirements | `MasterItemsList` in `StreamingAssets/LEAssetBundles/PermaLoad.bundle` |
| affixes: names, picker categories, item types, class | `MasterAffixesList` in `PermaLoad.bundle` |
| loot-filter colour / beam colour presets | `MasterColorList` in `PermaLoad.bundle` |
| filter icons and icon colours (saved to `data/filter_icons/`) | `LootFilterSettingsPanelUI` in `PermaLoad.bundle` (+ `monoscripts.bundle`) |
| affix value display rules (percent, rounding, plus sign, hidden values) | `MasterPropertyList`, `AbilityPropertyList`, `PlayerPropertyList` in `resources.assets` |
| idol altar stats | `Idol Altar Property List` in `PermaLoad.bundle` |
| names and affix texts, English and every game language (saved to `data/lang/`) | `Item_Names`, `Item_Affixes`, `Descriptors`, `Common` localization tables in `StreamingAssets/aa` |
| game version | PlayerSettings in `globalgamemanagers` |

The needed files are copied to `.cache/game/<build>/` first, so the game can be
running or patching meanwhile (snapshots of older builds are removed). `resources.assets`
ships without type trees, so the layouts of `UniqueList` and the property lists are
recovered from the game's `GameAssembly.dll` + `global-metadata.dat` with
[Cpp2IL](https://github.com/SamboyCoding/Cpp2IL) and
[TypeTreeGeneratorAPI](https://github.com/K0lb3/TypeTreeGeneratorAPI) (both downloaded once into
`.cache/tools/`; run from source, the pip-installed TypeTreeGeneratorAPI is used), once per game
build, into `.cache/schema/<build>/`. Each read must consume the asset exactly or it is rejected. Force a
rebuild with `extract --regen-schema`.

Derived values follow the game's own logic:

- LPL = the unique's LPL override if set, else its level requirement (override, else
  the base item's);
- categories: set (by drop tier) > Weaver's Will > cocooned > primordial > cannot drop randomly
  (special) > reroll-chance tiers. Tier cut-offs in `[rarity]` (0.25 / 0.5 / 0.75 / 0.95)
  reproduce lastepochtools' common ... extremely rare labels.

## The editor

`python -m lefilter ui` (what the downloadable program runs) starts a small local web app
(http://127.0.0.1:8765, standard library only, reachable from this computer only) and opens it
in the browser - on WSL in the Windows default browser. It edits the filters in the game's
Filters folder and in `out/`. The language menu switches item, unique and affix names to any
of the game's languages (the editor's own labels stay English).

- **Rules**: the rule list in in-game order (top = first match wins) with on/off
  toggles, colour, show/hide and a short summary of every condition; drag rows (or use
  ▲▼) to reorder, add / duplicate / delete rules. The editor on the right covers name,
  show/hide, colour, emphasis, sound, map icon, beam and every condition type the game
  writes (rarity, item type with bases, affixes with tier comparisons, character level,
  potential, class, uniques, corruption, faction, keys/shards/runes/glyphs ...). Affix and
  unique pickers search the game data and only list affixes that can roll on the rule's
  item types. *Preview at character level* dims rules that are switched off at that level.
- **Leveling generator**: see [below](#leveling-section); *Apply* puts the section into
  the open filter.
- **Idol generator**: see [below](#idol-generator).
- **Test an item**: describe an item (type, base, rarity, unique, affixes with tiers,
  LP/WW, corruption) and a character level; it shows the ground label the filter gives
  it and, for every rule, whether it matches and why not. Matching follows the game's
  code: the first enabled rule whose conditions all match decides, unmatched items are
  shown; an item-type condition honours its bases only when it has a single type.

- **New** starts a filter from the saved new-filter template, `templates/New filter.xml`
  (listed as "New-filter template"; open and edit it like any filter - it can't be deleted
  from the editor, and is regenerated from `config.toml` when missing or with *Rebuild
  template*). Top to bottom it has: the always-show personal/variant affix rule; a **BiS
  section** (per slot the slot's item type with no bases picked - so every base matches until
  you pick the right ones - and the build's affixes at T7+; one rule per weapon / off-hand
  type the build uses, plus an idol altar rule with every altar affix; own colour, emphasis
  and beam, `[bis]`); the exalted rules (`[[exalted_rule]]`: **all T8 items** first - any gear
  affix at tier 8, no item-type condition - then double T7, T7+T6, single T7 on uncorrupted
  items) and a show-all-legendary rule; the class item hide rules; a **shatter section**
  (`[shatter]`: magic/rare/exalted gear - idols can't be shattered - with rare-roll affixes:
  roll weighting <= 0.15, i.e. Hybrid Health and the "X and minion X penetration" ones; plus
  one rule per class for its class-specific affixes at T3+); the unique/set rules; and a rule
  hiding everything else at the bottom. That last one never hides shards, runes, glyphs or
  keys: the game only applies rules made of non-equipment conditions to those.
  In the dialog you pick the class (it switches on that class's hide and shatter rules,
  becomes the generators' class and sets the filter's class icon - or pick any of the game's
  filter icons and icon colours there; the icon button next to the filter name changes them
  for the open filter) and whether to fill the BiS rules with the Leveling tab's
  build affixes and weapons, add the leveling section, and add the idol section. The
  template's `[A]` rules are regenerated for the current game data on the way.
- **↻ [A] rules** (Rules tab) regenerates the open filter's `[A]` rules - unique/set
  groups, class hide rules, always-show affix rules - from `config.toml` and the current
  game data (e.g. new uniques after a patch), the way `build` does. Rules keep their on/off
  state and filled build slots stay as they are; Ctrl+Z undoes it.
- **Delete** removes the open filter's file after a confirmation; a copy goes to
  `.cache/backups/`.

Saving writes the game's own format (unchanged rules come out byte for byte) and backs
up the file it overwrites to `.cache/backups/`. Undo/redo: Ctrl+Z / Ctrl+Y; save: Ctrl+S.
The game picks the file up when the filter is (re)selected in-game. Rules whose layout
the editor doesn't know are kept verbatim and shown as RAW.

## Leveling section

Generated rules for campaign gear that fits a rough build profile, from toggles:

- **damage type** (physical, fire, cold, lightning, void, necrotic, poison): every
  ordinary gear affix named "<type> damage" or "<type> penetration" (fire/cold/lightning
  include elemental) - e.g. *Increased Physical Damage*, *Added Melee Physical Damage*,
  *Physical Penetration*;
- **build focus** (melee, spell, throwing, bow, minion, crit, damage over time, ailment
  chance): affixes with that keyword (*Increased Minion Damage*, *Minion Health* ...). With a
  melee/spell/bow/throwing focus picked, damage-type affixes for the other ways of hitting
  are dropped (no *Added Bow Physical Damage* for a melee build);
- **defence & utility** (health, resistances, armour, dodge, block, ward, mana,
  attributes, movement speed, regen/leech, cooldown) for armour, jewelry and off-hands;
- **class** (optional): allows that class's class-specific affixes and bases and drops
  affixes it can't roll. Set, corrupted, experimental, personal and idol affixes are
  never used.

**Weapons and off-hands** get one toggle per type. Their droppable bases below the level
cap (60) are grouped by level requirement into 10-level batches; each batch's rule is on
from the character level its batch starts at until the next batch starts, so the previous
rule switches off when the next one takes over, and everything is off from level 60. E.g.
a two-handed sword shows Bastard Sword (lvl 0) at character levels 0-9, Split Greatsword
(10) at 10-19, Imperial Warblade (24) at 20-29 ... Odachi (56) at 50-59; an empty batch
extends the previous window. By default each window has a highlighted rule for bases with
a build affix plus a plain rule for the rest (`weapon_mode`: `highlight` / `require` /
`bases`). **Armour** and **jewelry** get a rule for items with 2+ build affixes (until 60)
and one for items with a single build affix (until 30). Rarity defaults to magic, rare and
exalted; window size, cap, thresholds and looks are configurable.

The section's rules start with `[L] `; generating again replaces them in place.
Otherwise it goes directly under a separator named like LEVELING, else above the bottom
"hide everything" rule. In the editor the *Leveling generator* tab shows a timeline of
which bases are shown at which character level, the affixes each toggle picks and the
resulting rule count. `[leveling]` in `config.toml` holds the same options (the editor
can export them); with `enabled = true` `build` adds the section to the template too.

## Idol generator

The editor's *Idol generator* tab lists every idol kind that drops, by size (width ×
height, drawn as its inventory footprint) and class:

- all classes: 1x1 Small, 1x1 Minor, 2x1 Humble, 1x2 Stout;
- their Weaver ("enhanced") versions, which also roll the Weaver idol affixes;
- per class: 3x1 Grand, 1x3 Large, 4x1 Ornate, 1x4 Huge, 2x2 Adorned, and the class's
  3x1 / 1x3 Omen idols, which also roll the 4x1, 1x4 and 2x2 affixes.

Each kind shows exactly the affixes the game data lets roll on it (the affix's item types
and class restriction; corrupted-only affixes in their own group). Tick the ones you want
and whether one or both of an idol's two affixes must be among them; each kind with picks
becomes one show rule (item type + its bases + affix condition), optionally followed by a
rule hiding every other non-unique idol. Picks can be copied to another kind (e.g. a size's
Omen version). The section's rules start with `[I] `: applying again replaces them, and
opening a filter loads its picks back from them. Without a section yet it goes under a
separator named like IDOL, else at the top of the filter; the tab warns about rules above
it that catch idols by type alone. Heretical (enchanted) idols are crafted from class idols
and are separate bases, so each class idol's rule lists its heretical version too: one
thrown out of the inventory is shown like the idol it was made from.

## Tests

```bash
.venv/bin/python -m pytest
```

Releases are built by GitHub Actions (`.github/workflows/release.yml`, PyInstaller, Windows and
Linux) when a `v*` tag is pushed.

## Credits

- **Raxxsterax** - this tool exists because of his loot
  filters and the way they're built: drop-rarity and LP ladders for uniques, exalted and T8
  rules, BiS and shatter sections. His universal filter was the reference for the generated
  rules.
- **Eleventh Hour Games** - for Last Epoch and a loot filter system worth building tools for.
- [UnityPy](https://github.com/K0lb3/UnityPy) and
  [TypeTreeGeneratorAPI](https://github.com/K0lb3/TypeTreeGeneratorAPI) by K0lb3 - reading the
  game's Unity assets.
- [Cpp2IL](https://github.com/SamboyCoding/Cpp2IL) by Samboy063 - recovering the class layouts
  the game's assets are stored with.
- [lastepochtools.com](https://www.lastepochtools.com/) - the unique drop-rarity labels (common
  ... extremely rare) the rarity tiers are matched to.
- [PyInstaller](https://pyinstaller.org/) - the downloadable executables.

Bundled third-party licenses ship with each release in `THIRD_PARTY_LICENSES.txt`.

## License

Copyright (c) 2026 Ilia.C (Knifiel). Licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE): free to use, copy, modify and share for any
non-commercial purpose; selling it, or using it commercially, isn't allowed. Anyone you pass it
on to (changed or not) gets it under the same terms.

Last Epoch and everything in it - names, texts, images, game data - belong to Eleventh Hour
Games. None of it is included here, and this project isn't affiliated with or endorsed by
Eleventh Hour Games. The program reads game data from your own installation, on your own
computer, and never touches the running game; you use it at your own risk.
