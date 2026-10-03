"""Game-text translations for the editor's language selector, from the game's own string tables.

For every locale the game ships, data/lang/<code>.json maps ids to that locale's names: unique
items, item types and bases, affixes (the loot-filter picker's names), and each affix stat line,
resolved from the same table entries and prefix words as the English text (affixtext); and the
editor's own texts that are the game's loot-filter words (UI_GAME_TERMS: "Rarity", "Add", class
and slot names ...). The editor overlays them on the English data and its own catalog
(web/i18n). Rule names written into filters stay English.

Language rules from the game's language models (DescriptorPreferences): Korean puts the value
after the text, leaves out the "to" / "of" words, puts stat modifier words last with the value
in front of them ("방어도 {0} 증가") and drops the value slot "{0}" from affix names.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import affixtext

TEXT_TABLES = ("Item_Affixes", "Descriptors", "Common")
TABLES = ("Item_Names", *TEXT_TABLES, "UI")
# The editor's own texts that are the game's loot-filter words: English text -> the game's UI table key, or
# (key, the game's English) where the game words it a little differently. At extraction each language gets the
# game's wording for them ("ui"), laid over the editor's catalog. Made with packaging/translate_ui.py terms and
# checked by hand (same meaning where the editor uses it); a key whose English no longer reads so is left out.
_LF = "LootFilter_"
UI_GAME_TERMS: dict[str, str | tuple[str, str]] = {
    # condition names (the rule editor's "Add Condition" list)
    "Rarity": "LootFilter_RarityCondition_Rarity_Label", "Item Type": "Rule_Holder_Item Type", "Affix": "Rule_Holder_Affix",
    "Character Level": "Rule_Holder_Character Level", "Potential": "Rule_Holder_Potential",
    "Class Requirement": "Rule_Holder_Class Requirement", "Uniques": "Rule_Holder_Uniques", "Corruption": "Rule_Holder_Corruption",
    "Faction": ("Rule_Holder_Factions", "Factions"), "Affix Count": "Rule_Holder_Affix Count",
    "Item Level": ("Rule_Holder_Level", "Level"), "Keys": ("Rule_Holder_Keys", "Resources"),
    "Crafting Materials": "Rule_Holder_Crafting Materials", "Resonances": "Rule_Holder_Resonances",
    "Woven Echoes": "Rule_Holder_Woven Echoes", "Glyphs": "Rule_Holder_Glyphs", "Runes": "Rule_Holder_Runes",
    # rarities, show / hide, beams
    "Normal": "RarityCondition_Normal", "Magic": "RarityCondition_Magic", "Rare": "RarityCondition_Rare",
    "Exalted": "RarityCondition_Exalted", "Unique": "RarityCondition_Unique", "Set": "RarityCondition_Set",
    "Legendary": "RarityCondition_Legendary", "Show": "RuleDescription_Show", "Hide": "RuleDescription_Hide",
    "None": (_LF + "RuleBeamSize_NONE", "NONE"), "Smallest": (_LF + "RuleBeamSize_SMALLEST", "SMALLEST"),
    "Very small": (_LF + "RuleBeamSize_VERYSMALL", "VERY SMALL"), "Small": (_LF + "RuleBeamSize_SMALL", "SMALL"),
    "Medium": (_LF + "RuleBeamSize_MEDIUM", "MEDIUM"), "Large": (_LF + "RuleBeamSize_LARGE", "LARGE"),
    "Very large": (_LF + "RuleBeamSize_VERYLARGE", "VERY LARGE"), "Largest": (_LF + "RuleBeamSize_LARGEST", "LARGEST"),
    "Map icon": (_LF + "MapIcon_Title", "Map Icon"), "Sound": _LF + "Sound_Title",
    # condition editors
    "Class": _LF + "ClassCondition_Class_Label", "Type": _LF + "TypeCondition_Type_Label",
    "Prefixes": _LF + "AffixCountCondition_Prefixes_Label", "Suffixes": _LF + "AffixCountCondition_Suffixes_Label",
    "prefixes": _LF + "AffixCountCondition_Prefixes", "suffixes": _LF + "AffixCountCondition_Suffixes",
    "Any": _LF + "AffixCountCondition_HasSealed_Options_Any", "Not Sealed": _LF + "AffixCountCondition_HasSealed_Options_HasNoSealed",
    "Sealed": _LF + "AffixCountCondition_HasSealed_Options_HasSealed",
    "Sealed Prefix": _LF + "AffixCountCondition_HasSealed_Options_HasSealedPrefix",
    "Sealed Suffix": _LF + "AffixCountCondition_HasSealed_Options_HasSealedSuffix",
    "Affixes": "AffixCondition_Affixes", "Modifiers": _LF + "UniquesCondition_Modifiers_Label",
    "Weaver's Will": _LF + "RarityCondition_WeaversWill", "Weaver's will": (_LF + "RarityCondition_WeaversWill", "Weaver's Will"),
    "Weaver's touch": (_LF + "RarityCondition_WeaversTouch", "Weaver's Touch"),
    "Legendary potential": (_LF + "RarityCondition_LegendaryPotential", "Legendary Potential"),
    "Forging potential": ("Bazaar_Filter_ForgingPotential", "Forging Potential"),
    "Primordial": "Bazaar_Filter_Primordial", "Corrupted": "Bazaar_Filter_Corrupted",
    "Sets": "ContentGenerator_UniqueModifiers_Section_Sets",
    "at least": "MultiPicker_RequireAtLeast", "to": "Crafting_Generic_to", "Tier": "OmenWindow_Tier",
    "Description": _LF + "ConfigureLoot_Description_Label", "Filter icon": (_LF + "ConfigureLoot_FilterIcon_Label", "Filter Icon"),
    "New filter": (_LF + "Header_New_Filter", "New Filter"),
    # item categories, slots, classes, factions
    "One Handed Weapons": "MultiSelection_Item_Header_One Handed Weapons", "Two Handed Weapons": "MultiSelection_Item_Header_Two Handed Weapons",
    "Off-Hand": "MultiSelection_Item_Header_Off-Hand", "Off-hand": ("MultiSelection_Item_Header_Off-Hand", "Off-Hand"),
    "Armor": "MultiSelection_Header_Armor", "Accessories": "MultiSelection_Item_Header_Accessories",
    "Idols": "MultiSelection_Item_Header_Idols", "Altars": "MultiSelection_Item_Header_Altars",
    "Idol altar": ("ItemContainer_123_Name", "Idol Altar"), "Other": "GameGuide_Panel_Other_Category_Tab",
    "Weapons": "MultiSelection_Header_Weapons", "Helmet": "ItemContainer_2_Name", "Body armour": ("ItemContainer_3_Name", "Body Armor"),
    "Gloves": "ItemContainer_6_Name", "Belt": "ItemContainer_7_Name", "Boots": "ItemContainer_8_Name",
    "Amulet": "ItemContainer_11_Name", "Relic": "ItemContainer_12_Name",
    "Primalist": "MultiSelection_Header_Primalist", "Mage": "MultiSelection_Header_Mage", "Sentinel": "MultiSelection_Header_Sentinel",
    "Acolyte": "MultiSelection_Header_Acolyte", "Rogue": "MultiSelection_Header_Rogue",
    "All classes": ("MultiSelection_Header_All Classes", "All Classes"),
    "Circle of Fortune": "Factions_CircleofFortuneName", "Merchant's Guild": "Factions_MerchantGuildName",
    "Forgotten Knights": "Factions_ForgottenKnightsName", "Omen": "CircleOfFortune_ProphecyTarget_3",
    # tooltips
    "Implicits": "ItemTooltipV2_Implicits_Heading", "Set bonuses": ("ItemTooltipv2_SetBonuses_Heading", "Set Bonuses"),
    "Requires Level {n}": ("ItemTooltipV2_RequiresLevel", "Requires Level {0}"),
    # build toggles (stats)
    "Physical": "StatsPanel_Resistances_Physical_Label", "Fire": "StatsPanel_Resistances_Fire_Label",
    "Cold": "StatsPanel_Resistances_Cold_Label", "Lightning": "StatsPanel_Resistances_Lightning_Label",
    "Void": "StatsPanel_Resistances_Void_Label", "Necrotic": "StatsPanel_Resistances_Necrotic_Label",
    "Poison": "StatsPanel_Resistances_Poison_Label", "Strength": "StatsPanel_Attributes_Strength_Name",
    "Dexterity": "StatsPanel_Attributes_Dexterity_Name", "Intelligence": "StatsPanel_Attributes_Intelligence_Name",
    "Attunement": "StatsPanel_Attributes_Attunement_Name", "Vitality": "StatsPanel_Attributes_Vitality_Name",
    "Health": "StatsPanel_MainStats_Health_Name", "Mana": "StatsPanel_MainStats_Mana_Name",
    "Resistances": "StatsPanel_Resistances_Header", "Endurance": "StatsPanel_DefenseStats_Endurance_Label",
    "Armour (defence stat)": ("StatsPanel_Defenses_Armour_Label", "Armor"),
    "Dodge": "StatsPanel_Defenses_Dodge_Label", "Block": "GameGuide_Panel_Block_Tab", "Ward": "GameGuide_Panel_Ward_Tab",
    "Movement speed": ("StatsPanel_MainStats_MoveSpeed_Name", "Movement Speed"), "Minion": ("StatsPanel_Tabs_Minion", "minion"),
    "Damage over time": ("StatsPanel_DamageStats_IncreasedDamageOverTime_Name", "Damage Over Time"),
    # non-equipment flags (as the game's loot filter names them)
    "All Glyphs": _LF + "GlyphCondition_AllGlyphs", "All Runes": _LF + "RuneCondition_AllRunes",
    "All Shards": (_LF + "NonEquippableCondition_AllShards", "All shards"),
    "Common Shards": (_LF + "NonEquippableCondition_Common", "Common shards"),
    "Rare Shards": (_LF + "NonEquippableCondition_Rare", "Rare shards"),
    "Arena Keys": (_LF + "KeysCondition_ArenaKey", "Arena Key"),
    "Arena Keys of Memory": (_LF + "KeysCondition_ArenaKeyOfMemory", "Arena key of memory"),
    "Dungeon Keys": (_LF + "KeysCondition_DungeonKey", "Dungeon Key"),
    "Dungeon Charms": (_LF + "KeysCondition_DungeonCharm", "Dungeon Charm"),
    "Lizard Tails": (_LF + "KeysCondition_LizardTail", "Lizard Tail"),
    "Merchant Token": (_LF + "KeysCondition_MerchantTokens", "Merchant's guild tokens"),
    "Primordial Materials": (_LF + "KeysCondition_PrimordialMaterial", "Primordial Material"),
    "Crystallized Heart": _LF + "KeysCondition_CrystallizedHeart", "Harbinger Eye": _LF + "KeysCondition_HarbingerEye",
    "Temporal Keystone": _LF + "KeysCondition_TemporalKeystone",
    "Woven Echoes Unpurchasable": (_LF + "WovenEchoesCondition_Unpurchaseable", "Cannot be purchased from Masque"),
    **{f"Glyph of {g}": (_LF + f"GlyphCondition_GlyphOf{g}", f"Glyph of {'Chaos' if g == 'Stability' else g}")
       for g in ("Hope", "Stability", "Order", "Despair", "Envy")},
    **{f"Rune of {r}": (_LF + f"RuneCondition_{r}", f"Rune of {r}")
       for r in ("Shattering", "Refinement", "Removal", "Discovery", "Shaping", "Ascendance", "Creation", "Weaving",
                 "Havoc", "Redemption", "Evolution", "Corruption")},
    # buttons
    "Add": "Button_Label_Add", "Save": "Button_Label_Save", "Cancel": "Button_Label_Cancel", "Close": "Modal_Close",
    "Delete": "Prompt_Delete", "Copy": "Prompt_Copy", "Replace": "Button_Label_Replace",
}
# where a language's game text doesn't fit the editor's use (a grammatical case of a sentence it came from ...)
UI_TERM_SKIP = {"pl": {"Exalted", "Affixes", "Forging potential"}, "ru": {"Forging potential"}, "fr": {"Sets"}}


def ui_terms(ui_en: dict[str, str], ui: dict[str, str], code: str = "") -> dict[str, str]:
    """The editor's texts in the game's words for one language (ui: its UI table, ui_en: the English one): the
    case follows the editor's English ("LARGE" -> "Large", "uniques" -> "Uniques"), "{0}" its placeholders; the
    game's stray brackets and full stops ("(Unique)", "Remplacer.") go."""
    out = {}
    for text, ref in UI_GAME_TERMS.items():
        key, game_en = ref if isinstance(ref, tuple) else (ref, text.strip())
        word = (ui.get(key) or "").strip()
        if (ui_en.get(key) or "").strip() != game_en or not word or text in UI_TERM_SKIP.get(code, ()):
            continue   # the game says something else there now, or nothing
        if word.startswith("(") and word.endswith(")") and not game_en.startswith("("):
            word = word[1:-1].strip()
        if word.endswith(".") and not game_en.endswith("."):
            word = word[:-1].rstrip()
        if game_en.isupper() and not text.isupper():
            word = word.lower()
        if text[:1].isupper():
            word = word[:1].upper() + word[1:]
        names = re.findall(r"\{(\w+)\}", text)
        word = re.sub(r"\{(\d)\}", lambda m: "{%s}" % names[int(m.group(1))] if int(m.group(1)) < len(names) else m.group(0), word)
        if sorted(re.findall(r"\{\w+\}", word)) == sorted("{%s}" % n for n in names):
            out[text.strip()] = word
    return out
