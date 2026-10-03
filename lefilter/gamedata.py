"""Loot-filter enums and lookups, as defined in the game code (LE.dll, lootFilterVersion 9).

Values come from the IL2CPP metadata (Cpp2IL); the XML stores enums by name, flag
enums as space-separated names ("UNIQUE SET").
"""
from __future__ import annotations

import re

# EquipmentType: the base type id (MasterItemsList baseTypeID) is the enum value.
EQUIPMENT_TYPES = {
    0: "HELMET", 1: "BODY_ARMOR", 2: "BELT", 3: "BOOTS", 4: "GLOVES",
    5: "ONE_HANDED_AXE", 6: "ONE_HANDED_DAGGER", 7: "ONE_HANDED_MACES", 8: "ONE_HANDED_SCEPTRE",
    9: "ONE_HANDED_SWORD", 10: "WAND", 11: "ONE_HANDED_FIST", 12: "TWO_HANDED_AXE", 13: "TWO_HANDED_MACE",
    14: "TWO_HANDED_SPEAR", 15: "TWO_HANDED_STAFF", 16: "TWO_HANDED_SWORD", 17: "QUIVER", 18: "SHIELD",
    19: "CATALYST", 20: "AMULET", 21: "RING", 22: "RELIC", 23: "BOW", 24: "CROSSBOW",
    25: "IDOL_1x1_ETERRA", 26: "IDOL_1x1_LAGON", 27: "IDOL_2x1", 28: "IDOL_1x2", 29: "IDOL_3x1",
    30: "IDOL_1x3", 31: "IDOL_4x1", 32: "IDOL_1x4", 33: "IDOL_2x2", 34: "BLESSING", 35: "GREATER_LENS",
    36: "ARCTUS_LENS", 37: "MESEMBRIA_LENS", 38: "EOS_LENS", 39: "DYSIS_LENS", 40: "UNUSED", 41: "IDOL_ALTAR",
}
TYPE_IDS = {name: tid for tid, name in EQUIPMENT_TYPES.items()}

WEAPON_TYPES = ("ONE_HANDED_AXE", "ONE_HANDED_DAGGER", "ONE_HANDED_MACES", "ONE_HANDED_SCEPTRE", "ONE_HANDED_SWORD",
                "WAND", "TWO_HANDED_AXE", "TWO_HANDED_MACE", "TWO_HANDED_SPEAR", "TWO_HANDED_STAFF",
                "TWO_HANDED_SWORD", "BOW")
OFFHAND_TYPES = ("SHIELD", "QUIVER", "CATALYST")
ARMOUR_TYPES = ("HELMET", "BODY_ARMOR", "BELT", "BOOTS", "GLOVES")
JEWELRY_TYPES = ("AMULET", "RING", "RELIC")
# Idols: the all-class ones (1x1, 2x1, 1x2) and the class-specific ones (one base per class).
COMMON_IDOL_TYPES = ("IDOL_1x1_ETERRA", "IDOL_1x1_LAGON", "IDOL_2x1", "IDOL_1x2")
CLASS_IDOL_TYPES = ("IDOL_3x1", "IDOL_1x3", "IDOL_4x1", "IDOL_1x4", "IDOL_2x2")
# ItemList.IsWeaverIdol: the Weaver version of each all-class idol (larger pool: + Weaver Idol affixes).
WEAVER_IDOL_SUBTYPES = {"IDOL_1x1_ETERRA": 2, "IDOL_1x1_LAGON": 1, "IDOL_2x1": 1, "IDOL_1x2": 1}
# ItemData.IsOmenIdolAffix: Omen idols also roll the affixes of these (larger) idol types.
OMEN_EXTRA_TYPES = ("IDOL_4x1", "IDOL_1x4", "IDOL_2x2")

# Flag enums, in declaration order (the order the game's XmlSerializer writes them).
RARITIES = ("NORMAL", "MAGIC", "RARE", "UNIQUE", "SET", "LEGENDARY", "EXALTED")      # RarityCondition.Rarity
CLASSES = ("Primalist", "Mage", "Sentinel", "Acolyte", "Rogue")                     # ItemList.ClassRequirement
CLASS_BITS = {c: 1 << i for i, c in enumerate(CLASSES)}
# Filter icons (LootFilterSettingsPanelUI.icons in PermaLoad.bundle): 0 none, then the class icons.
CLASS_FILTER_ICONS = {"Acolyte": 1, "Mage": 2, "Primalist": 3, "Rogue": 4, "Sentinel": 5}
# Affixes use AffixList.ClassSpecificity instead: the same classes one bit up, plus NonSpecific
# (may roll on items that aren't class-specific). 0 = no restriction.
AFFIX_NONSPECIFIC = 1
AFFIX_CLASS_BITS = {c: bit << 1 for c, bit in CLASS_BITS.items()}
FACTIONS = ("CircleOfFortune", "MerchantsGuild", "ForgottenKnights", "TheWeaver")   # FactionID
# The faction condition's dropdown only offers the two trade factions (FactionCondition.GetFactionDropdownOptions).
FILTER_FACTIONS = ("CircleOfFortune", "MerchantsGuild")
FACTION_LABELS = {"CircleOfFortune": "Circle of Fortune", "MerchantsGuild": "Merchant's Guild",
                  "ForgottenKnights": "Forgotten Knights", "TheWeaver": "The Weaver"}
