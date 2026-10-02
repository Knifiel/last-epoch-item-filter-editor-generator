import pytest

from lefilter.leveling import LevelingOptions, gear_affixes, level_windows, parse_options, plan_leveling, toggle_affixes
from lefilter.sections import RuleInfo, insert_position, place
from lefilter.rules import ConfigError


def sub(sid, level, drops=True, cls=0, name=None):
    return {"id": sid, "name": name or f"base{sid}", "level": level, "drops": drops, "class": cls}


BASES = [
    {"id": 0, "type": "HELMET", "name": "Helmet", "category": "Armor", "weapon": False, "subtypes": [sub(0, 0)]},
    {"id": 1, "type": "BODY_ARMOR", "name": "Body Armor", "category": "Armor", "weapon": False, "subtypes": [sub(0, 0)]},
    {"id": 2, "type": "BELT", "name": "Belt", "category": "Armor", "weapon": False, "subtypes": [sub(0, 0)]},
    {"id": 3, "type": "BOOTS", "name": "Boots", "category": "Armor", "weapon": False, "subtypes": [sub(0, 0)]},
    {"id": 4, "type": "GLOVES", "name": "Gloves", "category": "Armor", "weapon": False, "subtypes": [sub(0, 0)]},
    {"id": 16, "type": "TWO_HANDED_SWORD", "name": "Two-Handed Sword", "category": "Two Handed Weapons", "weapon": True,
     "subtypes": [sub(0, 0), sub(1, 10), sub(2, 24), sub(3, 36, cls=2), sub(4, 46), sub(5, 56), sub(6, 61), sub(7, 52, drops=False),
                  sub(8, 5)]},
    {"id": 18, "type": "SHIELD", "name": "Shield", "category": "Off-Hand", "weapon": False, "subtypes": [sub(0, 0), sub(1, 33)]},
    {"id": 20, "type": "AMULET", "name": "Amulet", "category": "Accessories", "weapon": False,
     "subtypes": [sub(5, 0, name="Ruby Amulet"), sub(7, 58, name="Bone Amulet")]},
    {"id": 21, "type": "RING", "name": "Ring", "category": "Accessories", "weapon": False,
     "subtypes": [sub(3, 0, name="Silver Ring"), sub(4, 25, name="Gold Ring")]},
    {"id": 22, "type": "RELIC", "name": "Relic", "category": "Accessories", "weapon": False,
     "subtypes": [sub(3, 0, name="Copper Chalice"), sub(36, 70, cls=1, name="Spirit Catcher"),
                  sub(44, 58, cls=4, name="Argent Crest")]},
]


def affix(aid, name, category="Damage Type", cls=0, special=0, idol=False, rolls_on=(16, 18, 0, 20), prefix=True):
    return {"id": aid, "name": name, "category": category, "header": "", "class": cls, "special": special,
            "idol": idol, "prefix": prefix, "level": 0, "rolls_on": list(rolls_on)}


AFFIXES = [
    affix(30, "Increased Physical Damage"),
    affix(33, "Physical Penetration", rolls_on=(20,)),
    affix(63, "Added Melee Physical Damage", category="Melee", rolls_on=(16,)),
    affix(433, "Added Bow Physical Damage", category="Bow", rolls_on=(23,)),
    affix(37, "Physical Resistance", category="Resistance and Armor", rolls_on=(0, 1, 18, 21)),
    affix(12, "Increased Fire Damage"),
    affix(9, "Increased Elemental Damage"),
    affix(89, "Increased Melee Damage", category="Melee"),
    affix(88, "Added Throwing Damage", category="Throwing", cls=41, rolls_on=(2, 4, 20)),   # NonSpecific | Sentinel | Rogue
    affix(359, "Sentinel Melee Physical Damage If Wielding A Sword", category="Sentinel", cls=8, rolls_on=(0, 1)),
    affix(950, "Physical Damage Reforged", category="Set", special=3),
    affix(319, "Shared Physical Damage", category="General Idols", idol=True, rolls_on=(25,)),
    affix(25, "Added Health", category="Health", rolls_on=(0, 1, 2, 3, 4, 18, 20, 21, 22), prefix=False),
    affix(26, "Increased Minion Damage", category="Minion", rolls_on=(16, 20, 21)),
    affix(50, "All Attributes", category="Attributes", rolls_on=(12, 13, 14, 16)),
    affix(501, "Strength", category="Attributes", cls=11, rolls_on=(0, 1, 3, 4, 21, 22)),
    affix(503, "Dexterity", category="Attributes", rolls_on=(0, 1, 3, 4, 17, 21, 22)),
]
DATA = {"bases": BASES, "affixes": AFFIXES}


