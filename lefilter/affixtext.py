"""How affixes read on an item ("+4% Cold Penetration") and each tier's roll range, from game data.

Mirrors the game's tooltip code (TooltipItemManager.FormatAffix -> ModFormatting) per stat line:

- display rules (rounding, percentage, plus sign, hidden value) come from the stat's property
  info: PropertyList.GetPropertyInfo picks the ability's own list for ability stats (property 58:
  tags = ability, specialTag = its stat), the player property list for property 98 (tags = index),
  the idol altar list for altar stats (130), the Penetration info for "increased effect" of an
  ailment that adds penetration (43 with such an ailment in specialTag) and the master list for
  everything else;
- the prefix is GetPrefixModifier: added -> none / "of" (percentage of) / "to" (added to),
  increased -> increased / reduced (none when the stat's name already says it), more -> more /
  less; negative rolls use reduced / less and print without a sign;
- the text is the affix's display name (Item_Affix_<id>_DisplayName) with the prefix's word in
  front (AddModifierPrefix, which doesn't mind a doubled word) for single affixes not flagged
  useGeneratedNameForDisplayName; in English, a multi-affix property flagged so shows its own
  modDisplayName the same way; everything else uses the Descriptors entry
  "property,tags,specialTag[,extraTag],prefix" ("to" is put in front of added-to texts, which
  the table leaves out), else a text composed from the stat's name (English only, as the game);
- values are rounded the game's way (to even, in single precision) to the stat's step, then
  shown x100 (or x10) for percentages.

Each line keeps a language-independent recipe for its text (table, key, prefix word), so every
game language resolves the same text from its own tables (see i18n).

Tier values are for the affix's standard item type; on another item type the game scales them
by (1 + type modifier) / (1 + the affix's standard modifier) (AffixList.Affix.getModifier).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

ADDED, INCREASED, MORE, QUOTIENT = range(4)          # BaseStats.ModType
PREFIX_NONE, PREFIX_PERCENT_OF, PREFIX_ADDED_TO, PREFIX_INCREASED, PREFIX_REDUCED, PREFIX_MORE, PREFIX_LESS = range(7)
HUNDREDTH, INTEGER, TENTH, THOUSANDTH = range(4)      # PropertyRounding
STEP = {HUNDREDTH: 0.01, INTEGER: 1.0, TENTH: 0.1, THOUSANDTH: 0.001}
ABILITY_PROPERTY, PLAYER_PROPERTY, IDOL_ALTAR_PROPERTY = 58, 98, 130
AILMENT_EFFECT_PROPERTY, PENETRATION_PROPERTY = 43, 59     # IncreasedAilmentEffect, Penetration

# Common-table words AddModifierPrefix puts in front of a descriptor, per prefix.
WORD_KEYS = {PREFIX_PERCENT_OF: "ModFormat_PercentageOfPrefix_Of", PREFIX_ADDED_TO: "ModFormat_AddedToPrefix_To",
             PREFIX_INCREASED: "ModFormat_StatPrefix_Increased", PREFIX_REDUCED: "ModFormat_StatPrefix_Reduced",
             PREFIX_MORE: "ModFormat_StatPrefix_More", PREFIX_LESS: "ModFormat_StatPrefix_Less"}
ENGLISH_WORDS = {PREFIX_PERCENT_OF: "of", PREFIX_ADDED_TO: "to", PREFIX_INCREASED: "increased",
                 PREFIX_REDUCED: "reduced", PREFIX_MORE: "more", PREFIX_LESS: "less"}

# AT flags in the order their words lead a composed descriptor ("Minion Melee Fire Damage").
TAG_WORDS = [(8192, "Minion"), (16384, "Totem"), (512, "Melee"), (256, "Spell"), (1024, "Throwing"), (2048, "Bow"),
             (1, "Physical"), (2, "Lightning"), (4, "Cold"), (8, "Fire"), (16, "Void"), (32, "Necrotic"),
             (64, "Poison"), (128, "Elemental")]


@dataclass
class PropertyLists:
    """The game's stat display rules (PropertyList.GetPropertyInfo's sources)."""
    master: dict[int, dict] = field(default_factory=dict)
    default: dict = field(default_factory=dict)
    ability: dict[int, list[dict]] | None = None      # ability id -> its stats' infos
    ability_default: dict = field(default_factory=dict)
    player: list[dict] | None = None
    player_default: dict = field(default_factory=dict)
    altar: list[dict] | None = None
    altar_default: dict = field(default_factory=dict)
    penetration_ailments: set[int] = field(default_factory=set)   # ailment ids whose effect adds penetration

    @classmethod
    def from_game(cls, property_list: dict | None, ability_list: dict | None = None, player_list: dict | None = None,
                  altar_list: dict | None = None, penetration_ailments: set[int] | None = None) -> "PropertyLists":
        lists = cls(penetration_ailments=set(penetration_ailments or ()))
        if property_list:
            lists.master = {i["property"]: i for i in property_list["propertyInfoList"]}
            lists.default = property_list.get("defaultProperty") or {}
        if ability_list:
            lists.ability = {e["abilityID"]: e["properties"] for e in ability_list["list"]}
            lists.ability_default = ability_list.get("defaultProperty") or {}
        if player_list:
            lists.player, lists.player_default = player_list["list"], player_list.get("defaultProperty") or {}
        if altar_list:
            lists.altar, lists.altar_default = altar_list["list"], altar_list.get("defaultProperty") or {}
        return lists

    def info(self, prop: int, tags: int, special: int) -> dict:
        if prop == ABILITY_PROPERTY and self.ability is not None:
            props = self.ability.get(tags)
            return props[special] if props and special < len(props) else self.ability_default
        if prop == PLAYER_PROPERTY and self.player is not None:
            return self.player[tags] if tags < len(self.player) else self.player_default
        if prop == IDOL_ALTAR_PROPERTY and self.altar is not None:
            return self.altar[tags] if tags < len(self.altar) else self.altar_default
        if prop == AILMENT_EFFECT_PROPERTY and special in self.penetration_ailments:
            prop = PENETRATION_PROPERTY
        return self.master.get(prop, self.default)


def prefix_type(mod_type: int, info: dict, positive: bool = True) -> int:
    """ModFormatting.GetPrefixModifier."""
    if mod_type == ADDED:
        if info.get("displayAsPercentageOf"):
            return PREFIX_PERCENT_OF
        return PREFIX_ADDED_TO if info.get("displayAsAddedTo") else PREFIX_NONE
    if mod_type == INCREASED:
        if info.get("nameIncludesModifier") and positive:
            return PREFIX_NONE
        return PREFIX_INCREASED if positive else PREFIX_REDUCED
    if mod_type == MORE:
        return PREFIX_MORE if positive else PREFIX_LESS
    return PREFIX_NONE


def rounding(info: dict, mod_type: int, special: int = 0) -> int:
    """BasePropertyInfo.GetRounding: added -> the stat's rounding, increased -> hundredths,
    more -> the stat's per-specialTag override, else its rounding for more."""
    if mod_type == ADDED:
        return info.get("roundingForAdded", INTEGER)
    if mod_type == INCREASED:
        return HUNDREDTH
    for o in info.get("moreRoundingOverrides") or []:
        if o.get("specialTag") == special:
            return o["roundingForMore"]
    return info.get("roundingForMore", HUNDREDTH)


