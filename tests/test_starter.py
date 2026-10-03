from pathlib import Path

import pytest

from lefilter.filterdoc import new_rule, parse_rule_blocks
from lefilter.filterxml import render_rule
from lefilter.matcher import Context, evaluate
from lefilter.gamedata import CLASSES
from lefilter.rules import ConfigError, plan_rules
from lefilter.starter import build_starter, gear_affix_ids, plan_exalted, refresh_generated

THRESHOLDS = {"uncommon": 0.25, "rare": 0.5, "very_rare": 0.75, "extremely_rare": 0.95}


def unique(uid, name, base_type=21, lpl=20, reroll=0.0):
    return {"id": uid, "name": name, "internal_name": name, "lpl": lpl, "level": lpl, "reroll_chance": reroll,
            "can_drop_randomly": True, "weavers_will": False, "is_set": False, "is_primordial": False,
            "is_cocooned": False, "hidden": False, "base_type": base_type, "base_type_name": "x"}


def affix(aid, name, rolls_on=(16, 0), special=0, idol=False):
    return {"id": aid, "name": name, "category": "c", "header": "", "class": 0, "special": special, "idol": idol,
            "prefix": True, "level": 0, "rolls_on": list(rolls_on)}


DATA = {
    "game_version": "1.5",
    "uniques": [unique(1, "Ring One"), unique(2, "Idol One", base_type=33), unique(3, "Idol Two", base_type=25, lpl=0)],
    "affixes": [affix(30, "Phys"), affix(25, "Health"), affix(105, "Idol Health", (33,), idol=True),
                affix(950, "Set thing", special=3), affix(1088, "Altar thing", (41,)),
                affix(698, "Julra's", special=2)],
    "bases": [{"id": 16, "type": "TWO_HANDED_SWORD", "name": "Two-Handed Sword", "category": "", "weapon": True,
               "subtypes": [{"id": 0, "name": "Bastard Sword", "level": 0, "drops": True, "class": 0}]}],
}
CONFIG = {
    "filter": {"rule_prefix": "[A] "},
    "rarity": THRESHOLDS,
    "affix_rule": [{"name": "ALWAYS SHOW - PERSONAL", "affix_categories": ["c"]}],
    "class_hide": {"add": True},
    "starter": {"legendary": {"name": "LEGENDARY", "color": 7}, "hide_rest": {"name": "HIDE REST"}},
    "exalted_rule": [{"name": "DOUBLE T7", "min": 2, "tier": 7, "uncorrupted": True, "color": 7},
                     {"name": "T7 + T6", "min": 2, "tier": 6, "total": 13},
                     {"name": "SINGLE T7", "min": 1, "tier": 7}],
    "group": [{"name": "COMMON", "header": "--- UNIQUES ---", "categories": ["common"], "rules": [{"lp_min": 1}]},
              {"name": "UNIQUE IDOLS", "categories": ["common"], "base_types": ["IDOLS"], "rules": [{"label": "show all"}]}],
    "build_slots": {"add": True, "name": "EDIT FOR YOUR BUILD - {section}"},
}
CTX = Context({**DATA, "bases": []})
HIDE = "[A] Hide items of other classes (select what classes you don't want to see)"


def hidden(rule):
    """The classes a class hide rule ticks."""
    return next(c for c in rule["conditions"] if c["type"] == "ClassCondition")["classes"]


def test_exalted_rules_count_gear_affixes_by_tier():
    assert gear_affix_ids(DATA["affixes"]) == [30, 25]           # no idol, set, personal or altar affixes
    rules = parse_rule_blocks([render_rule(r) for r in plan_exalted(CONFIG, DATA["affixes"])])
    double = rules[0]["conditions"]
    assert double[0] == {"type": "AffixCondition", "affixes": [30, 25], "comparsion": "MORE_OR_EQUAL",
                         "comparsion_value": 7, "min_on_same_item": 2, "combined_comparsion": "ANY",
                         "combined_value": 1, "advanced": True}
    assert double[1] == {"type": "CorruptionCondition", "corruption": "OnlyUncorrupted"}
    item = lambda t1, t2, corrupted=False: {"type": "BOOTS", "subtype": 0, "rarity": "RARE", "corrupted": corrupted,
                                            "affixes": [{"id": 30, "tier": t1}, {"id": 25, "tier": t2}]}
    name = lambda it: rules[evaluate(rules, it, 50, CTX)["index"]]["name"] if evaluate(rules, it, 50, CTX)["index"] is not None else None
    assert name(item(7, 7)) == "DOUBLE T7"
    assert name(item(7, 7, corrupted=True)) == "T7 + T6"
    assert name(item(7, 6)) == "T7 + T6"
    assert name(item(7, 5)) == "SINGLE T7"
    assert name(item(6, 6)) is None
    with pytest.raises(ConfigError, match="tier 1-8"):
        plan_exalted({"exalted_rule": [{"name": "x", "tier": 9}]}, DATA["affixes"])


def test_unique_groups_can_select_by_item_type():
    plan = plan_rules(CONFIG, DATA["uniques"])
    assert [u["id"] for u in plan.members["UNIQUE IDOLS"]] == [3, 2]       # sorted by LPL
    assert [u["id"] for u in plan.members["COMMON"]] == [3, 2, 1]           # same LPL: by name
    with pytest.raises(ConfigError, match="base_types"):
        plan_rules({**CONFIG, "group": [{"name": "G", "categories": ["common"], "base_types": ["IDOLZ"], "rules": [{}]}]},
                   DATA["uniques"])


