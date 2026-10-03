import tomllib
from pathlib import Path

import pytest

from lefilter.rules import (UPDATED_AFFIX_RULES, UPDATED_CLASS_HIDE_NAME, UPDATED_EXALTED_RULES, UPDATED_GROUP_RULES, ConfigError, RuleSpec, build_slot_filters, categorize, plan_rules, unique_kind,
                            released_defaults, upgrade_config)

THRESHOLDS = {"uncommon": 0.25, "rare": 0.5, "very_rare": 0.75, "extremely_rare": 0.95}


def unique(uid, name, lpl=50, reroll=0.0, random=True, **flags):
    return {"id": uid, "name": name, "internal_name": name.replace("'", ""), "lpl": lpl, "level": lpl,
            "reroll_chance": reroll, "can_drop_randomly": random, "weavers_will": flags.get("ww", False),
            "is_set": flags.get("set", False), "is_primordial": flags.get("primordial", False),
            "is_cocooned": flags.get("cocooned", False), "hidden": False, "base_type_name": "Ring"}


@pytest.mark.parametrize("reroll,expected", [
    (0.0, "common"), (0.2, "common"), (0.25, "uncommon"), (0.4, "uncommon"), (0.5, "rare"),
    (0.72, "rare"), (0.75, "very_rare"), (0.9, "very_rare"), (0.97, "extremely_rare"),
])
def test_categorize_by_reroll_chance(reroll, expected):
    assert categorize(unique(1, "x", reroll=reroll), THRESHOLDS) == expected


def test_categorize_flags_take_precedence_over_rarity():
    assert categorize(unique(1, "x", random=False), THRESHOLDS) == "special"
    assert categorize(unique(1, "x", random=False, primordial=True), THRESHOLDS) == "primordial"
    assert categorize(unique(1, "x", random=False, cocooned=True), THRESHOLDS) == "cocooned"
    assert categorize(unique(1, "x", reroll=0.9, ww=True), THRESHOLDS) == "weaver"
    assert categorize(unique(1, "x", set=True), THRESHOLDS) == "set_common"
    assert categorize(unique(1, "x", set=True, reroll=0.7), THRESHOLDS) == "set_rare"
    assert categorize(unique(1, "x", set=True, random=False), THRESHOLDS) == "set_special"


def test_unique_kind_sorts_as_categorize_does_before_drop_rarity():
    assert unique_kind(unique(1, "x", reroll=0.9)) == "random" and unique_kind(unique(1, "x", random=False)) == "non_random"
    assert unique_kind(unique(1, "x", random=False, primordial=True)) == "primordial"
    assert unique_kind(unique(1, "x", ww=True, random=False)) == "weaver"
    assert unique_kind(unique(1, "x", set=True, ww=True)) == "set"


def config(*groups):
    return {"rarity": THRESHOLDS, "filter": {"rule_prefix": "[A] "}, "group": list(groups)}


UNIQUES = [
    unique(1, "Low Common", lpl=20),
    unique(2, "High Common", lpl=70),
    unique(3, "Rare One", lpl=60, reroll=0.6),
    unique(4, "Boss Drop", lpl=80, random=False),
    unique(5, "Clotho's Needle", ww=True),
]


def test_lpl_split_selects_disjoint_members():
    plan = plan_rules(config(
        {"name": "C 60+", "categories": ["common"], "lpl_min": 60, "rules": [{"lp_min": 1}]},
        {"name": "C 0-59", "categories": ["common"], "lpl_max": 59, "rules": [{"lp_min": 1}]},
    ), UNIQUES)
    assert [r.unique_ids for r in plan.rules] == [[2], [1]]
    assert plan.rules[0].name == "[A] C 60+ - 1LP+"


def test_only_matches_names_loosely_and_empty_only_is_skipped_silently():
    plan = plan_rules(config(
        {"name": "Picks", "only": ["clothos needle"], "rules": [{}]},
        {"name": "Placeholder", "only": [], "rules": [{}]},
    ), UNIQUES)
    assert [r.unique_ids for r in plan.rules] == [[5]]
    assert plan.warnings == []