CORRUPTION = ("Any", "OnlyCorrupted", "OnlyUncorrupted")
COMPARSION = ("ANY", "EQUAL", "LESS", "LESS_OR_EQUAL", "MORE", "MORE_OR_EQUAL")    # sic, the game's spelling
BEAM_SIZES = ("NONE", "LARGEST", "VERYLARGE", "LARGE", "MEDIUM", "SMALL", "VERYSMALL", "SMALLEST")
SEALED_TYPES = ("Any", "NotSealed", "Sealed", "SealedPrefix", "SealedSuffix")       # AffixCountCondition
LEVEL_CONDITION_TYPES = ("BELOW_LEVEL", "ABOVE_LEVEL", "MAX_LVL_BELOW_CHARACTER_LEVEL", "HIGHEST_USABLE_LEVEL")

NON_EQUIPMENT_FLAGS = (
    "CommonShards", "CommonRunes", "CommonGlyphs", "RareShards", "RareRunes", "RareGlyphs",
    *(f"WovenEchoesRank{i}" for i in range(1, 11)), "WovenEchoesUnpurchasable", "GoldResonance",
    "ObsidianResonance", "ArenaKeys", "DungeonKeys", "DungeonCharms", "LizardTails", "HarbingerEye",
    "PrimordialMaterials", "TemporalKeystone", "MerchantToken", "ArenaKeysOfMemory", "CrystallizedHeart",
    "AllKeys", "AllWovenEchoes", "AllResonances", "AllShards", "AllRunes", "AllGlyphs", "AllCommon", "AllRare",
    "AllCrafting", "All",
)
GLYPH_FLAGS = ("GlyphOfHope", "GlyphOfStability", "GlyphOfOrder", "GlyphOfDespair", "GlyphOfEnvy", "AllGlyphs")
RUNE_FLAGS = ("RuneOfShattering", "RuneOfRefinement", "RuneOfRemoval", "RuneOfDiscovery", "RuneOfShaping",
              "RuneOfAscendance", "RuneOfCreation", "RuneOfWeaving", "RuneOfHavoc", "RuneOfRedemption",
              "RuneOfEvolution", "RuneOfCorruption", "AllRunes")

# Conditions on non-equipment items: condition type -> (flags element, known flag names).
FLAG_CONDITIONS = {
    "KeysCondition": ("NonEquippableItemFilterFlags", NON_EQUIPMENT_FLAGS),
    "CraftingMaterialsCondition": ("NonEquippableItemFilterFlags", NON_EQUIPMENT_FLAGS),
    "ResonancesCondition": ("NonEquippableItemFilterFlags", NON_EQUIPMENT_FLAGS),
    "WovenEchoesCondition": ("NonEquippableItemFilterFlags", NON_EQUIPMENT_FLAGS),
    "GlyphCondition": ("GlyphFilterFlags", GLYPH_FLAGS),
    "RuneCondition": ("RuneFilterFlags", RUNE_FLAGS),
}

# Affix specialAffixType values (MasterAffixesList).
AFFIX_SPECIAL = {0: "", 1: "experimental", 2: "personal", 3: "set", 4: "enchanted idol", 5: "weaver idol",
                 6: "corrupted", 7: "variant"}

# EpochColor.ColorID entries used as the default label colour of each rarity.
RARITY_COLOR_IDS = {"NORMAL": 0, "MAGIC": 1, "RARE": 2, "UNIQUE": 3, "SET": 4, "LEGENDARY": 5, "EXALTED": 11}


def flags_to_xml(names: list[str], order: tuple[str, ...], none: str = "None", everything: str | None = None) -> str:
    """Selected flag names -> the XML text the game writes (declaration order, space-separated)."""
    chosen = [n for n in order if n in set(names)]
    if not chosen:
        return none
    if everything and len(chosen) == len([n for n in order if n != everything]):
        return everything
    return " ".join(chosen)


def class_names(bits: int) -> list[str]:
    return [c for c in CLASSES if bits & CLASS_BITS[c]]


# --- filter file version ---------------------------------------------------------------------------------
# What the game's upgrade of an older filter works on (ItemFilterManager.UpdateFilter renames old tags,
# ItemFilter.Sanitize turns levelDependent into a level condition and BeamId into the beam fields).
OLD_FILTER_LAYOUT = re.compile(r"TWO_HANDED_POLEARM|<type>HIGHLIGHT</type>|<(?:levelDependent|minLvl|maxLvl)>"
                               r"|<levelDependent_deprecated>true<|<BeamId>")


def check_filter_version(version: int | None, text: str, current: int, where: str = "") -> None:
    """Refuses a filter this tool can't read as lootFilterVersion `current`. The game writes 0 into the filters it
    creates (it upgrades them when it next loads one, which would clear their map icons and beam overrides), so
    0 in the current layout counts as current - saving writes `current`, so the game leaves it as it is."""
    if version == current or (version == 0 and not OLD_FILTER_LAYOUT.search(text)):
        return
    raise ValueError(f"{where}lootFilterVersion {version}, expected {current} - open and save it in the current game version first")
