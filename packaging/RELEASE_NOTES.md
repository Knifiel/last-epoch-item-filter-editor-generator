## Last Epoch Item Filter editor/generator (beta)

Edit Last Epoch loot filters outside the game, and generate rules for uniques, leveling, idols,
BiS items, shattering and more - straight from your own game installation.

### What's new in v0.3.3

- **Steam Deck / Linux**: double-clicking `LEIFEG` in the file manager now works - the terminal
  window it opens used to close right away (the copy started in it couldn't load its own files), so
  it only ran when started from a terminal.
- **Touch screens** (Steam Deck desktop mode): press and hold where a mouse would hover - a base,
  an affix or its values, a unique, a toggle, a button - to see its tooltip or what it does. The
  tooltip stays until the next touch; lifting the finger doesn't click.
- **Remove an affix everywhere**: *Remove an affix…* (Rules tab, and now on the Leveling, Best in
  slot and Idols tabs too) takes the affix out of the open filter's rules and the three tabs'
  picks in one go - no more apply, back to Rules, remove. It lists every affix used anywhere with
  where, lets you untick places to leave it in, and *Undo* in the dialog puts it all back. Its
  filter box remembers what you typed (selected, so typing replaces it).
- **Rules to fill in stand out**: the template's rules waiting for your build's picks (build
  slots, *BIS - … (pick bases)*, the class hide rule) get a *to fill in* mark in the rule list,
  a count with *Next* above it, and a note in the editor saying what each needs. Still optional.
- **Weaver's Will and primordial uniques on their own**: the uniques picker gets *Show only Weaver's
  Will uniques* and *Show only Primordial uniques* filters (they combine with the item type ones), and
  the *EDIT FOR YOUR BUILD - WEAVER'S WILL* and *- PRIMORDIAL* slots open with theirs on.
- **Cocooned items** (boxes holding a random unique) move to one rule, *SHOW ALL COCOONED ITEMS* (on),
  right below *SHOW ALL LEGENDARY ITEMS*; no unique rule lists them any more. The section left behind is
  *--- PRIMORDIAL ---* with its build slot *EDIT FOR YOUR BUILD - PRIMORDIAL*. Your template and
  *↻ [A] rules* make the change: a filled slot keeps its uniques, and a cocooned rule you switched off stays off.

### What's new in v0.3.2

- The always-show rule at the top now takes personal affixes only (*ALWAYS SHOW - PERSONAL
  AFFIXES*): Variant mods only come on two non-random uniques (Unsated Rage, Withstand the
  Elements), which the unique rules show already. Your new-filter template gets it when this
  version starts (unless you changed that rule in config.toml); existing filters with *↻ [A] rules*.
- **Uniques at the bottom**: *Reorder generated sections* moves the unique & set rules (Weaver's
  Will included) right above the leveling section, so the exalted, BiS and idol sections come
  first - new filters already have that order. Fixed: refreshing the `[A]` rules of a filter that
  still had the five old class hide rules moved the uniques up next to the shatter section.
- The new-filter template's update also regenerates its `[A]` rules the way *New* does (current
  game data, e.g. uniques added by a patch; on/off states, filled build slots and the class hide
  rule's classes kept).

### What's new in v0.3.1

- **Affixes named and ordered like the in-game picker**: affix lists and picked affixes are
  grouped under the game's headers and categories in its order (Core · Attributes, Offensive ·
  Melee, ..., Defensive · Health ...), each category's affixes by name - in the rule editor, the
  Best in slot and Idols tabs, the item tester and *Remove an affix…*. Picked affixes sit under
  their category's subheader. Names are the picker's too, e.g. *Physical Damage* instead of
  *Increased Physical Damage*, and idol altar affixes by their effect (*increased Mana Regen per
  Equipped Ornate Idol*) instead of all being *Maximum Idols Equipped*; searching still finds
  the old names, and config.toml lists naming affixes the old way keep working. The game data
  is re-read once on the first start (a minute or two).
- **Quick filter for affix lists** (rule editor, Best in slot): tick categories to list only
  those (with how many each has), and sort by category or by name.
- Idol altar affixes stop at T7 in tier tables and the item tester: T8 only rolls on equipment.
  Variant mods (fixed mods of unique variants) show their one value instead of eight identical
  tiers.
- Uniques the game hides from players (Sharktooth Saw, Heirloom of Light, Egg of the Forgotten)
  are left out of the generated unique rules and the uniques picker, as in-game; *↻ [A] rules*
  takes them out of existing filters.
- **One class hide rule instead of five**: *Hide items of other classes (select what classes
  you don't want to see)*. New ticks every class but yours and switches it on; tick the ones
  you don't want to see in the rule editor (refreshing keeps them). It frees four rule slots.
  Existing filters: *↻ [A] rules* turns the five rules into this one, hiding what the
  switched-on ones hid.
- **Shatter section at the top**, right below the always-show rule and above the class hide
  rule: a class-specific affix gives an item its class's requirement, so the shatter rules
  for other classes' affixes never fired below the class hide rules. The shatter rules now
  take magic and rare items only (`[shatter] rarity`) - exalted ones have the exalted rules.
- **Restore exalted section…** (Rules tab): puts the template's exalted & legendary section back
  into a filter - only the rules it lacks (e.g. the corrupted rules, for a filter made before
  v0.3.0) or all of them in place of the filter's.
- The idol section goes right before the uniques (it used to follow the shatter section).
- Your new-filter template gets the new layout once when this version starts; existing
  filters get it with **Reorder generated sections** (Rules tab). A new filter has it already.

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
- **Corrupted items**: the template gets *SHOW ALL CORRUPTED ITEMS* (switched on: normal to
  exalted items that dropped corrupted, for builds after corrupted affixes) and *EXALTED -
  CORRUPTED DOUBLE T7* below the exalted rules, which stay for uncorrupted items.
- **Class hide rules at the top**, right below the always-show rule, so other classes' items
  stay hidden from every rule below - corrupted, BiS, shatter and leveling ones included.
- **Idol section before the uniques**: a new idol section now goes right before the
  uniques instead of at the top. **Reorder generated sections** (Rules tab) moves the class
  hide rules, BiS, idol and leveling sections of an existing filter back to their places.
- **Idols: heretical idols' Enchanted affixes** are offered on each class idol (its rule covers
  the heretical version), and **Omen idols list all their corrupted affixes** - those of the
  4x1, 1x4 and 2x2 sizes too (30 on a Grand Omen idol, not 10).
- **Idols: copy picks to every other idol kind** at once; each takes the ones that can roll on it.
- **Remove an affix…** (Rules tab): take one affix out of every rule at once.
- **Weaver's Will uniques in three brackets**: 19+ WW (emphasized, in red like the best LP
  uniques), 15-18 WW (emphasized) and 0-14 WW, instead of 17+ and 0-16.
- **Upgrading from v0.2.0**: a `config.toml` from an earlier version gets the new Weaver brackets
  and corrupted rules too, unless you changed those settings; the new-filter template updates
  itself (see above). Existing filters: *↻ [A] rules* gives them the Weaver brackets and moves
  the class hide rules up, *Add missing sections…* doesn't add rules to a section the filter
  already has - *Restore exalted section…* (v0.3.1) adds the two corrupted rules.
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