def test_build_slot_filters_name_each_kind_of_unique_slot():
    uniques = [*UNIQUES, unique(6, "First One", random=False, primordial=True), unique(7, "Cocooned Club", cocooned=True),
               unique(8, "Set Ring", set=True)]
    cfg = {**config(
        {"name": "RANDOM", "header": "--- RANDOM DROPS ---", "categories": ["common", "rare"], "rules": [{}]},
        {"name": "SPECIAL", "header": "--- NON-RANDOM DROPS ---", "categories": ["special"], "rules": [{}]},
        {"name": "WEAVER", "header": "--- WEAVER'S WILL ---", "categories": ["weaver"], "rules": [{}]},
        {"name": "PRIMORDIAL", "header": "--- PRIMORDIAL / COCOONED ---", "categories": ["primordial"], "rules": [{}]},
        {"name": "COCOONED", "categories": ["cocooned"], "rules": [{}]},
        {"name": "LET THROUGH", "categories": ["special"], "rules": [{}]},   # no header: joins the primordial section
        {"name": "SETS", "header": "------- SET ITEMS -------", "categories": ["set_common", "set_rare"], "rules": [{}]},
    ), "build_slots": {"add": True}}
    assert build_slot_filters(cfg, uniques) == {"[A] EDIT FOR YOUR BUILD - RANDOM DROPS": "random",
                                                "[A] EDIT FOR YOUR BUILD - NON-RANDOM DROPS": "non_random",
                                                "[A] EDIT FOR YOUR BUILD - WEAVER'S WILL": "weaver",
                                                "[A] EDIT FOR YOUR BUILD - PRIMORDIAL / COCOONED": "primordial",
                                                "[A] EDIT FOR YOUR BUILD - SET ITEMS": "set"}
    assert build_slot_filters({}, uniques) == {}   # a broken config: no filters, no error


def test_no_unique_group_of_the_default_config_lists_cocooned_items():
    from lefilter.rules import TYPE_IDS, read_config
    uniques = [{**unique(i, f"U{i}", **flags), "base_type": TYPE_IDS[t]} for i, (t, flags) in enumerate([
        ("ONE_HANDED_MACES", {"cocooned": True}), ("IDOL_1x1_ETERRA", {"cocooned": True}),   # even a cocooned idol
        ("RING", {}), ("IDOL_1x1_ETERRA", {}), ("RELIC", {"primordial": True})], 1)]
    plan = plan_rules(read_config(Path(__file__).parent.parent / "config.toml"), uniques)
    assert not [r.name for r in plan.rules if {1, 2} & set(r.unique_ids or [])]   # the [starter] cocooned rule shows them
    names = [r.name for r in plan.rules]
    assert "[A] --- PRIMORDIAL ---" in names and "[A] EDIT FOR YOUR BUILD - PRIMORDIAL" in names


def test_unknown_unique_name_suggests_close_match():
    with pytest.raises(ConfigError, match="Clotho's Needle"):
        plan_rules(config({"name": "Picks", "only": ["Clotho Needle"], "rules": [{}]}), UNIQUES)


def test_unknown_config_keys_are_rejected():
    with pytest.raises(ConfigError, match="lp_minimum"):
        plan_rules(config({"name": "G", "categories": ["rare"], "rules": [{"lp_minimum": 1}]}), UNIQUES)


def test_shadowed_rule_is_reported():
    plan = plan_rules(config(
        {"name": "G", "categories": ["rare"], "rules": [{"lp_min": 1}, {"lp_min": 2}]},
    ), UNIQUES)
    assert any("'2LP+' can never match" in w for w in plan.warnings)


def test_disabled_rules_do_not_count_as_shadowing():
    plan = plan_rules(config(
        {"name": "G", "categories": ["rare"], "rules": [{"enabled": False}, {"lp_min": 2}]},
    ), UNIQUES)
    assert plan.warnings == []


def test_uncovered_uniques_are_listed():
    plan = plan_rules(config({"name": "G", "categories": ["rare"], "rules": [{}]}), UNIQUES)
    assert {u["id"] for u in plan.uncovered} == {1, 2, 4, 5}


def test_auto_labels():
    assert RuleSpec(lp_min=2).auto_label() == "2LP+"
    assert RuleSpec(ww_min=17).auto_label() == "17+ WW"
    assert RuleSpec(ww_max=16).auto_label() == "0-16 WW"
    assert RuleSpec(ww_min=15, ww_max=18).auto_label() == "15-18 WW"
    assert RuleSpec().auto_label() == "all"