def display(info: dict, mod_type: int, rnd: int) -> tuple[int, bool]:
    """(multiplier, percent) as ModFormatting.AppendValue prints a rounded value."""
    if mod_type != ADDED:
        return 100, True
    if rnd == HUNDREDTH:
        return (10 if info.get("displayAddedAsTenthOfValue") else 100), True
    if rnd == THOUSANDTH and info.get("displayAddedAsPercentage"):
        return 100, True
    return 1, False


def sign(info: dict, mod_type: int, positive: bool) -> str:
    """FormatDescriptor's sign: only added values get one ("of ..." ones only when negative)."""
    if mod_type != ADDED:
        return ""
    if not positive:
        return "-"
    return "" if info.get("displayAsPercentageOf") or info.get("dontDisplayPlus") else "+"


def compose(prop: int, tags: int, prefix: int, infos: dict[int, dict]) -> str:
    """Last-resort descriptor: tag words + the stat's name."""
    name = infos.get(prop, {}).get("propertyName") or f"stat {prop}"
    words = [w for bit, w in TAG_WORDS if tags & bit]
    text = " ".join(words + [name])
    return f"{ENGLISH_WORDS[prefix]} {text}" if prefix in ENGLISH_WORDS else text


def with_word(text: str, prefix: int, words: dict[int, str], prefs: dict | None = None) -> str:
    """AddModifierPrefix: the prefix's word in front of the text (the game doesn't check for a
    doubled word). Language rules: the "to" / "of" words left out, and modifier words after the
    text with the value's place "{0}" before them (Korean: "방어도 {0} 증가")."""
    prefs = prefs or {}
    word = words.get(prefix)
    if not word:
        return text
    if (prefix == PREFIX_ADDED_TO and prefs.get("omit_added_to")) or (prefix == PREFIX_PERCENT_OF and prefs.get("omit_percent_of")):
        return text
    if prefix >= PREFIX_INCREASED:
        if prefs.get("values_prepend_modifiers"):
            word = "{0} " + word
        if prefs.get("modifiers_last"):
            return f"{text} {word}"
    return f"{word} {text}"


def resolve(source: list | None, tables: dict[str, dict[str, str]], words: dict[int, str],
            prefs: dict | None = None) -> str | None:
    """A line's text from its recipe [table, key, prefix word] in one language's tables."""
    if not source:
        return None
    table, key, word = source
    text = (tables.get(table) or {}).get(key)
    if not text:
        return None
    return with_word(text, word, words, prefs) if word else text