def test_starter_parts_in_order_with_class_enabled():
    doc = build_starter(CONFIG, DATA, {"name": "Sentinel", "character_class": "Sentinel",
                                       "parts": ["personal", "exalted", "legendary", "class_hide", "uniques", "hide_rest"]})
    names = [(r["name"], r["enabled"]) for r in doc["rules"]]
    assert names[1] == (HIDE, True)        # one rule, right below the always-show rule: before every other rule
    assert hidden(doc["rules"][1]) == ["Primalist", "Mage", "Acolyte", "Rogue"]   # every class but the chosen one
    assert names[:1] + names[2:8] == [("[A] ALWAYS SHOW - PERSONAL", True), ("------ EXALTED & LEGENDARY ------", False),
                                       ("DOUBLE T7", True), ("T7 + T6", True), ("SINGLE T7", True),
                                       ("SHOW ALL CORRUPTED ITEMS", True), ("LEGENDARY", True)]
    corrupted = doc["rules"][6]["conditions"]
    assert {c["type"]: c for c in corrupted}["CorruptionCondition"]["corruption"] == "OnlyCorrupted"
    assert {c["type"]: c for c in corrupted}["RarityCondition"]["rarity"] == ["NORMAL", "MAGIC", "RARE", "EXALTED"]
    off = build_starter({**CONFIG, "starter": {**CONFIG["starter"], "corrupted": False}}, DATA, {"parts": ["exalted"]})
    assert "SHOW ALL CORRUPTED ITEMS" not in [r["name"] for r in off["rules"]]
    recoloured = build_starter({**CONFIG, "starter": {"corrupted": {"color": 4}}}, DATA, {"parts": ["exalted"]})
    assert {r["name"]: r["color"] for r in recoloured["rules"]}["SHOW ALL CORRUPTED ITEMS"] == 4
    assert names[-1] == ("HIDE REST", True) and doc["rules"][-1]["type"] == "HIDE" and not doc["rules"][-1]["conditions"]
    assert doc["header"]["name"] == "Sentinel" and doc["header"]["version"] == "1.5"


def test_starter_leveling_goes_above_the_bottom_hide_rule():
    doc = build_starter(CONFIG, DATA, {"parts": ["hide_rest", "leveling"],
                                       "leveling": {"weapons": ["TWO_HANDED_SWORD"], "weapon_mode": "bases"}})
    assert [r["name"] for r in doc["rules"]] == ["[L] ------- LEVELING (auto) -------", "[L] Two-Handed Sword 0-59",
                                                "HIDE REST"]


def test_refresh_keeps_toggles_and_filled_build_slots():
    first = build_starter(CONFIG, DATA, {"parts": ["class_hide", "uniques", "hide_rest"]})["rules"]
    by = {r["name"]: r for r in first}
    assert not by[HIDE]["enabled"] and hidden(by[HIDE]) == list(CLASSES)   # no class: off, all five ticked
    by[HIDE]["enabled"] = True
    hidden(by[HIDE])[:] = ["Sentinel", "Rogue"]                            # the user's pick
    slot = by["[A] EDIT FOR YOUR BUILD - UNIQUES"]
    slot["conditions"][1]["uniques"] = [{"id": 1, "rolls": []}]
    slot["enabled"] = True
    config = {**CONFIG, "group": CONFIG["group"] + [{"name": "NEW GROUP", "categories": ["common"], "rules": [{}]}]}
    res = refresh_generated(config, DATA, first)
    names = [r["name"] for r in res["rules"]]
    assert "[A] NEW GROUP - all" in names and names[-1] == "HIDE REST"
    again = {r["name"]: r for r in res["rules"]}
    assert again[HIDE]["enabled"] and hidden(again[HIDE]) == ["Sentinel", "Rogue"]
    assert again["[A] EDIT FOR YOUR BUILD - UNIQUES"]["conditions"][1]["uniques"] == [{"id": 1, "rolls": []}]
    assert refresh_generated(config, DATA, res["rules"])["rules"] == res["rules"]


def test_refresh_into_a_filter_without_generated_rules():
    rules = [new_rule("mine"), new_rule("------ UNIQUE ITEMS ------", enabled=False), new_rule("legendary"),
             new_rule("bottom", type="HIDE")]
    names = [r["name"] for r in refresh_generated(CONFIG, DATA, rules)["rules"]]
    assert names[0] == "[A] ALWAYS SHOW - PERSONAL"
    assert names[1:3] == [HIDE, "mine"]
    sep = names.index("------ UNIQUE ITEMS ------")
    assert names[sep + 1] == "[A] --- UNIQUES ---" and names[-2:] == ["legendary", "bottom"]


# --- BiS, shatter, T8, new-from-template ----------------------------------------------

from lefilter.gamedata import ARMOUR_TYPES, JEWELRY_TYPES, TYPE_IDS  # noqa: E402
from lefilter.starter import ensure_template, make_template, new_from_template, plan_bis, plan_shatter  # noqa: E402


def gaffix(aid, name, category="c", rolls_on=None, weight=1.0, cls=0, special=0):
    every = [TYPE_IDS[t] for t in ("TWO_HANDED_SWORD", *ARMOUR_TYPES, *JEWELRY_TYPES)]
    return {"id": aid, "name": name, "category": category, "header": "", "class": cls, "special": special,
            "idol": False, "prefix": True, "level": 0, "weight": weight, "rolls_on": rolls_on or every}