GRAMMAR_TAG = re.compile(r"(\[[MFNmfn]?[sp]\])")     # [ms] [fs] [ns] [p] ...: gender / number for the game's grammar
NAME_BRACES = re.compile(r"\{([^{}0-9][^{}]*)\}")    # Japanese {skill name} marks; {0} (value slot) stays
LANGUAGE_PREFS = {"ko": {"value_after": True, "omit_added_to": True, "omit_percent_of": True,
                         "modifiers_last": True, "values_prepend_modifiers": True, "strip_value_tag": True}}


def clean(text: str | None) -> str | None:
    """Displayable text: name braces removed, "{0}" kept as the value's place; of gendered
    variants ("[ms]Verfluchter[fs]Verfluchte...") the masculine singular, else the first."""
    if not text:
        return text
    parts = GRAMMAR_TAG.split(text)
    if len(parts) > 3:   # several variants: lead text + (marker, variant) pairs
        variants = list(zip(parts[1::2], parts[2::2]))
        chosen = next((v for m, v in variants if m.lower() == "[ms]" and v.strip()), None) \
            or next((v for _, v in variants if v.strip()), "")
        text = parts[0] + chosen
    else:
        text = "".join(parts[::2])
    return NAME_BRACES.sub(r"\1", text).strip()


def strip_value_tag(text: str) -> str:
    """Localization.StripValueTag: "{0}" out of a name, spaces collapsed."""
    return re.sub(r"\s+", " ", text.replace("{0}", "")).strip()


