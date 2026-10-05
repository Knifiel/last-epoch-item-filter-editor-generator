import pytest

from lefilter.filterdoc import parse_rule_blocks
from lefilter.filterxml import render_rule
from lefilter.leveling import gear_affixes, level_windows, parse_options, plan_leveling, tier_bands, toggle_affixes
from lefilter.matcher import Context, evaluate
from lefilter.sections import RuleInfo, doc_infos, insert_position, place, place_leveling, reorder_generated
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


def affix(aid, name, category="Damage Type", cls=0, special=0, idol=False, rolls_on=(16, 18, 0, 20), prefix=True,
          header=""):
    return {"id": aid, "name": name, "category": category, "header": header, "class": cls, "special": special,
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
    affix(68, "Health On Kill", category="Health Recovery", rolls_on=(16,), header="Defensive"),
    affix(69, "Melee Health Leech", category="Leech", rolls_on=(16, 0), header="Defensive"),
    affix(42, "Lightning Damage And Leech", category="Leech", rolls_on=(16,), header="Defensive"),
    affix(718, "Mana and Mana Regen", category="Mana", rolls_on=(16, 20), header="Other"),
    affix(563, "Level of Rive", category="Sentinel", cls=8, rolls_on=(1,)),
    affix(603, "Level of Smite", category="Sentinel", cls=8, rolls_on=(22,)),
    affix(380, "Increased Smelters Wrath Damage", category="Sentinel", cls=8, rolls_on=(0, 1)),
    affix(610, "Level of Fireball", category="Mage", cls=4, rolls_on=(0,)),
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
    picked = toggle_affixes({"damage": ["physical"]}, AFFIXES)["physical"]
    assert names(picked) == ["Increased Physical Damage", "Physical Penetration", "Added Melee Physical Damage",
                             "Added Bow Physical Damage"]


def test_fire_includes_elemental():
    picked = toggle_affixes({"damage": ["fire"]}, AFFIXES)["fire"]
    assert names(picked) == ["Increased Fire Damage", "Increased Elemental Damage"]


def test_delivery_focus_narrows_damage_type_picks():
    picked = toggle_affixes({"damage": ["physical"], "focus": ["melee"]}, AFFIXES)
    assert "Added Bow Physical Damage" not in names(picked["physical"])
    assert "Added Melee Physical Damage" in names(picked["physical"])
    assert names(picked["melee"]) == ["Added Melee Physical Damage", "Increased Melee Damage", "Melee Health Leech"]


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
    assert first.affix_tier is None                          # T1: any tier
    # the 20-39 window: its affix rule splits where the tier changes, its base rule doesn't
    assert [(r.name, r.char_level, r.affix_tier) for r in rules[4:7]] == [
        ("[L] Two-Handed Sword 20-29 build affix T2+", (20, 29), 2), ("[L] Two-Handed Sword 30-39 build affix T3+", (30, 39), 3),
        ("[L] Two-Handed Sword 20-39", (20, 39), None)]
    assert [r.affix_tier for r in rules[7:]] == [4, None, 4, None]
    assert len(rules) == 11


def test_weapon_modes_and_fallback_without_affixes():
    require = plan_leveling(parse_options({"damage": ["physical"], "weapons": ["TWO_HANDED_SWORD"], "weapon_mode": "require",
                                           "header": ""}, BASES), DATA)
    assert all(r.affix_ids for r in require.rules) and len(require.rules) == 6   # 20-39 split by tier
    bare = plan_leveling(parse_options({"weapons": ["TWO_HANDED_SWORD"], "weapon_mode": "require", "header": ""}, BASES), DATA)
    assert all(r.affix_ids is None for r in bare.rules) and len(bare.rules) == 5
    assert any("none of the selected affixes" in w for w in bare.warnings)


def test_offhands_use_defences_and_gear_rules():
    opts = parse_options({"damage": ["physical"], "defence": ["health"], "offhands": ["Shield"], "armour": True,
                          "jewelry": True, "weapon_mode": "require", "header": "", "tier_step": 0}, BASES)
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
    opts = parse_options({"defence": ["health"], "jewelry": True, "header": "", "tier_step": 0}, BASES)
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
    sentinel = plan_leveling(parse_options({"defence": ["health"], "jewelry": True, "header": "", "tier_step": 0,
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
                          "good_bases": {"2H Sword": ["base2", "base3"], "HELMET": ["base0"]}, "header": "",
                          "tier_step": 0}, BASES)
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


def test_attributes_count_where_they_roll_and_all_attributes_is_its_own_toggle():
    picked = toggle_affixes({"attributes": ["strength", "all_attributes"]}, AFFIXES)
    assert names(picked["strength"]) == ["Strength"] and names(picked["all_attributes"]) == ["All Attributes"]
    # shared toggles (v0.2.0): a single attribute stands for All Attributes on weapons
    plan = plan_leveling(parse_options({"attributes": ["strength"], "weapons": ["2H Sword"], "offhands": ["Shield"],
                                        "armour": True, "jewelry": True, "weapon_mode": "require", "header": ""},
                                       BASES), DATA)
    by_type = {r.item_types[0]: r for r in plan.rules}
    assert plan.picked["weapons"] == {"all_attributes": [AFFIXES[14]]}
    assert by_type["TWO_HANDED_SWORD"].affix_ids == [50]     # All Attributes: Strength doesn't roll on weapons
    assert by_type["SHIELD"].affix_ids is None               # neither rolls on shields: bases only
    assert by_type["HELMET"].affix_ids == [501] and by_type["BELT"].affix_ids == [501]   # rings and relics
    assert names(plan.rule_affixes["[L] Jewelry & belts build affix 0-19"]) == ["Strength"]


def test_each_kind_of_gear_has_its_own_toggles():
    opts = parse_options({"weapons": ["2H Sword"], "offhands": ["Shield"], "armour": True, "jewelry": True,
                          "weapon_mode": "require", "header": "", "good_bases": {"AMULET": [], "RING": [], "RELIC": []},
                          "weapon_affixes": {"damage": ["physical"]}, "offhand_affixes": {"defence": ["health"]},
                          "armour_affixes": {"attributes": ["strength"]},
                          "jewelry_affixes": {"damage": ["fire"], "defence": ["health"]}}, BASES)
    plan = plan_leveling(opts, DATA)
    by_type = {r.item_types[0]: r for r in plan.rules}
    assert by_type["TWO_HANDED_SWORD"].affix_ids == [30, 63] and by_type["SHIELD"].affix_ids == [25]
    assert by_type["HELMET"].affix_ids == [501] and by_type["BELT"].affix_ids == [9, 12, 25]
    assert {s: list(t) for s, t in plan.picked.items()} == {"weapons": ["physical"], "offhands": ["health"],
                                                             "armour": ["strength"], "jewelry": ["fire", "health"]}
    assert names(plan.picked["jewelry"]["fire"]) == ["Increased Fire Damage", "Increased Elemental Damage"]


def test_shared_toggles_of_older_configs_start_every_section():
    opts = parse_options({"damage": ["physical"], "defence": ["health", "attributes"]}, BASES)
    every = ["strength", "dexterity", "intelligence", "attunement", "vitality"]
    assert opts.weapon_affixes == {"damage": ["physical"], "focus": [], "attributes": ["all_attributes"], "defence": [],
                                   "defensive": False, "exclude": []}
    assert opts.armour_affixes == opts.jewelry_affixes == opts.offhand_affixes == {
        "damage": ["physical"], "focus": [], "attributes": every, "defence": ["health"], "exclude": []}
    # v0.2.0's armour toggle also took endurance: those configs keep it
    assert parse_options({"defence": ["armour"]}, BASES).armour_affixes["defence"] == ["armour", "endurance"]
    assert parse_options({"armour_affixes": {"defence": ["armour"]}}, BASES).armour_affixes["defence"] == ["armour"]
    mixed = parse_options({"damage": ["fire"], "armour_affixes": {"defence": ["health"]}}, BASES)
    assert mixed.armour_affixes["damage"] == [] and mixed.jewelry_affixes["damage"] == ["fire"]
    with pytest.raises(ConfigError, match="armour_affixes defence: unknown"):
        parse_options({"armour_affixes": {"defence": ["laser"]}}, BASES)
    with pytest.raises(ConfigError, match="armour_affixes"):
        parse_options({"armour_affixes": {"defensive": True}}, BASES)   # only weapons have it


def test_weapons_leave_out_defensive_affixes_unless_asked():
    toggles = {"damage": ["lightning"], "focus": ["melee"], "defence": ["sustain", "mana"]}
    base = {"weapons": ["2H Sword"], "weapon_mode": "require", "header": ""}
    shared = plan_leveling(parse_options({**base, **toggles}, BASES), DATA)
    assert 69 not in shared.rules[0].affix_ids              # Melee Health Leech: the melee toggle, but Defensive
    off = plan_leveling(parse_options({**base, "weapon_affixes": toggles}, BASES), DATA)
    assert set(off.rules[0].affix_ids) == {9, 42, 63, 89}   # Lightning Damage And Leech stays: it's a damage pick
    assert names(off.picked["weapons"]["sustain"]) == ["Lightning Damage And Leech"]
    assert off.warnings == ["Weapons: Mana: only defensive affixes here, which weapons leave out "
                            "(tick Include defensive affixes - weapon_affixes.defensive - to count them)"]
    on = plan_leveling(parse_options({**base, "weapon_affixes": {**toggles, "defensive": True}}, BASES), DATA)
    assert {68, 69, 42, 718} <= set(on.rules[0].affix_ids) and not on.warnings
    armour = plan_leveling(parse_options({"armour": True, "header": "", "armour_affixes": toggles}, BASES), DATA)
    assert 69 in armour.rules[0].affix_ids                  # other gear keeps them
    idle = plan_leveling(parse_options({"attributes": ["vitality"], "defence": ["health"], "offhands": ["Shield"],
                                        "header": ""}, BASES), DATA)
    assert idle.warnings == []                               # nothing of Vitality rolls on off-hands: not offered there


def test_class_affixes_count_on_their_slots_for_their_class():
    table = {"defence": ["health"], "armour": True, "jewelry": True, "header": "", "character_class": "Sentinel",
             "class_affixes": [563, "level of smite", "Level of Fireball", 380]}
    plan = plan_leveling(parse_options(table, BASES), DATA)
    assert names(plan.class_affixes) == ["Level of Rive", "Level of Smite", "Increased Smelters Wrath Damage"]
    assert "class_affixes: not Sentinel affixes, left out: Level of Fireball" in plan.warnings
    armour = plan.rule_affixes["[L] Armour 2+ build affixes 0-19"]
    assert {563, 380} <= {a["id"] for a in armour} and 603 not in {a["id"] for a in armour}
    relic = plan.rule_affixes["[L] Relic good bases build affix 0-19"]
    assert {a["id"] for a in relic} == {25, 603}
    assert 563 not in {a["id"] for a in plan.rule_affixes["[L] Jewelry & belts build affix 0-19"]}
    no_class = plan_leveling(parse_options({**table, "character_class": ""}, BASES), DATA)
    assert no_class.class_affixes == [] and "class_affixes: no class chosen; class affixes left out" in no_class.warnings
    no_armour = plan_leveling(parse_options({**table, "armour": False}, BASES), DATA)
    assert "Level of Rive: rolls only on Body Armor, none of which is picked" in no_armour.warnings
    with pytest.raises(ConfigError, match="class_affixes"):
        parse_options({"class_affixes": "Level of Rive"}, BASES)


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


def test_endurance_is_its_own_toggle():
    affixes = [affix(70, "Increased Armor", category="Resistance and Armor", rolls_on=(0,)),
               affix(71, "Endurance", category="Resistance and Armor", rolls_on=(0,)),
               affix(72, "Endurance Threshold", category="Resistance and Armor", rolls_on=(0,)),
               affix(73, "Minion Endurance", category="Minion", rolls_on=(0,))]
    picked = toggle_affixes({"defence": ["armour", "endurance"]}, affixes)
    assert names(picked["armour"]) == ["Increased Armor"]
    assert names(picked["endurance"]) == ["Endurance", "Endurance Threshold"]


def test_sections_can_exclude_single_affixes():
    table = {"armour": True, "jewelry": True, "header": "",
             "armour_affixes": {"defence": ["health"], "attributes": ["strength"], "exclude": [501]},
             "jewelry_affixes": {"defence": ["health"], "attributes": ["strength"], "exclude": ["strength"]}}
    plan = plan_leveling(parse_options(table, BASES), DATA)
    assert names(plan.picked["armour"]["strength"]) == [] and names(plan.candidates["armour"]["strength"]) == ["Strength"]
    assert plan.excluded["armour"] == {501} and plan.excluded["jewelry"] == {501}   # by id, or by name
    assert [a["id"] for a in plan.rule_affixes["[L] Armour 2+ build affixes 0-19"]] == [25]
    assert not [w for w in plan.warnings if "Strength" in w]          # an excluded toggle isn't "missing"
    assert names(plan.picked["jewelry"]["health"]) == ["Added Health"]
    with pytest.raises(ConfigError, match="exclude must be a list"):
        parse_options({"armour_affixes": {"exclude": "Strength"}}, BASES)


def test_no_recolour_can_be_written_as_minus_one():
    opts = parse_options({"style": {"weapon_affix": {"color": -1, "emphasized": True}, "gear": {"color": None}}}, BASES)
    assert opts.spec("weapon_affix").color is None and opts.spec("weapon_affix").emphasized
    assert opts.spec("gear").color is None and opts.spec("jewelry").color == 13


def test_a_class_affix_excluded_in_one_section_stays_out_of_it_only():
    table = {"armour": True, "jewelry": True, "header": "", "character_class": "Sentinel",
             "class_affixes": [563, 380, 603], "armour_affixes": {"defence": ["health"], "exclude": ["level of rive"]},
             "jewelry_affixes": {"defence": ["health"]}}
    plan = plan_leveling(parse_options(table, BASES), DATA)
    assert plan.excluded["armour"] == {563}
    armour = [a["id"] for a in plan.rule_affixes["[L] Armour 2+ build affixes 0-19"]]
    assert 563 not in armour and 380 in armour                       # the other class pick stays
    assert 603 in [a["id"] for a in plan.rule_affixes["[L] Jewelry & belts build affix 0-19"]]


def test_toggles_match_the_affixes_own_name_and_excludes_take_either_name():
    # the game may name an affix unlike its own name; the toggles look at the latter
    renamed = [{**a, "name": "Burning", "internal_name": "Increased Fire Damage"} if a["name"] == "Increased Fire Damage"
               else {**a, "name": "Life Steal", "internal_name": "Melee Health Leech"} if a["name"] == "Melee Health Leech" else a
               for a in AFFIXES]
    before = toggle_affixes({"damage": ["fire"], "focus": ["melee"]}, AFFIXES)
    after = toggle_affixes({"damage": ["fire"], "focus": ["melee"]}, renamed)
    assert {k: [a["id"] for a in v] for k, v in after.items()} == {k: [a["id"] for a in v] for k, v in before.items()}
    data = {**DATA, "affixes": [{**a, "name": "Str", "internal_name": "Strength"} if a["id"] == 501 else a for a in DATA["affixes"]]}
    for name in ("Strength", "Str"):
        table = {"armour": True, "header": "", "armour_affixes": {"attributes": ["strength"], "exclude": [name]}}
        plan = plan_leveling(parse_options(table, BASES), data)
        assert plan.excluded["armour"] == {501} and not [w for w in plan.warnings if "exclude" in w]


def test_build_affixes_need_a_higher_tier_as_the_character_levels():
    opts = parse_options({}, BASES)
    assert tier_bands(0, 59, opts) == [(0, 19, 1), (20, 29, 2), (30, 39, 3), (40, 59, 4)]
    assert tier_bands(25, 34, opts) == [(25, 29, 2), (30, 34, 3)]
    assert tier_bands(0, 59, parse_options({"tier_step": 0}, BASES)) == [(0, 59, 1)]
    assert tier_bands(0, 59, parse_options({"tier_step": 15, "max_tier": 2}, BASES)) == [(0, 29, 1), (30, 59, 2)]
    plan = plan_leveling(parse_options({"defence": ["health"], "armour": True, "jewelry": True, "header": "",
                                        "good_bases": {"AMULET": [], "RING": [], "RELIC": []}}, BASES), DATA)
    assert [(r.name, r.affix_tier, r.affix_min) for r in plan.rules] == [
        ("[L] Armour 2+ build affixes 0-19", None, 2), ("[L] Armour 2+ build affixes T2+ 20-29", 2, 2),
        ("[L] Armour 2+ build affixes T3+ 30-39", 3, 2), ("[L] Armour 2+ build affixes T4+ 40-59", 4, 2),
        ("[L] Armour 1 build affix 0-19", None, 1), ("[L] Armour 1 build affix T2+ 20-29", 2, 1),
        ("[L] Jewelry & belts build affix 0-19", None, 1), ("[L] Jewelry & belts build affix T2+ 20-29", 2, 1),
        ("[L] Jewelry & belts build affix T3+ 30-39", 3, 1), ("[L] Jewelry & belts build affix T4+ 40-59", 4, 1)]
    xml = render_rule(plan.rules[3])
    assert "<comparsion>MORE_OR_EQUAL</comparsion>" in xml and "<comparsionValue>4</comparsionValue>" in xml
    for bad in ({"tier_step": -1}, {"max_tier": 0}, {"max_tier": 8}):
        with pytest.raises(ConfigError, match="tier_step"):
            parse_options(bad, BASES)


def test_endgame_rares_per_slot_in_their_own_section():
    opts = parse_options({"damage": ["physical"], "defence": ["health"], "weapons": ["2H Sword"], "weapon_mode": "bases",
                          "armour": True, "endgame_bases": {"2H Sword": ["base4", "base6"], "Helmet": ["Laser Hat"]}}, BASES)
    plan = plan_leveling(opts, DATA)
    header, *rules = plan.endgame
    assert header.is_separator and header.name == "[E] ------ ENDGAME RARES - disable when not needed ------"
    assert not header.spec.enabled and not any(r.name.startswith("[E]") for r in plan.rules)
    assert [r.name for r in rules] == ["[E] Two-Handed Sword endgame rare", "[E] Helmet endgame rare", "[E] Body Armor endgame rare",
                                       "[E] Boots endgame rare", "[E] Gloves endgame rare"]
    sword, helmet, *_ = rules
    assert sword.sub_types == [4, 6] and helmet.sub_types == []          # no endgame base picked: any base
    assert sword.affix_ids == [30, 63] and helmet.affix_ids == [25, 30]  # in `bases` mode too: the build's affixes
    assert all(r.rarity == "RARE EXALTED" and r.char_level is None and r.spec.enabled and r.spec.color == 12
               and (r.affix_min, r.affix_tier, r.affix_total) == (2, 5, None) for r in rules)
    assert "endgame_bases: Helmet has no bases named Laser Hat" in plan.warnings
    no_armour_affix = plan_leveling(parse_options({"focus": ["minion"], "armour": True}, BASES), DATA)
    assert no_armour_affix.endgame == [] and not [w for w in no_armour_affix.warnings if "endgame" in w]   # said already
    # a class keeps only its own bases; none of its own picked: any base
    sentinel = plan_leveling(parse_options({"damage": ["physical"], "weapons": ["2H Sword"], "character_class": "Sentinel",
                                            "endgame_bases": {"TWO_HANDED_SWORD": ["base3"]}}, BASES), DATA)
    assert sentinel.endgame[1].sub_types == []
    mage = plan_leveling(parse_options({"damage": ["physical"], "weapons": ["2H Sword"], "character_class": "Mage",
                                        "endgame_bases": {"TWO_HANDED_SWORD": ["base3"]}}, BASES), DATA)
    assert mage.endgame[1].sub_types == [3]
    # a slot nothing of the build rolls on gets none, and a warning
    shield = plan_leveling(parse_options({"focus": ["minion"], "offhands": ["Shield"]}, BASES), DATA)
    assert shield.endgame == [] and "Shield endgame rares: none of the build's affixes roll on it; no rule generated" in shield.warnings
    with pytest.raises(ConfigError, match="endgame_prefix"):
        parse_options({"endgame_prefix": "[L] "}, BASES)
    with pytest.raises(ConfigError, match="endgame_bases must be"):
        parse_options({"endgame_bases": {"RING": "Gold Ring"}}, BASES)


def test_endgame_rare_needs_two_t5_build_affixes():
    plan = plan_leveling(parse_options({"defence": ["health"], "damage": ["physical"], "attributes": ["strength"],
                                        "armour": True}, BASES), DATA)
    rules = parse_rule_blocks([render_rule(r) for r in plan.endgame])
    helmet = next(r for r in rules if r["name"] == "[E] Helmet endgame rare")
    assert [(c["comparsion"], c["comparsion_value"], c["min_on_same_item"], c["combined_comparsion"], c["combined_value"])
            for c in helmet["conditions"] if c["type"] == "AffixCondition"] == [("MORE_OR_EQUAL", 5, 2, "ANY", 1)]
    ctx = Context({**DATA, "uniques": []})

    def shown(*affixes, rarity="RARE"):   # build affixes: Added Health 25, Increased Physical Damage 30, Strength 501
        item = {"type": "HELMET", "subtype": 0, "rarity": rarity, "affixes": [{"id": a, "tier": t} for a, t in affixes]}
        return evaluate([helmet], item, 80, ctx)["index"] == 0
    assert shown((25, 5), (30, 5)) and shown((25, 5), (30, 5), (501, 1)) and shown((25, 7), (501, 6), rarity="EXALTED")
    assert not shown((25, 5), (30, 4), (501, 4)) and not shown((25, 8))
    assert not shown((25, 5), (37, 5))                         # Physical Resistance isn't a build affix
    assert not shown((25, 5), (30, 5), rarity="MAGIC")


def test_endgame_rares_go_right_below_the_exalted_section():
    def doc(*names):
        return [{"name": n, "conditions": [] if n.startswith("--") or n == "HIDE" else [{"type": "RarityCondition"}],
                 "enabled": n == "HIDE" or not n.startswith("--"), "type": "HIDE" if n == "HIDE" else "SHOW"} for n in names]
    rules = doc("--- EXALTED & LEGENDARY ---", "double t7", "legendary", "--- UNIQUES ---", "unique", "HIDE")
    leveling, endgame = doc("[L] --- LEVELING ---", "[L] a"), doc("[E] --- ENDGAME ---", "[E] helmet")
    out, removed, at = place_leveling(rules, doc_infos, leveling, endgame, "[L] ", "[E] ")
    assert [r["name"] for r in out] == ["--- EXALTED & LEGENDARY ---", "double t7", "legendary", "[E] --- ENDGAME ---",
                                        "[E] helmet", "--- UNIQUES ---", "unique", "[L] --- LEVELING ---", "[L] a", "HIDE"]
    assert removed == 0 and at == 7
    again, removed, at = place_leveling(out, doc_infos, leveling[:1], endgame[:1], "[L] ", "[E] ")
    assert [r["name"] for r in again] == ["--- EXALTED & LEGENDARY ---", "double t7", "legendary", "[E] --- ENDGAME ---",
                                          "--- UNIQUES ---", "unique", "[L] --- LEVELING ---", "HIDE"]
    assert removed == 4 and at == 6
    # moved away, Reorder generated sections puts it back
    moved = [again[i] for i in (0, 1, 2, 4, 5, 3, 6, 7)]
    back, labels = reorder_generated(moved, {"leveling": "[L] ", "endgame": "[E] "})
    assert back == again and labels == ["endgame rares section"]
    # no exalted section: right before the uniques
    out, _, _ = place_leveling(doc("--- UNIQUES ---", "unique", "HIDE"), doc_infos, [], endgame, "[L] ", "[E] ")
    assert [r["name"] for r in out][:2] == ["[E] --- ENDGAME ---", "[E] helmet"]


def test_stun_affixes_are_the_stun_toggles_alone():
    affixes = [affix(29, "Health and Stun Avoidance", category="Stun", rolls_on=(0,), header="Defensive"),
               affix(51, "Stun Avoidance", category="Stun", rolls_on=(0,), header="Defensive"),
               affix(58, "Increased Stun Chance", category="General", rolls_on=(16,)),
               affix(91, "Increased Stun Chance with Melee Attacks", category="Melee", rolls_on=(16,)),
               affix(89, "Increased Melee Damage", category="Melee"),
               affix(25, "Added Health", category="Health", rolls_on=(0,))]
    picked = toggle_affixes({"focus": ["melee", "stun"], "defence": ["health"]}, affixes)
    assert names(picked["melee"]) == ["Increased Melee Damage"]                 # no melee stun chance
    assert names(picked["stun"]) == ["Stun Avoidance", "Increased Stun Chance", "Increased Stun Chance with Melee Attacks"]
    assert names(picked["health"]) == ["Health and Stun Avoidance", "Added Health"]   # a health affix, not a stun one
    # the other ways of hitting drop their stun affixes too
    assert names(toggle_affixes({"focus": ["spell", "stun"]}, affixes)["stun"]) == ["Stun Avoidance", "Increased Stun Chance"]


def test_endgame_only_makes_just_the_endgame_rares():
    table = {"weapons": ["2H Sword"], "damage": ["physical"], "defence": ["health"], "armour": True,
             "good_bases": {"Helmet": ["Laser Hat"]}}
    full = plan_leveling(parse_options(table, BASES), DATA)
    only = plan_leveling(parse_options({**table, "endgame_only": True}, BASES), DATA)
    assert full.rules and only.rules == [] and only.windows == {}
    assert [r.name for r in only.endgame] == [r.name for r in full.endgame] and len(only.endgame) > 1
    assert set(only.rule_affixes) == {r.name for r in only.endgame[1:]}
    assert any("good_bases" in w for w in full.warnings) and not any("good_bases" in w for w in only.warnings)
    with pytest.raises(ConfigError, match="endgame_only"):
        parse_options({"endgame_only": "yes"}, BASES)
    # applied: the filter's leveling section stays as it is, the endgame rares go below the exalted rules
    def doc(*names):
        return [{"name": n, "conditions": [] if n.startswith("--") or n == "HIDE" else [{"type": "RarityCondition"}],
                 "enabled": n == "HIDE" or not n.startswith("--"), "type": "HIDE" if n == "HIDE" else "SHOW"} for n in names]
    rules = doc("--- EXALTED & LEGENDARY ---", "double t7", "--- UNIQUES ---", "[L] --- LEVELING ---", "[L] a", "[E] old", "HIDE")
    out, removed, at = place_leveling(rules, doc_infos, None, doc("[E] --- ENDGAME ---", "[E] helmet"), "[L] ", "[E] ")
    assert [r["name"] for r in out] == ["--- EXALTED & LEGENDARY ---", "double t7", "--- UNIQUES ---", "[L] --- LEVELING ---",
                                        "[L] a", "[E] --- ENDGAME ---", "[E] helmet", "HIDE"]
    assert removed == 1 and at == 5                                    # the old endgame rare replaced where it was