def text_source(affix: dict, p: dict, prefix: int, tables: dict[str, dict[str, str]]) -> list | None:
    """Where the line's text comes from: [table, key, prefix whose word goes in front (0 = none)]."""
    descriptors, names = tables.get("Descriptors", {}), tables.get("Item_Affixes", {})
    aid = affix["affixId"]
    if "affixProperties" not in affix and not affix.get("useGeneratedNameForDisplayName", 1):
        if (names.get(f"Item_Affix_{aid}_DisplayName") or "").strip():
            return ["Item_Affixes", f"Item_Affix_{aid}_DisplayName", prefix]
    tail = f"{p['property']},{p['tags']},{p['specialTag']}"
    for key in (f"{tail},{p.get('extraTag', 0)},{prefix}", f"{tail},{prefix}"):
        if descriptors.get(key):
            return ["Descriptors", key, PREFIX_ADDED_TO if prefix == PREFIX_ADDED_TO else 0]
    return None


def _properties(affix: dict) -> list[dict]:
    if "affixProperties" in affix:
        return affix["affixProperties"]
    return [{k: affix.get(k, 0) for k in ("property", "tags", "specialTag", "extraTag", "modifierType")}]


def _fallback_text(affix: dict, index: int, p: dict, info: dict, prefix: int, lists: PropertyLists) -> str:
    """English text when no table has one: the altar stat's name, the matching part of the
    affix's name, or a composed descriptor (never for ability / player / altar stats, whose tags
    aren't stat flags)."""
    props = _properties(affix)
    name = affix.get("affixDisplayName") or affix.get("affixName") or ""
    parts = name.split(" and ") if len(props) > 1 else [name]
    if p["property"] == IDOL_ALTAR_PROPERTY and info.get("propertyName"):
        text = info["propertyName"]
    elif p["property"] in (ABILITY_PROPERTY, PLAYER_PROPERTY, IDOL_ALTAR_PROPERTY) or (len(parts) == len(props) and parts[index]):
        text = parts[index] if len(parts) == len(props) and parts[index] else name
        text = text.removeprefix("Added ").strip()
    else:
        return compose(p["property"], p["tags"], prefix, lists.master)
    return with_word(text, prefix, ENGLISH_WORDS)


def affix_lines(affix: dict, lists: PropertyLists, tables: dict[str, dict[str, str]],
                words: dict[int, str] | None = None) -> list[dict]:
    """One dict per stat line: text (English), source (its recipe, see text_source), sign
    ("+", "-" or ""), step (rounding step), mult (x100 / x10 / x1), percent, hide (the game
    shows the text only) and per tier [min, max] of the shown magnitude (multi-affix lines after
    the first use the tier's extraRolls)."""
    words = words or ENGLISH_WORDS
    lines = []
    for i, p in enumerate(_properties(affix)):
        info = lists.info(p["property"], p["tags"], p["specialTag"])
        mod = p.get("modifierType", ADDED)
        rolls = []
        for t in affix["tiers"]:
            roll = t if i == 0 else (t["extraRolls"][i - 1] if i - 1 < len(t["extraRolls"]) else None)
            if roll is not None:
                rolls.append((roll["minRoll"], roll["maxRoll"]))
        values = [v for r in rolls for v in r]
        positive = not (values and all(v <= 0 for v in values) and any(v < 0 for v in values))
        prefix = prefix_type(mod, info, positive)
        rnd = rounding(info, mod, p["specialTag"])
        mult, percent = display(info, mod, rnd)
        source = text_source(affix, p, prefix, tables)
        if "affixProperties" in affix and not p.get("useGeneratedNameForDisplayName", 1) and (p.get("modDisplayName") or "").strip():
            text = with_word(p["modDisplayName"], prefix, words)   # English only: other languages use `source`
        else:
            text = resolve(source, tables, words) or _fallback_text(affix, i, p, info, prefix, lists)
        tiers = [sorted((round(abs(a), 6), round(abs(b), 6))) for a, b in rolls]
        lines.append({"text": text, "source": source, "sign": sign(info, mod, positive), "step": STEP[rnd],
                      "mult": mult, "percent": percent, "hide": bool(info.get("hideModifierValue")), "tiers": tiers})
    return lines


def _f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def format_value(value: float, line: dict) -> str:
    """One value as the tooltip shows it (no sign): rounded half to even in single precision to
    the line's step, x100 / x10 for percentages."""
    factor = round(1 / line["step"])
    v = round(_f32(_f32(value) * factor)) / factor * line["mult"]
    text = f"{v:.3f}".rstrip("0").rstrip(".")
    return f"{text}%" if line["percent"] else text


def format_line(line: dict, lo: float, hi: float, value_after: bool = False) -> str:
    """'+4% Cold Penetration', '+20-25 Health', '-5 to -10 ...'; value_after: the language puts
    the value after the text (Korean), "{0}" in the text marks its place."""
    if line["hide"]:
        return line["text"]
    a, b = format_value(lo, line), format_value(hi, line)
    s = line["sign"]
    if a == b:
        value = s + a
    elif s == "-":
        value = f"-{a} to -{b}"
    else:
        value = s + (f"{a.rstrip('%')}-{b}" if line["percent"] else f"{a}-{b}")
    text = line["text"]
    if "{0}" in text:
        return text.replace("{0}", value)
    return f"{text} {value}" if value_after else f"{value} {text}"