GEAR = [TYPE_IDS[t] for t in (*ARMOUR_TYPES, *JEWELRY_TYPES)]   # health doesn't roll on weapons
FULL = {
    **DATA,
    "affixes": [gaffix(30, "Increased Physical Damage"), gaffix(25, "Added Health", category="Health", rolls_on=GEAR),
                gaffix(36, "Hybrid Health", category="Health", rolls_on=GEAR, weight=0.1),
                gaffix(719, "Physical Penetration and Minion Physical Penetration", weight=0.15),
                gaffix(33, "Physical Penetration", rolls_on=[20], weight=0.3),
                gaffix(563, "Level of Rive", category="Sentinel", cls=8, rolls_on=[0, 1]),
                gaffix(1088, "Maximum Idols Equipped", category="Idol Altars", rolls_on=[41]),
                {**gaffix(105, "Idol Health", rolls_on=[33], weight=0.1), "idol": True}],
    "bases": [{"id": TYPE_IDS[t], "type": t, "name": t.title().replace("_", " "), "category": "", "weapon": False,
               "subtypes": [{"id": 0, "name": "b", "level": 0, "drops": True, "class": 0}]}
              for t in ("TWO_HANDED_SWORD", *ARMOUR_TYPES, *JEWELRY_TYPES, "IDOL_ALTAR")],
}
BUILD = {"damage": ["physical"], "defence": ["health"], "weapons": ["TWO_HANDED_SWORD"]}
FULL_CONFIG = {**CONFIG, "bis": {"tier": 7, "min": 1, "color": 9, "emphasized": True, "beam_size": "LARGEST", "beam_color": 12},
               "shatter": {"max_weight": 0.15, "class_tier": 3, "color": 16},
               "exalted_rule": [{"name": "ALL T8", "min": 1, "tier": 8}] + CONFIG["exalted_rule"]}


def test_bis_rules_per_slot_with_build_affixes_and_no_bases():
    rules = plan_bis(FULL_CONFIG, FULL, BUILD)
    names = [r.name for r in rules]
    assert names[0].startswith("------ BIS") and names[1] == "BIS - Two Handed Sword (pick bases)"
    assert len(rules) == 1 + 1 + 8 and not any(r.item_types == ["IDOL_ALTAR"] for r in rules)   # altars: idol section
    old_config = {**FULL_CONFIG, "bis": {**FULL_CONFIG["bis"], "altar": True}}   # a v0.1.0 config.toml still loads
    assert [r.name for r in plan_bis(old_config, FULL, BUILD)] == names
    sword, helmet = rules[1], rules[2]
    assert sword.item_types == ["TWO_HANDED_SWORD"] and sword.sub_types == [] and sword.affix_ids == [30, 719]
    assert set(helmet.affix_ids) == {30, 25, 36, 719} and helmet.affix_tier == 7
    assert sword.spec.color == 9 and sword.spec.emphasized and sword.spec.beam_size == "LARGEST"
    bare = plan_bis(FULL_CONFIG, FULL, {})
    assert bare[1].name == "BIS - Weapon (pick type & bases)" and bare[1].item_types == []
    assert not any(r.spec.enabled for r in bare[1:])            # nothing to go on yet: switched off
    no_weapon = plan_bis(FULL_CONFIG, FULL, {"defence": ["health"], "damage": ["physical"]})
    assert no_weapon[1].affix_ids == [30, 719]                  # only affixes that roll on weapons
    sentinel = plan_bis(FULL_CONFIG, FULL, {**BUILD, "class_affixes": ["Level of Rive"]}, "Sentinel")
    helmet, body, belt = sentinel[2:5]
    assert 563 in helmet.affix_ids and 563 in body.affix_ids and 563 not in belt.affix_ids
    assert 563 not in plan_bis(FULL_CONFIG, FULL, {**BUILD, "class_affixes": ["Level of Rive"]}, "Mage")[2].affix_ids


def test_shatter_rules():
    rules = plan_shatter(FULL_CONFIG, FULL, "Sentinel")
    general = rules[1]
    assert general.affix_ids == [36, 719] and general.affix_tier is None and general.rarity == "MAGIC RARE"   # exalted: the exalted rules
    assert not {t for t in general.item_types if t.startswith("IDOL")}       # idols can't be shattered
    by_name = {r.name: r for r in rules}
    assert by_name["SHATTER - SENTINEL AFFIXES"].spec.enabled and by_name["SHATTER - SENTINEL AFFIXES"].affix_ids == [563]
    assert by_name["SHATTER - SENTINEL AFFIXES"].affix_tier == 3
    assert not by_name["SHATTER - MAGE AFFIXES"].spec.enabled


def test_t8_rule_decides_before_double_t7():
    rules = parse_rule_blocks([render_rule(r) for r in plan_exalted(FULL_CONFIG, FULL["affixes"])])
    item = {"type": "BOOTS", "subtype": 0, "rarity": "RARE", "affixes": [{"id": 30, "tier": 8}, {"id": 25, "tier": 7}]}
    assert rules[evaluate(rules, item, 90, Context({**FULL, "uniques": [], "bases": []}))["index"]]["name"] == "ALL T8"