def build_language(tables: dict[str, dict[str, str]], data: dict, code: str = "", ui_en: dict[str, str] | None = None) -> dict:
    """ui_en: the English UI table (cleaned), for the editor's texts in the game's words."""
    tables = {t: {k: clean(v) for k, v in tables.get(t, {}).items()} for t in TABLES}
    names, affix_names = tables["Item_Names"], tables["Item_Affixes"]
    prefs = LANGUAGE_PREFS.get(code, {})
    words = {p: tables["Common"].get(k) for p, k in affixtext.WORD_KEYS.items()}
    out = {"uniques": {}, "base_types": {}, "subtypes": {}, "implicits": {}, "affixes": {}, "lines": {}, "categories": {},
           "value_after": bool(prefs.get("value_after"))}
    out["unique_tooltips"] = {}
    for u in data["uniques"]:
        if names.get(f"Unique_Name_{u['id']}"):
            out["uniques"][u["id"]] = names[f"Unique_Name_{u['id']}"]
        lines = [names.get(f"Unique_Tooltip_{line['desc']}_{u['id']}") if "desc" in line
                 else affixtext.resolve(line.get("source"), tables, words, prefs) for line in u.get("tooltip") or []]
        rolls = [affixtext.resolve(line.get("source"), tables, words, prefs) for line in u.get("rolls") or []]
        lore = names.get(f"Unique_Lore_{u['id']}")
        if any(lines) or any(rolls) or lore:   # None: the English text stays
            out["unique_tooltips"][u["id"]] = {"lines": lines, "rolls": rolls, "lore": lore}
    out["set_bonuses"] = {}   # set id -> its bonus lines (None: the English text stays; written ones have no translation)
    for st in data.get("sets", []):
        texts = [None if "desc" in line else affixtext.resolve(line.get("source"), tables, words, prefs) for line in st["bonuses"]]
        if any(texts):
            out["set_bonuses"][st["id"]] = texts
    for b in data["bases"]:
        if names.get(f"Item_BaseType_Name_{b['id']}"):
            out["base_types"][b["id"]] = names[f"Item_BaseType_Name_{b['id']}"]
        for s in b["subtypes"]:
            text = names.get(f"Item_SubType_Name_{b['id']}_{s['id']}")
            if text:
                out["subtypes"][f"{b['id']}/{s['id']}"] = text
            texts = [affixtext.resolve(line.get("source"), tables, words, prefs) for line in s.get("implicits") or []]
            if any(texts):
                out["implicits"][f"{b['id']}/{s['id']}"] = texts   # None: the English text stays
    out["categories"] = {}   # affix picker headers / categories (English name -> this language's)
    for c in sorted({a.get(k) for a in data["affixes"] for k in ("header", "category")} - {None, ""}):
        text = affix_names.get(f"Affix_Category_{c}") or tables["Common"].get(f"Affix_Category_{c}")
        if text:
            out["categories"][c] = text
    for a in data["affixes"]:
        name = (a.get("filter_name") and affix_names.get(f"Item_Affix_{a['id']}_FilterOverride")) \
            or affix_names.get(f"Item_Affix_{a['id']}_DisplayName")
        if name:
            out["affixes"][a["id"]] = strip_value_tag(name)
        texts = [affixtext.resolve(line.get("source"), tables, words, prefs) for line in a.get("lines", [])]
        if any(texts):
            out["lines"][a["id"]] = texts   # None: no entry - the English text stays
    out["ui"] = ui_terms(ui_en or {}, tables["UI"], code)
    return out