def test_weaver_brackets_and_old_defaults_upgrade():
    raw = tomllib.loads((Path(__file__).parent.parent / "config.toml").read_text(encoding="utf-8"))
    weaver = next(g for g in raw["group"] if g["name"] == "WEAVER")
    old, new = UPDATED_GROUP_RULES["WEAVER"]
    assert weaver["rules"] == new and raw["exalted_rule"] == UPDATED_EXALTED_RULES[1]
    names = [r.name for r in plan_rules(config(weaver), [unique(1, "Woven", ww=True)]).rules]
    assert names == ["[A] WEAVER - 19+ WW", "[A] WEAVER - 15-18 WW", "[A] WEAVER - 0-14 WW"]
    released = {**raw, "group": [{**weaver, "rules": old}], "exalted_rule": UPDATED_EXALTED_RULES[0]}   # a v0.2.0 copy
    up = upgrade_config(released)
    assert up["group"][0]["rules"] == new and up["exalted_rule"] == UPDATED_EXALTED_RULES[1]
    assert released["group"][0]["rules"] == old                    # the caller's config isn't changed
    mine = {**weaver, "rules": [{**old[0], "color": 9}, old[1]]}   # changed by the user: stays theirs
    assert upgrade_config({"group": [mine]})["group"] == [mine]
    back = released_defaults(raw)                                  # what earlier versions generated from it
    assert back["group"][[g["name"] for g in raw["group"]].index("WEAVER")]["rules"] == old
    assert back["exalted_rule"] == UPDATED_EXALTED_RULES[0] and back["starter"]["corrupted"] is False
    assert raw["class_hide"]["name"] == UPDATED_CLASS_HIDE_NAME[1] and back["class_hide"]["name"] == UPDATED_CLASS_HIDE_NAME[0]
    assert upgrade_config(released_defaults(raw))["class_hide"]["name"] == UPDATED_CLASS_HIDE_NAME[1]
    assert raw["affix_rule"] == UPDATED_AFFIX_RULES[1] and back["affix_rule"] == UPDATED_AFFIX_RULES[0]
    assert upgrade_config({"affix_rule": UPDATED_AFFIX_RULES[0]})["affix_rule"] == UPDATED_AFFIX_RULES[1]


def test_set_groups_use_set_rarity_and_headers_become_separators():
    uniques = UNIQUES + [unique(9, "Some Set Ring", set=True, reroll=0.7)]
    plan = plan_rules(config(
        {"name": "SETS", "header": "--- SETS ---", "categories": ["set_rare"], "rules": [{}]},
        {"name": "Empty picks", "header": "--- PICKS ---", "only": [], "rules": [{}]},
    ), uniques)
    sep, rule, picks_sep = plan.rules
    assert sep.is_separator and sep.name == "[A] --- SETS ---" and not sep.spec.enabled
    assert rule.rarity == "SET" and rule.unique_ids == [9]
    assert picks_sep.is_separator  # headers are emitted even when their group selects nothing


def test_build_slot_closes_each_section():
    uniques = UNIQUES + [unique(9, "Some Set Ring", set=True, reroll=0.7)]
    cfg = config(
        {"name": "TOP", "header": "--- TOP ---", "build_slot": False, "categories": ["rare"], "rules": [{}]},
        {"name": "C1", "header": "------ COMMONS ------", "categories": ["common"], "lpl_min": 60, "rules": [{}]},
        {"name": "C2", "categories": ["common"], "lpl_max": 59, "rules": [{}]},
        {"name": "SETS", "header": "== SETS ==", "build_slot": {"color": 16}, "categories": ["set_rare"],
         "rules": [{}]},
    )
    cfg["build_slots"] = {"add": True, "name": "EDIT FOR YOUR BUILD - {section}", "color": 3}
    names = [(r.name, r.rarity, r.unique_ids) for r in plan_rules(cfg, uniques).rules]
    assert names == [
        ("[A] --- TOP ---", None, None), ("[A] TOP - all", "UNIQUE", [3]),
        ("[A] ------ COMMONS ------", None, None), ("[A] C1 - all", "UNIQUE", [2]), ("[A] C2 - all", "UNIQUE", [1]),
        ("[A] EDIT FOR YOUR BUILD - COMMONS", "UNIQUE", []),
        ("[A] == SETS ==", None, None), ("[A] SETS - all", "SET", [9]),
        ("[A] EDIT FOR YOUR BUILD - SETS", "SET", []),
    ]
    slot = plan_rules(cfg, uniques).rules[-1].spec
    assert slot.color == 16 and not slot.enabled