def test_new_from_template_applies_class_and_build(tmp_path):
    path = tmp_path / "New filter.xml"
    assert ensure_template(path, FULL_CONFIG, FULL) and not ensure_template(path, FULL_CONFIG, FULL)
    template = make_template(FULL_CONFIG, FULL)
    bis = [r for r in template["rules"] if r["name"].startswith("BIS - ")]
    assert bis and not any(r["enabled"] for r in bis)   # no build yet: off
    assert not any(r["enabled"] for r in template["rules"] if r["name"].startswith(("[A] Hide", "SHATTER - ")) and "RARE-ROLL" not in r["name"])
    next(r for r in template["rules"] if r["name"] == "ALL T8")["color"] = 3   # template edits carry over
    doc = new_from_template(FULL_CONFIG, FULL, template, {"name": "Sentinel", "character_class": "Sentinel",
                                                          "leveling": BUILD})
    by = {r["name"]: r for r in doc["rules"]}
    assert doc["header"]["name"] == "Sentinel" and by["ALL T8"]["color"] == 3
    assert doc["header"]["icon"] == 5 and template["header"]["icon"] == 0      # Sentinel's filter icon
    picked = new_from_template(FULL_CONFIG, FULL, template, {"character_class": "Sentinel", "icon": 20, "icon_color": 7})
    assert (picked["header"]["icon"], picked["header"]["icon_color"]) == (20, 7)
    assert by[HIDE]["enabled"] and hidden(by[HIDE]) == ["Primalist", "Mage", "Acolyte", "Rogue"]
    assert by["SHATTER - SENTINEL AFFIXES"]["enabled"] and not by["SHATTER - ROGUE AFFIXES"]["enabled"]
    names = [r["name"] for r in doc["rules"]]
    # a blank slate: the BiS rules stay the template's generic, switched-off ones
    assert names.index("BIS - Weapon (pick type & bases)") == names.index("------ BIS ITEMS (pick the bases) ------") + 1
    assert not by["BIS - Helmet (pick bases)"]["enabled"]
    assert names.index("ALL T8") < names.index("DOUBLE T7")


def test_add_missing_sections_completes_a_uniques_only_filter():
    from lefilter.starter import add_missing_sections
    template = make_template(FULL_CONFIG, FULL)
    # what `build --standalone` writes: the unique groups only, then a leveling rule added on top
    uniques = refresh_generated(FULL_CONFIG, FULL, [])["rules"]
    uniques = [r for r in uniques if not r["name"].startswith(("[A] ALWAYS SHOW", "[A] Hide"))]
    leveling = parse_rule_blocks([render_rule(r) for r in plan_rules(FULL_CONFIG, FULL["uniques"]).rules[:1]])[0]
    leveling["name"] = "[L] Helmet 0-59"
    rules = uniques + [leveling]
    res = add_missing_sections(FULL_CONFIG, FULL, template, rules, {"character_class": "Sentinel"})
    names = [r["name"] for r in res["rules"]]
    assert names[0] == "[A] ALWAYS SHOW - PERSONAL"
    assert names.index("------ BIS ITEMS (pick the bases) ------") < names.index("ALL T8") < names.index("[A] --- UNIQUES ---")
    assert names[1] == "------ SHATTER AFFIXES ------" and names[8] == HIDE
    assert names[-2:] == ["[L] Helmet 0-59", "HIDE REST"]      # the catch-all below the leveling section
    by = {r["name"]: r for r in res["rules"]}
    assert not by["BIS - Helmet (pick bases)"]["enabled"] and by["SHATTER - SENTINEL AFFIXES"]["enabled"]
    assert by[HIDE]["enabled"] and hidden(by[HIDE]) == ["Primalist", "Mage", "Acolyte", "Rogue"]
    assert "HIDE REST" in res["added"] and "[L] Helmet 0-59" not in res["added"]
    again = add_missing_sections(FULL_CONFIG, FULL, template, res["rules"], {"character_class": "Sentinel"})
    assert again["added"] == [] and [r["name"] for r in again["rules"]] == names   # nothing left to add


def _r(name, color=0, enabled=True):
    return {"name": name, "type": "SHOW", "conditions": [], "color": color, "enabled": enabled}


def test_reconcile_template_keeps_user_edits_and_removals():
    from lefilter.starter import reconcile_template
    base = [_r("A"), _r("B"), _r("C"), _r("D"), _r("E")]
    mine = [_r("A"), _r("B", color=3), _r("D"), _r("MY RULE"), _r("E")]          # B edited, C removed, own rule added
    fresh = [_r("A", color=1), _r("NEW 1"), _r("B", color=2), _r("C", color=2), _r("E"), _r("NEW 2")]   # D dropped
    rules, report = reconcile_template(base, mine, fresh)
    assert [(r["name"], r["color"]) for r in rules] == [("A", 1), ("NEW 1", 0), ("B", 3), ("MY RULE", 0), ("E", 0),
                                                        ("NEW 2", 0)]
    assert report == {"added": ["NEW 1", "NEW 2"], "updated": ["A"], "kept": ["B"], "dropped": ["D"]}
    # no copy as generated (a template from before the stamp): the user's rules stay, missing ones are added
    rules, report = reconcile_template(None, mine, fresh)
    assert [r["name"] for r in rules] == ["A", "NEW 1", "B", "C", "D", "MY RULE", "E", "NEW 2"]
    assert rules[0]["color"] == 0 and report["added"] == ["NEW 1", "C", "NEW 2"]