def names(affixes):
    return [a["name"] for a in affixes]


def test_level_windows_batch_by_requirement_and_hand_over():
    two_h = BASES[5]["subtypes"]
    windows = level_windows(two_h, step=10, cap=60)
    # bases 0 and 5 share the first batch; 61 is past the cap, 52 can't drop, 36 is class-locked
    assert [(w.min, w.max, [s["level"] for s in w.bases]) for w in windows] == [
        (0, 9, [0, 5]), (10, 19, [10]), (20, 39, [24]), (40, 49, [46]), (50, 59, [56])]
    with_mage = level_windows(two_h, step=10, cap=60, character_class="Mage")
    assert [(w.min, w.max) for w in with_mage] == [(0, 9), (10, 19), (20, 29), (30, 39), (40, 49), (50, 59)]


def test_level_windows_first_window_starts_at_zero():
    windows = level_windows([sub(0, 14), sub(1, 33)], step=10, cap=40)
    assert [(w.min, w.max) for w in windows] == [(0, 29), (30, 39)]


def test_damage_type_picks_named_affixes_but_not_defences_or_specials():
    picked = toggle_affixes(LevelingOptions(damage=["physical"]), AFFIXES)["physical"]
    assert names(picked) == ["Increased Physical Damage", "Physical Penetration", "Added Melee Physical Damage",
                             "Added Bow Physical Damage"]


def test_fire_includes_elemental():
    picked = toggle_affixes(LevelingOptions(damage=["fire"]), AFFIXES)["fire"]
    assert names(picked) == ["Increased Fire Damage", "Increased Elemental Damage"]


def test_delivery_focus_narrows_damage_type_picks():
    picked = toggle_affixes(LevelingOptions(damage=["physical"], focus=["melee"]), AFFIXES)
    assert "Added Bow Physical Damage" not in names(picked["physical"])
    assert "Added Melee Physical Damage" in names(picked["physical"])
    assert names(picked["melee"]) == ["Added Melee Physical Damage", "Increased Melee Damage"]


def test_class_specific_affixes_only_for_their_class():
    assert 359 not in {a["id"] for a in gear_affixes(AFFIXES)}
    assert 88 in {a["id"] for a in gear_affixes(AFFIXES)}            # may roll on non-class items
    sentinel = {a["id"] for a in gear_affixes(AFFIXES, "Sentinel")}
    assert {359, 88} <= sentinel
    assert 88 in {a["id"] for a in gear_affixes(AFFIXES, "Mage")}    # NonSpecific bit keeps it
    assert not {950, 319} & sentinel                                  # set / idol affixes never


def test_plan_weapon_batches_highlight_mode():
    opts = parse_options({"damage": ["physical"], "focus": ["melee"], "weapons": ["2H Sword"]}, BASES)
    plan = plan_leveling(opts, DATA)
    header, *rules = plan.rules
    assert header.is_separator and header.name == "[L] ------- LEVELING (auto) -------" and not header.spec.enabled
    assert [r.name for r in rules[:4]] == ["[L] Two-Handed Sword 0-9 build affix", "[L] Two-Handed Sword 0-9",
                                           "[L] Two-Handed Sword 10-19 build affix", "[L] Two-Handed Sword 10-19"]
    first = rules[0]
    assert first.item_types == ["TWO_HANDED_SWORD"] and first.sub_types == [0, 8] and first.char_level == (0, 9)
    assert first.affix_ids == [30, 63, 89] and first.rarity == "MAGIC RARE EXALTED"
    assert first.spec.color == 14 and first.spec.emphasized
    assert rules[1].affix_ids is None and rules[1].spec.color is None
    assert len(rules) == 10


