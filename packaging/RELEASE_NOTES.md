## Last Epoch Item Filter editor/generator (beta)

Edit Last Epoch loot filters outside the game, and generate rules for uniques, leveling, idols,
BiS items, shattering and more - straight from your own game installation.

### What's new in v0.3.0

- **Leveling: a section per kind of gear.** Weapons, off-hands, armour and jewelry & belts
  each have their own affix toggles, and each only takes the affixes that can roll on it:
  attributes (Strength, Dexterity ...) count on armour, rings and relics, not on weapons;
  weapons get a single *All Attributes - two-handers only* toggle instead. A section offers
  only the toggles with something that rolls there; hover one to see where. Your earlier
  toggles carry over to every section.
- **Leveling: no defensive affixes on weapons** by default - health on kill or hit, leech,
  dodge and mana rarely beat a damage affix there. *Include defensive affixes* in the weapons
  section brings them back.
- **Leveling: class affixes.** With a class chosen, tick its class-specific affixes (skill
  levels such as *Level of Rive* ...), grouped by where they roll: helmet, body armour, relic.
  They count as build affixes in the armour and jewelry rules and in the BiS rules.
- **Leveling: good relics follow the class.** The default list keeps every class's good relics,
  but only the chosen class's are shown and used.
- **Base stats on hover**: hovering a base in a rule's item type condition, in the leveling
  good bases or among the preferred idol altars shows its level and class requirement, its
  implicits with the range they roll in, a weapon's base attack rate, and an idol altar's
  shape: its idol slots with the refracted ones marked. The game data is re-read once on the
  first start (that can take a minute or two).
- **The new-filter template updates itself** when a new version starts, keeping your edits:
  new rules are added where the template has them, rules you removed stay removed, rules you
  changed keep your version (a copy of each version's template, the old template's backup and
  a log of updates are kept next to it).
- **Leveling: leave out single affixes**: each toggle's affixes are listed with a checkbox, so
  you can drop e.g. Strength or Minion Melee and Bow Damage without touching the rules by
  hand. **Endurance** is its own toggle now (it was part of Armour; older settings with
  Armour get both).
- **Copy and paste affix lists** between affix rules and Best in slot slots (pasting adds
  the ones that can roll there; the copied list is kept, so it can seed new rules), and
  *Copy affixes to…* other BiS slots.
- **Shorter program name**: the executable is now `LEIFEG` (Last Epoch Item Filter Editor /
  Generator). Your settings and filters stay where they were; delete the old
  `LastEpochItemFilterEditor` executable.
- **Uniques in the rule editor**: quick filters by item type, the unique's tooltip on hover
  (base and implicits, level, LP level, modifiers with ranges, set items marked, lore), and
  required roll ranges per picked unique, typed as values like in-game.
- **Best in slot generator** (new tab): per slot pick concrete bases (weapons across several
  weapon types), concrete affixes and two tiers - best in slot (default 2+ at T7, with a beam)
  and good (1+ at T6) - each with an optional minimum forging potential. It replaces the
  filter's BiS rules; opening a filter loads its picks back.
- **New is a blank slate by default**: the BiS rules, the leveling and the idol section are
  opt-in (each tab can apply its section later). *Save as* also sets the in-game name (the
  game lists filters by it, not by the file name).
- **Idol section after the shatter section**: a new idol section now goes right before the
  uniques instead of at the top. **Reorder generated sections** (Rules tab) moves the BiS,
  idol and leveling sections of an existing filter back to their places.
- **Weaver's Will uniques in three brackets**: 19+ WW (emphasized, in red like the best LP
  uniques), 15-18 WW (emphasized) and 0-14 WW, instead of 17+ and 0-16. A `config.toml` from an
  earlier version gets them too unless you changed its Weaver rules; existing filters get them
  with *↻ [A] rules*.
- **Add missing sections…** (Rules tab): gives a filter that didn't start from *New* - such as
  the uniques-only one `build --standalone` writes, which the editor now points out - the
  template's BiS, exalted and legendary, class hide, shatter and hide-everything rules.
- The BiS weapon rule of a build without a weapon no longer lists affixes that can't roll on
  weapons.

### What's new in v0.2.0

- **Leveling: jewelry and belts** with a build affix now show until the leveling cap (60)
  instead of switching off at 30. Belts moved from the armour rules to the jewelry ones.
- **Leveling: good bases** for every slot (weapons, off-hands, armour, jewelry, belts). Pick them
  in the Leveling tab; each slot's good bases get their own rule above the rest, with a stronger
  look, that stays on until the cap. Defaults: the jewelry and belt bases with resistance
  implicits that Raxxanterax's S5 filter picks for the campaign (Gold Ring, Bone and Gold
  Amulet, Spidersilk Sash, a few class relics).
- **Leveling: attribute toggles** (strength, dexterity, intelligence, attunement, vitality). Each
  adds the two-hander-only All Attributes.
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

- **Windows**: `LEIFEG-windows.zip` - unzip it anywhere and double-click `LEIFEG.exe`.
- **Linux** (Steam with Proton, Steam Deck, Arch ...): `LEIFEG-linux.tar.gz` - unpack it and
  run `./LEIFEG`.

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