def test_sync_template_once_per_version(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import parse_filter
    path, backups = tmp_path / "templates" / "New filter.xml", tmp_path / "backups"
    read = lambda p: parse_filter(p.read_bytes().decode("utf-8-sig"))
    monkeypatch.setattr(starter, "__version__", "0.3.0")
    assert starter.sync_template(path, FULL_CONFIG, FULL, backups)["created"]
    assert starter.template_stamp(path) == "0.3.0" and starter.generated_copy(path).is_file()
    assert starter.sync_template(path, FULL_CONFIG, FULL, backups) is None          # same version: nothing to do
    doc = read(path)                                                               # the user edits the template
    doc["rules"] = [r for r in doc["rules"] if r["name"] != "SHATTER - RARE-ROLL AFFIXES"]
    next(r for r in doc["rules"] if r["name"] == "ALL T8")["color"] = 4
    starter.write_template(path, doc, "0.3.0")
    monkeypatch.setattr(starter, "__version__", "0.4.0")                           # a new version with a new rule
    config = {**FULL_CONFIG, "exalted_rule": FULL_CONFIG["exalted_rule"] + [{"name": "EXALTED - QUAD T5", "min": 4, "tier": 5}]}
    res = starter.sync_template(path, config, FULL, backups)
    assert res["from"] == "0.3.0" and res["to"] == "0.4.0" and res["added"] == ["EXALTED - QUAD T5"]
    names = [r["name"] for r in read(path)["rules"]]
    assert "SHATTER - RARE-ROLL AFFIXES" not in names                             # removed stays removed
    assert names.index("EXALTED - QUAD T5") == names.index("SINGLE T7") + 1
    assert next(r for r in read(path)["rules"] if r["name"] == "ALL T8")["color"] == 4
    assert starter.template_stamp(path) == "0.4.0" and Path(res["backup"]).is_file()
    assert "0.3.0 -> 0.4.0" in (path.parent / ".generated" / "updates.log").read_text()
    assert starter.sync_template(path, config, FULL, backups) is None



def test_first_update_of_an_unstamped_template_keeps_removals(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import new_rule, parse_filter, render_filter
    from lefilter.filterxml import write_filter
    read = lambda p: parse_filter(p.read_bytes().decode("utf-8-sig"))
    path, backups = tmp_path / "templates" / "New filter.xml", tmp_path / "backups"
    doc = make_template(FULL_CONFIG, FULL)                  # what v0.2.0 wrote: no stamp, no copy as generated
    doc["rules"] = [r for r in doc["rules"] if r["name"] != "HIDE REST"]                       # the user removed it
    doc["rules"].insert(1, starter.legacy_template_rules(FULL_CONFIG, FULL)["BIS - Idol Altar (pick bases & affixes)"])
    write_filter(path, render_filter(doc))
    monkeypatch.setattr(starter, "__version__", "0.3.0")
    res = starter.sync_template(path, FULL_CONFIG, FULL, backups)
    names = [r["name"] for r in read(path)["rules"]]
    assert res["first"] and "HIDE REST" not in names and "HIDE REST" not in res["added"]
    assert "BIS - Idol Altar (pick bases & affixes)" not in names and res["dropped"] == ["BIS - Idol Altar (pick bases & affixes)"]
    # an update cut short after the template was written: the copy as generated gets repaired
    copy = starter.generated_copy(path)
    starter.write_template(copy, read(copy), "0.2.9")
    assert starter.sync_template(path, FULL_CONFIG, FULL, backups) is None and starter.template_stamp(copy) == "0.3.0"


def test_add_missing_sections_uses_the_configured_class_hide_name():
    from lefilter.starter import add_missing_sections
    config = {**FULL_CONFIG, "class_hide": {"add": True, "name": "Not my classes"}}
    template = make_template(config, FULL)
    uniques = [r for r in refresh_generated(config, FULL, [])["rules"] if "Not my" not in r["name"]]
    res = add_missing_sections(config, FULL, template, uniques, {"character_class": "Rogue"})
    by = {r["name"]: r for r in res["rules"]}
    assert by["[A] Not my classes"]["enabled"] and hidden(by["[A] Not my classes"]) == ["Primalist", "Mage", "Sentinel", "Acolyte"]


def test_a_filled_in_legacy_placeholder_survives_the_first_update(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import new_rule, parse_filter, render_filter
    from lefilter.filterxml import write_filter
    path = tmp_path / "templates" / "New filter.xml"
    doc = make_template(FULL_CONFIG, FULL)
    doc["rules"].insert(1, new_rule("BIS - Idol Altar (pick bases & affixes)",
                                    conditions=[{"type": "SubTypeCondition", "types": ["IDOL_ALTAR"], "subtypes": [1, 2]}]))
    write_filter(path, render_filter(doc))
    monkeypatch.setattr(starter, "__version__", "0.3.0")
    res = starter.sync_template(path, FULL_CONFIG, FULL, tmp_path / "backups")
    names = [r["name"] for r in parse_filter(path.read_bytes().decode("utf-8-sig"))["rules"]]
    assert "BIS - Idol Altar (pick bases & affixes)" in names and not res["dropped"]   # the user picked its bases



def test_an_edited_legacy_placeholder_is_kept(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import parse_filter, render_filter
    from lefilter.filterxml import write_filter
    path = tmp_path / "templates" / "New filter.xml"
    doc = make_template(FULL_CONFIG, FULL)
    altar = starter.legacy_template_rules(FULL_CONFIG, FULL)["BIS - Idol Altar (pick bases & affixes)"]
    altar["color"] = 5                                      # recoloured, bases still unpicked
    doc["rules"].insert(1, altar)
    write_filter(path, render_filter(doc))
    monkeypatch.setattr(starter, "__version__", "0.3.0")
    res = starter.sync_template(path, FULL_CONFIG, FULL, tmp_path / "backups")
    assert not res["dropped"] and "BIS - Idol Altar (pick bases & affixes)" in [
        r["name"] for r in parse_filter(path.read_bytes().decode("utf-8-sig"))["rules"]]


def test_first_update_of_a_v020_template_gets_this_versions_defaults(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import parse_filter, render_filter
    from lefilter.filterxml import write_filter
    from lefilter.rules import UPDATED_EXALTED_RULES, UPDATED_GROUP_RULES, released_defaults
    _, new = UPDATED_GROUP_RULES["WEAVER"]
    config = {**FULL_CONFIG, "exalted_rule": UPDATED_EXALTED_RULES[1],
              "group": FULL_CONFIG["group"] + [{"name": "WEAVER", "categories": ["weaver"], "rules": new}]}
    data = {**FULL, "uniques": FULL["uniques"] + [{**unique(9, "Woven"), "weavers_will": True}]}
    path = tmp_path / "templates" / "New filter.xml"
    doc = make_template(released_defaults(config), data)   # what v0.2.0 wrote: two Weaver brackets, no corrupted rules,
    legacy = starter.legacy_template_rules(config, data)   # a hide rule per class...
    hides = [legacy[n] for n in starter.old_class_hide_names(config)]
    rest = [r for r in doc["rules"] if r["name"] != HIDE]
    at = next(i for i, r in enumerate(rest) if "SHATTER" in r["name"])
    doc["rules"] = rest[:at] + hides + rest[at:]           # ...and the class hide rules above the shatter section
    by = {r["name"]: r for r in doc["rules"]}
    assert "[A] WEAVER - 17+ WW" in by and "SHOW ALL CORRUPTED ITEMS" not in by
    by["[A] WEAVER - 0-16 WW"]["color"] = 5                 # the user recoloured one
    write_filter(path, render_filter(doc))
    monkeypatch.setattr(starter, "__version__", "0.3.0")
    res = starter.sync_template(path, config, data, tmp_path / "backups")
    names = [r["name"] for r in parse_filter(path.read_bytes().decode("utf-8-sig"))["rules"]]
    # [A] rules are regenerated as New makes them: the recoloured obsolete one goes too
    assert [n for n in names if n.startswith("[A] WEAVER")] == ["[A] WEAVER - 19+ WW", "[A] WEAVER - 15-18 WW",
                                                                 "[A] WEAVER - 0-14 WW"]
    assert set(res["dropped"]) == {"[A] WEAVER - 17+ WW", "[A] WEAVER - 0-16 WW", *[r["name"] for r in hides]}
    assert names.index("EXALTED - CORRUPTED DOUBLE T7") == names.index("EXALTED - SINGLE T7") + 1
    assert names.index("SHOW ALL CORRUPTED ITEMS") == names.index("EXALTED - CORRUPTED DOUBLE T7") + 1
    assert names[1] == "------ SHATTER AFFIXES ------"                       # moved to the top...
    assert names[8] == HIDE and not [n for n in names if "Hide non-" in n]   # ...the one class hide rule under it


def test_the_template_update_moves_the_shatter_section_to_the_top_once(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import parse_filter
    names = lambda: [r["name"] for r in parse_filter(path.read_bytes().decode("utf-8-sig"))["rules"]]
    path = tmp_path / "templates" / "New filter.xml"
    doc = make_template(FULL_CONFIG, FULL)
    shatter = [r for r in doc["rules"] if "SHATTER" in r["name"]]
    rest = [r for r in doc["rules"] if r not in shatter]
    at = [r["name"] for r in rest].index("[A] --- UNIQUES ---")
    low = {**doc, "rules": rest[:at] + shatter + rest[at:]}          # v0.3.0's layout: shatter right before the uniques
    monkeypatch.setattr(starter, "__version__", "0.3.0")
    starter.write_generated_template(path, low)
    monkeypatch.setattr(starter, "__version__", "0.3.1")
    starter.sync_template(path, FULL_CONFIG, FULL)
    assert names()[1] == "------ SHATTER AFFIXES ------" and names()[8] == HIDE
    starter.write_template(path, low, "0.3.1")                         # the user moves it down again...
    monkeypatch.setattr(starter, "__version__", "0.3.2")
    starter.sync_template(path, FULL_CONFIG, FULL)
    assert names().index("SHATTER - RARE-ROLL AFFIXES") == names().index("[A] --- UNIQUES ---") - 6   # ...and it stays
    assert names()[1] == HIDE


def test_refresh_turns_the_old_per_class_hide_rules_into_one():
    from lefilter.rules import plan_class_hide
    old_config = {**CONFIG, "class_hide": {"add": True, "name": "Hide non-{class} class non-legendary items", "enabled_for": ["Mage"]}}
    old = parse_rule_blocks([render_rule(r) for r in plan_class_hide(old_config, per_class=True)])
    res = refresh_generated(CONFIG, DATA, old + [new_rule("mine")])
    by = {r["name"]: r for r in res["rules"]}
    assert not [n for n in by if "Hide non-" in n]
    assert by[HIDE]["enabled"] and hidden(by[HIDE]) == ["Primalist", "Sentinel", "Acolyte", "Rogue"]   # what "non-Mage" hid
    none_on = refresh_generated(CONFIG, DATA, [{**r, "enabled": False} for r in old])["rules"]
    one = next(r for r in none_on if r["name"] == HIDE)
    assert not one["enabled"] and hidden(one) == list(CLASSES)


def test_restore_the_exalted_section_from_the_template():
    from lefilter.starter import restore_section
    template = make_template(FULL_CONFIG, FULL)
    header = "------ EXALTED & LEGENDARY ------"
    names = [r["name"] for r in template["rules"]]
    start = names.index(header)
    section = names[start:names.index("[A] --- UNIQUES ---")]
    assert section[-3:] == ["SINGLE T7", "SHOW ALL CORRUPTED ITEMS", "LEGENDARY"]
    # a filter from before the corrupted rules, with a rule of the user's in the section and a recoloured one
    old = [dict(r) for r in template["rules"] if r["name"] != "SHOW ALL CORRUPTED ITEMS"]
    mine = new_rule("My exalted thing", conditions=[{"type": "RarityCondition", "rarity": ["EXALTED"]}])
    old.insert([r["name"] for r in old].index("LEGENDARY"), mine)
    next(r for r in old if r["name"] == "ALL T8")["color"] = 3
    res = restore_section(old, template, header)
    assert res["found"] and not res["matches"]
    added = [r["name"] for r in res["add"]["rules"]]
    assert res["add"]["added"] == ["SHOW ALL CORRUPTED ITEMS"] and res["add"]["removed"] == []
    assert added[added.index("SHOW ALL CORRUPTED ITEMS") - 1] == section[-3]       # after the rule it follows
    assert "My exalted thing" in added and next(r for r in res["add"]["rules"] if r["name"] == "ALL T8")["color"] == 3
    replaced = res["replace"]["rules"]
    assert [r["name"] for r in replaced][start:start + len(section)] == section and "My exalted thing" not in [r["name"] for r in replaced]
    assert "My exalted thing" in res["replace"]["removed"] and next(r for r in replaced if r["name"] == "ALL T8")["color"] != 3
    assert restore_section(replaced, template, header)["matches"]
    # no exalted section at all: the whole section after the BiS one
    bare = [r for r in template["rules"] if r["name"] not in section]
    got = restore_section(bare, template, header)
    out = [r["name"] for r in got["add"]["rules"]]
    assert not got["found"] and got["add"]["added"] == section
    bis_end = max(i for i, n in enumerate(out) if n.startswith("BIS - "))
    assert out.index(header) == bis_end + 1 and out[bis_end + 1:bis_end + 1 + len(section)] == section
    with pytest.raises(ConfigError):
        restore_section(bare, {"rules": bare}, header)


def test_a_v031_template_gets_the_personal_only_always_show_rule(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import parse_filter
    from lefilter.rules import UPDATED_AFFIX_RULES
    path = tmp_path / "templates" / "New filter.xml"
    data = {**FULL, "affixes": FULL["affixes"] + [{**gaffix(1200, "Personal thing", category="Personal"), "special": 2},
                                                  {**gaffix(1111, "Blood Rage Frenzy", category="Variant"), "special": 7}]}
    old_config = {**FULL_CONFIG, "affix_rule": UPDATED_AFFIX_RULES[0]}
    monkeypatch.setattr(starter, "__version__", "0.3.1")
    starter.write_generated_template(path, make_template(old_config, data))
    monkeypatch.setattr(starter, "__version__", "0.3.2")
    res = starter.sync_template(path, {**FULL_CONFIG, "affix_rule": UPDATED_AFFIX_RULES[1]}, data)
    rules = parse_filter(path.read_bytes().decode("utf-8-sig"))["rules"]
    assert rules[0]["name"] == "[A] ALWAYS SHOW - PERSONAL AFFIXES" and res["dropped"] == ["[A] ALWAYS SHOW - PERSONAL & VARIANT AFFIXES"]
    assert next(c for c in rules[0]["conditions"] if c["type"] == "AffixCondition")["affixes"] == [1200]


def test_old_per_class_hide_rules_dont_drag_the_unique_block_up_on_refresh():
    from lefilter.rules import plan_class_hide
    template = make_template(FULL_CONFIG, FULL)["rules"]
    old_config = {**FULL_CONFIG, "class_hide": {"add": True, "name": "Hide non-{class} class non-legendary items"}}
    old_hide = parse_rule_blocks([render_rule(r) for r in plan_class_hide(old_config, per_class=True)])
    rules = [template[0], *old_hide, *[r for r in template[1:] if r["name"] != HIDE]]   # five old ones right below the top
    names = [r["name"] for r in refresh_generated(FULL_CONFIG, FULL, rules)["rules"]]
    assert names.index("[A] --- UNIQUES ---") > names.index("LEGENDARY")                 # stays below the exalted section
    assert names.index(HIDE) == names.index("SHATTER - ROGUE AFFIXES") + 1 and not [n for n in names if "Hide non-" in n]


# --- v0.3.3: cocooned items below the legendary rule, a primordial section -------------------------
from lefilter.rules import upgrade_config  # noqa: E402

OLD_SEP, NEW_SEP = "[A] --- PRIMORDIAL / COCOONED ---", "[A] --- PRIMORDIAL ---"
OLD_SLOT, NEW_SLOT = "[A] EDIT FOR YOUR BUILD - PRIMORDIAL / COCOONED", "[A] EDIT FOR YOUR BUILD - PRIMORDIAL"
OLD_COC, NEW_COC = "[A] COCOONED - all", "SHOW ALL COCOONED ITEMS"
PRIMORDIAL_DATA = {**FULL, "uniques": FULL["uniques"] + [{**unique(7, "First One"), "is_primordial": True},
                                                         {**unique(8, "Cocooned Club"), "is_cocooned": True},
                                                         {**unique(9, "Cocooned Axe"), "is_cocooned": True}]}
OLD_GROUPS = [{"name": "PRIMORDIAL", "header": "--- PRIMORDIAL / COCOONED ---", "categories": ["primordial"], "rules": [{}]},
              {"name": "COCOONED", "categories": ["cocooned"], "rules": [{"label": "all", "color": 1}]}]
NEW_GROUPS = [{"name": "PRIMORDIAL", "header": "--- PRIMORDIAL ---", "categories": ["primordial"], "rules": [{}]}]


def primordial_config(groups, cocooned=True) -> dict:
    """FULL_CONFIG with these primordial groups; cocooned=False: no [starter] cocooned rule (as v0.3.2 had)."""
    starter = {**FULL_CONFIG["starter"], **({} if cocooned else {"cocooned": False})}
    idols_off = groups is NEW_GROUPS   # this version: the unique idols' show-all rule is off unless switched on
    base = [{**g, "rules": [{**g["rules"][0], "enabled": False}]} if idols_off and g["name"] == "UNIQUE IDOLS" else g
            for g in CONFIG["group"]]
    return {**FULL_CONFIG, "starter": starter, "group": base + groups}


def test_an_old_configs_cocooned_group_and_primordial_header_get_this_versions():
    assert upgrade_config(primordial_config(OLD_GROUPS)) == primordial_config(NEW_GROUPS)
    rules = make_template(primordial_config(NEW_GROUPS), PRIMORDIAL_DATA)["rules"]
    names = [r["name"] for r in rules]
    assert names[names.index("LEGENDARY") + 1] == NEW_COC and NEW_SEP in names and NEW_SLOT in names
    cocooned = lambda r: {u["id"] for c in r["conditions"] if c["type"] == "UniqueModifiersCondition" for u in c["uniques"]} & {8, 9}
    assert [r["name"] for r in rules if cocooned(r)] == [NEW_COC] and rules[names.index(NEW_COC)]["enabled"]


@pytest.mark.parametrize("was_on", [True, False])
def test_refresh_moves_the_old_cocooned_rule_below_legendary_and_keeps_a_filled_slot(was_on):
    old = build_starter(primordial_config(OLD_GROUPS, cocooned=False), PRIMORDIAL_DATA,
                        {"parts": ["legendary", "uniques", "hide_rest"]})["rules"]
    by = {r["name"]: r for r in old}
    assert NEW_COC not in by
    by[OLD_SLOT]["conditions"][1]["uniques"] = [{"id": 7, "rolls": []}]   # filled in-game
    by[OLD_SLOT]["enabled"] = True
    by[OLD_COC]["enabled"] = was_on
    rules = refresh_generated(primordial_config(NEW_GROUPS), PRIMORDIAL_DATA, old)["rules"]
    names = [r["name"] for r in rules]
    assert OLD_COC not in names and OLD_SLOT not in names and OLD_SEP not in names and NEW_SEP in names
    assert names[names.index("LEGENDARY") + 1] == NEW_COC and rules[names.index(NEW_COC)]["enabled"] == was_on
    assert rules[names.index(NEW_SLOT)]["conditions"][1]["uniques"] == [{"id": 7, "rolls": []}]
    assert refresh_generated(primordial_config(NEW_GROUPS), PRIMORDIAL_DATA, rules)["rules"] == rules
    kept = {r["name"] for r in refresh_generated(primordial_config(OLD_GROUPS, cocooned=False), PRIMORDIAL_DATA, old)["rules"]}
    assert {OLD_COC, OLD_SLOT, OLD_SEP} <= kept and not {NEW_COC, NEW_SLOT, NEW_SEP} & kept   # a config keeping them keeps them


def test_a_v032_template_update_moves_cocooned_and_keeps_a_filled_primordial_slot(tmp_path, monkeypatch):
    from lefilter import starter
    from lefilter.filterdoc import parse_filter
    path = tmp_path / "templates" / "New filter.xml"
    read = lambda: parse_filter(path.read_bytes().decode("utf-8-sig"))["rules"]
    monkeypatch.setattr(starter, "__version__", "0.3.2")
    starter.write_generated_template(path, make_template(primordial_config(OLD_GROUPS, cocooned=False), PRIMORDIAL_DATA))
    doc = parse_filter(path.read_bytes().decode("utf-8-sig"))
    by = {r["name"]: r for r in doc["rules"]}
    by[OLD_SLOT]["conditions"][1]["uniques"] = [{"id": 7, "rolls": []}]
    by[OLD_COC]["enabled"] = False                                          # the user's: off
    starter.write_template(path, doc, "0.3.2")
    monkeypatch.setattr(starter, "__version__", "0.3.3")
    res = starter.sync_template(path, upgrade_config(primordial_config(OLD_GROUPS)), PRIMORDIAL_DATA)
    rules = read()
    names = [r["name"] for r in rules]
    assert names == [r["name"] for r in make_template(primordial_config(NEW_GROUPS), PRIMORDIAL_DATA)["rules"]]
    assert not rules[names.index(NEW_COC)]["enabled"]                       # still off
    assert rules[names.index(NEW_SLOT)]["conditions"][1]["uniques"] == [{"id": 7, "rolls": []}]
    assert res["added"] == [NEW_COC] and res["dropped"] == [OLD_COC]


def test_the_unique_idols_show_all_rule_is_off_by_default_now():
    # unique idols are in the drop-rarity rules too: an untouched old config's show-all rule goes off
    group = {"name": "UNIQUE IDOLS", "categories": ["common"], "base_types": ["IDOLS"], "rules": [{"label": "show all"}]}
    assert upgrade_config({"group": [group]})["group"][0]["rules"] == [{"label": "show all", "enabled": False}]
    changed = {**group, "rules": [{"label": "show all", "color": 4}]}
    assert upgrade_config({"group": [changed]})["group"][0] == changed            # one the user changed stays theirs
    from lefilter.rules import released_defaults
    now = {**group, "rules": [{"label": "show all", "enabled": False}]}
    assert next(g for g in released_defaults({"group": [now]})["group"] if g["name"] == "UNIQUE IDOLS")["rules"] == group["rules"]