def test_weapon_modes_and_fallback_without_affixes():
    require = plan_leveling(parse_options({"damage": ["physical"], "weapons": ["TWO_HANDED_SWORD"], "weapon_mode": "require",
                                           "header": ""}, BASES), DATA)
    assert all(r.affix_ids for r in require.rules) and len(require.rules) == 5
    bare = plan_leveling(parse_options({"weapons": ["TWO_HANDED_SWORD"], "weapon_mode": "require", "header": ""}, BASES), DATA)
    assert all(r.affix_ids is None for r in bare.rules) and len(bare.rules) == 5
    assert any("none of the selected affixes" in w for w in bare.warnings)


def test_offhands_use_defences_and_gear_rules():
    opts = parse_options({"damage": ["physical"], "defence": ["health"], "offhands": ["Shield"], "armour": True,
                          "jewelry": True, "weapon_mode": "require", "header": ""}, BASES)
    plan = plan_leveling(opts, DATA)
    shield = [r for r in plan.rules if r.item_types == ["SHIELD"]]
    assert [r.char_level for r in shield] == [(0, 29), (30, 59)]
    assert 25 in shield[0].affix_ids                          # health counts on off-hands
    armour = [r for r in plan.rules if r.name.startswith("[L] Armour")]
    assert [(r.affix_min, r.char_level) for r in armour] == [(2, (0, 59)), (1, (0, 29))]
    assert armour[0].item_types == ["HELMET", "BODY_ARMOR", "BOOTS", "GLOVES"]   # belts go with jewelry
    jewelry = [r for r in plan.rules if r.name.startswith("[L] Jewelry")]
    assert set(jewelry[0].affix_ids) == {30, 33, 25}


def test_jewelry_and_belts_good_bases_highlighted_until_cap():
    opts = parse_options({"defence": ["health"], "jewelry": True, "header": ""}, BASES)
    rules = plan_leveling(opts, DATA).rules
    assert [r.name for r in rules] == ["[L] Amulet good bases build affix 0-59", "[L] Ring good bases build affix 0-59",
                                       "[L] Relic good bases build affix 0-59", "[L] Jewelry & belts build affix 0-59"]
    amulet, ring, relic, rest = rules
    assert amulet.item_types == ["AMULET"] and amulet.sub_types == [7] and ring.sub_types == [4]
    assert relic.sub_types == [36, 44]                       # no class: every class's good relic
    assert all(r.affix_min == 1 and r.char_level == (0, 59) and r.affix_ids == [25] for r in rules)
    assert amulet.spec.emphasized and not rest.spec.emphasized and rest.spec.color == 13
    assert rest.item_types == ["BELT", "AMULET", "RING", "RELIC"] and rest.sub_types == []
    # the belt has no good base in BASES; a class keeps only its own relics
    sentinel = plan_leveling(parse_options({"defence": ["health"], "jewelry": True, "header": "",
                                            "character_class": "Sentinel"}, BASES), DATA).rules
    assert [r.sub_types for r in sentinel if r.item_types == ["RELIC"]] == [[44]]


def test_good_bases_config():
    opts = parse_options({"good_bases": {"Ring": ["silver ring", "Gold Ring"], "AMULET": []}}, BASES)
    assert opts.good_bases["RING"] == ["Silver Ring", "Gold Ring"] and opts.good_bases["AMULET"] == []
    assert opts.good_bases["BELT"] == ["Spidersilk Sash"]     # left out: default
    laser = plan_leveling(parse_options({"defence": ["health"], "jewelry": True, "good_bases": {"RING": ["Laser Ring"]}},
                                        BASES), DATA)
    assert "good_bases: Ring has no bases named Laser Ring" in laser.warnings
    assert not any(r.item_types == ["RING"] for r in laser.rules)
    with pytest.raises(ConfigError, match="isn't a weapon"):
        parse_options({"good_bases": {"IDOL_2x1": []}}, BASES)
    with pytest.raises(ConfigError, match="good_bases must be"):
        parse_options({"good_bases": {"RING": "Gold Ring"}}, BASES)