def test_build_slot_rejects_unknown_options():
    cfg = config({"name": "S", "header": "--- S ---", "build_slot": {"colour": 2}, "categories": ["rare"],
                  "rules": [{}]})
    cfg["build_slots"] = {"add": True}
    with pytest.raises(ConfigError, match="colour"):
        plan_rules(cfg, UNIQUES)


AFFIXES = [
    {"id": 698, "name": "Julra's", "category": "Personal"},
    {"id": 1111, "name": "Blood Rage Frenzy", "category": "Variant"},
    {"id": 5, "name": "Health", "category": "Health"},
]


def test_affix_rule_selects_picker_categories_case_insensitively():
    from lefilter.rules import plan_affix_rules
    cfg = {"filter": {"rule_prefix": "[A] "},
           "affix_rule": [{"name": "ALWAYS", "affix_categories": ["personal", "Variant"], "emphasized": True}]}
    rules, members, _ = plan_affix_rules(cfg, AFFIXES)
    assert [(r.name, r.affix_ids, r.rarity, r.unique_ids) for r in rules] == [("[A] ALWAYS", [698, 1111], None, None)]
    assert rules[0].spec.emphasized


def test_affix_rule_unknown_category_lists_known_ones():
    from lefilter.rules import plan_affix_rules
    cfg = {"affix_rule": [{"name": "X", "affix_categories": ["Personnal"]}]}
    with pytest.raises(ConfigError, match="known: Health, Personal, Variant"):
        plan_affix_rules(cfg, AFFIXES)


def test_class_hide_is_one_rule_set_up_for_the_classes_played():
    from lefilter.rules import plan_class_hide
    others = ["Primalist", "Mage", "Acolyte", "Rogue"]
    cfg = {"filter": {"rule_prefix": "[A] "}, "class_hide": {"add": True, "enabled_for": ["Sentinel"]}}
    [rule] = plan_class_hide(cfg)
    assert rule.name == "[A] Hide items of other classes (select what classes you don't want to see)"
    assert rule.spec.action == "hide" and rule.spec.enabled and rule.classes == others and rule.rarity == "NORMAL MAGIC RARE"
    [off] = plan_class_hide({**cfg, "class_hide": {"add": True}})
    assert not off.spec.enabled and off.classes == [*others[:2], "Sentinel", *others[2:]]   # all five: none would hide anything
    renamed = {**cfg, "class_hide": {"add": True, "name": "No {class} stuff"}}
    assert [r.name for r in plan_class_hide(renamed)] == [rule.name]                  # a per-class name: the default one
    assert [r.name for r in plan_class_hide(renamed, per_class=True)] == [f"[A] No {c} stuff" for c in (
        "Primalist", "Mage", "Sentinel", "Acolyte", "Rogue")]                         # what earlier versions made of it
    assert plan_class_hide({}) == []


def test_class_hide_rejects_bad_options():
    from lefilter.rules import plan_class_hide
    with pytest.raises(ConfigError, match="enabled_for"):
        plan_class_hide({"class_hide": {"add": True, "enabled_for": ["Necromancer"]}})
    with pytest.raises(ConfigError, match="unknown key"):
        plan_class_hide({"class_hide": {"add": True, "classes": []}})
    with pytest.raises(ConfigError, match="every class"):
        plan_class_hide({"class_hide": {"add": True, "enabled_for": ["Primalist", "Mage", "Sentinel", "Acolyte", "Rogue"]}})


def test_uniques_hidden_from_players_are_left_out():
    hidden = {**unique(9, "Sharktooth Saw", random=False), "hidden": True}
    plan = plan_rules(config({"name": "SPECIAL", "categories": ["special"], "rules": [{}]}), UNIQUES + [hidden])
    assert [u["name"] for u in plan.members["SPECIAL"]] == ["Boss Drop"] and 9 not in [u["id"] for u in plan.uncovered]