def write_languages(locales: list[tuple[str, str, Path]], shared: Path, data: dict, out_dir: Path,
                    warnings: list[str] | None = None) -> list[dict]:
    """Write data/lang/<code>.json for each locale; returns [{code, label}] (English first). A
    locale that can't be read is left out (with a warning)."""
    from .extract import read_string_tables   # extract imports this module
    out_dir.mkdir(parents=True, exist_ok=True)
    languages = []
    en = next((bundle for code, _, bundle in locales if code == "en"), None)
    try:
        ui_en = {k: clean(v) for k, v in read_string_tables(en, shared, ("UI",))["UI"].items()} if en else {}
    except Exception as e:   # the languages still get the game's names, the editor's texts its own catalog
        ui_en = {}
        if warnings is not None:
            warnings.append(f"the game's English UI texts not read: {e}")
    for code, label, bundle in locales:
        if code == "en":
            languages.insert(0, {"code": code, "label": label})
            continue
        try:
            lang = build_language(read_string_tables(bundle, shared, TABLES), data, code, ui_en)
        except Exception as e:
            if warnings is not None:
                warnings.append(f"language {label} not extracted: {e}")
            continue
        (out_dir / f"{code}.json").write_text(json.dumps({"code": code, "label": label, **lang}, ensure_ascii=False),
                                              encoding="utf-8")
        languages.append({"code": code, "label": label})
    return languages