def test_good_bases_for_any_slot_stay_on_until_cap_above_the_windows():
    opts = parse_options({"damage": ["physical"], "defence": ["health"], "weapons": ["2H Sword"], "armour": True,
                          "good_bases": {"2H Sword": ["base2", "base3"], "HELMET": ["base0"]}, "header": ""}, BASES)
    rules = plan_leveling(opts, DATA).rules
    sword, helmet = rules[:2]
    assert sword.name == "[L] Two-Handed Sword good bases build affix 0-59"
    assert sword.sub_types == [2, 3] and sword.char_level == (0, 59) and sword.affix_ids == [30, 63]
    assert sword.spec.color == 15 and sword.spec.emphasized
    assert helmet.item_types == ["HELMET"] and helmet.affix_ids == [25, 30] and helmet.char_level == (0, 59)
    assert rules[2].name == "[L] Two-Handed Sword 0-9 build affix"
    mage = plan_leveling(parse_options({"weapons": ["2H Sword"], "weapon_mode": "bases", "character_class": "Sentinel",
                                        "good_bases": {"TWO_HANDED_SWORD": ["base2", "base3"]}, "header": ""}, BASES), DATA)
    assert mage.rules[0].name == "[L] Two-Handed Sword good bases 0-59"
    assert mage.rules[0].sub_types == [2] and mage.rules[0].affix_ids is None   # base3 is a Mage base
    assert not any(r.item_types == ["RING"] for r in mage.rules)   # only the slots in use
    # no build affix rolls on a helmet: no good-base rule rather than one showing every helmet
    minion = plan_leveling(parse_options({"focus": ["minion"], "armour": True, "good_bases": {"HELMET": ["base0"]},
                                          "header": ""}, BASES), DATA)
    assert minion.rules == [] and "Helmet good bases: none of the build's affixes roll on it; no rule generated" in minion.warnings


def test_attributes_count_like_damage_and_add_all_attributes():
    opts = LevelingOptions(attributes=["strength"])
    assert names(toggle_affixes(opts, AFFIXES)["strength"]) == ["All Attributes", "Strength"]
    plan = plan_leveling(parse_options({"attributes": ["strength"], "weapons": ["2H Sword"], "weapon_mode": "require",
                                        "header": ""}, BASES), DATA)
    assert all(r.affix_ids == [50] for r in plan.rules)     # weapons use attributes, not defences


def test_old_attributes_defence_toggle_becomes_every_attribute():
    opts = parse_options({"defence": ["health", "attributes"]}, BASES)
    assert opts.defence == ["health"]
    assert opts.attributes == ["strength", "dexterity", "intelligence", "attunement", "vitality"]


def test_parse_options_errors():
    with pytest.raises(ConfigError, match="unknown item type"):
        parse_options({"weapons": ["Laser Sword"]}, BASES)
    with pytest.raises(ConfigError, match="focus"):
        parse_options({"focus": ["sneaky"]}, BASES)
    with pytest.raises(ConfigError, match="unknown key"):
        parse_options({"weapon": []}, BASES)
    with pytest.raises(ConfigError, match="style"):
        parse_options({"style": {"weapon": {}}}, BASES)


def info(name, sep=False, catch=False):
    return RuleInfo(name=name, separator=sep, catch_all=catch)


def test_insert_position():
    rules = [info("a"), info("---- LEVELING ----", sep=True), info("lvl rule"), info("", sep=True, catch=True)]
    assert insert_position(rules, "[L] ") == ([], 2)
    assert insert_position([info("a"), info("", sep=True, catch=True)], "[L] ") == ([], 1)
    assert insert_position([info("a")], "[L] ") == ([], 1)
    old = [info("a"), info("[L] x"), info("b"), info("[L] y")]
    assert insert_position(old, "[L] ") == ([1, 3], 1)


def test_place_replaces_previous_section_in_place():
    items = ["a", "[L] old1", "b", "[L] old2", "c"]
    infos = [info(n) for n in items]
    out, removed, at = place(items, infos, ["[L] new"], "[L] ")
    assert out == ["a", "[L] new", "b", "c"] and removed == 2 and at == 1
