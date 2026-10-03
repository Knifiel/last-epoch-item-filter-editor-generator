import pytest

from lefilter import bis
from lefilter.filterdoc import new_rule
from lefilter.gamedata import TYPE_IDS
from lefilter.rules import ConfigError


def sub(sid, name, cls=0, drops=True):
    return {"id": sid, "name": name, "level": 0, "drops": drops, "class": cls}


def base(t, name, subs):
    return {"id": TYPE_IDS[t], "type": t, "name": name, "category": "", "weapon": False, "subtypes": subs}


def affix(aid, name, types, category="c", cls=0):
    return {"id": aid, "name": name, "category": category, "header": "", "class": cls, "special": 0, "idol": False,
            "prefix": True, "level": 0, "rolls_on": [TYPE_IDS[t] for t in types]}


DATA = {
    "bases": [base("ONE_HANDED_AXE", "One-Handed Axe", [sub(0, "Hatchet"), sub(3, "Tribal Axe")]),
              base("ONE_HANDED_SWORD", "One-Handed Sword", [sub(1, "Gladius"), sub(5, "Rune Sword", cls=4)]),
              base("SHIELD", "Shield", [sub(0, "Targe")]),
              base("HELMET", "Helmet", [sub(0, "Iron Helmet"), sub(2, "Gladiator Helm")]),
              base("RELIC", "Relic", [sub(3, "Copper Chalice"), sub(44, "Argent Crest", cls=4), sub(36, "Spirit Catcher", cls=1)])],
    "affixes": [affix(30, "Increased Physical Damage", ["ONE_HANDED_AXE", "ONE_HANDED_SWORD", "RELIC"]),
                affix(63, "Added Melee Physical Damage", ["ONE_HANDED_AXE"]),
                affix(25, "Added Health", ["HELMET", "SHIELD", "RELIC"]),
                affix(37, "Physical Resistance", ["HELMET", "SHIELD"]),
                affix(603, "Level of Smite", ["RELIC"], category="Sentinel", cls=8)],
}


def names(rules):
    return [r["name"] for r in rules]


def cond(rule, ctype):
    return next((c for c in rule["conditions"] if c["type"] == ctype), None)


def test_weapons_span_types_one_rule_per_type_and_tier():
    opts = bis.parse_options({"slots": {"weapons": {"bases": {"ONE_HANDED_AXE": [3], "ONE_HANDED_SWORD": []},
                                                    "affixes": [30, 63], "good": {"fp": 20}}}})
    plan = bis.plan_bis(opts, DATA)
    assert names(plan.rules) == ["BIS - One-Handed Axe: 2+ T7", "BIS - One-Handed Sword: 1+ T7",
                                 "BIS - One-Handed Axe (good): 1+ T6, FP 20+", "BIS - One-Handed Sword (good): 1+ T6, FP 20+"]
    axe, sword, axe_good, _ = plan.rules
    assert cond(axe, "SubTypeCondition") == {"type": "SubTypeCondition", "types": ["ONE_HANDED_AXE"], "subtypes": [3]}
    assert cond(sword, "SubTypeCondition")["subtypes"] == []                     # none picked: every base
    aff = cond(axe, "AffixCondition")
    assert aff["affixes"] == [30, 63] and aff["min_on_same_item"] == 2 and aff["advanced"]
    assert (aff["comparsion"], aff["comparsion_value"]) == ("MORE_OR_EQUAL", 7)
    assert cond(sword, "AffixCondition")["affixes"] == [30]                      # what rolls on swords
    assert cond(axe, "PotentialCondition") is None and cond(axe_good, "PotentialCondition")["fp_min"] == 20
    assert axe["color"] == 9 and axe["emphasized"] and axe["beam_size"] == "LARGEST" and axe["beam_override"]
    assert not axe_good["emphasized"] and not axe_good["beam_override"]
    assert cond(axe, "RarityCondition")["rarity"] == ["MAGIC", "RARE", "EXALTED"]


def test_single_slots_bases_only_class_filter_and_warnings():
    opts = bis.parse_options({"character_class": "Sentinel", "slots": {
        "helmet": {"bases": {"HELMET": [2]}},                                 # bases only: one rule, no affixes
        "relic": {"bases": {"RELIC": [36, 44]}, "affixes": [603, 30], "good": {"enabled": False}},
        "offhand": {"affixes": [25]},                                          # no item type picked
        "body": {}}})
    plan = bis.plan_bis(opts, DATA)
    assert names(plan.rules) == ["BIS - Helmet: bases", "BIS - Relic: 2+ T7"]
    assert cond(plan.rules[0], "AffixCondition") is None and cond(plan.rules[0], "SubTypeCondition")["subtypes"] == [2]
    assert cond(plan.rules[1], "SubTypeCondition")["subtypes"] == [44]        # Spirit Catcher is a Primalist relic
    assert plan.warnings == ["Off-hand: pick the item types (and bases) the affixes are for"]
    mage = bis.plan_bis(bis.parse_options({"character_class": "Mage", "slots": {"relic": {"bases": {"RELIC": [36, 44]}}}}), DATA)
    assert mage.rules == [] and "none of the picked bases is for Mage" in mage.warnings[0]
    anyone = bis.plan_bis(bis.parse_options({"slots": {"relic": {"bases": {"RELIC": [36, 44]}}}}), DATA)
    assert cond(anyone.rules[0], "SubTypeCondition")["subtypes"] == [36, 44] and not anyone.warnings   # no class: any class's
    nothing = bis.plan_bis(bis.parse_options({"slots": {"helmet": {"affixes": [63]}}}), DATA)
    assert nothing.rules == [] and nothing.warnings == ["Helmet: none of the picked affixes roll on it; no rule"]


def test_options_are_checked():
    with pytest.raises(ConfigError, match="unknown BiS slot"):
        bis.parse_options({"slots": {"pants": {}}})
    with pytest.raises(ConfigError, match="bases must map"):
        bis.parse_options({"slots": {"helmet": {"bases": {"RING": []}}}})
    with pytest.raises(ConfigError, match="tier must be 1-8"):
        bis.parse_options({"slots": {"helmet": {"bis": {"tier": 9}}}})
    assert bis.parse_options({"slots": {"helmet": {"good": {"fp": ""}}}}).slots["helmet"]["good"]["fp"] is None


def test_place_replaces_the_bis_rules_and_reads_them_back():
    opts = bis.parse_options({"slots": {"weapons": {"bases": {"ONE_HANDED_AXE": [3]}, "affixes": [30, 63],
                                                    "bis": {"min": 3, "tier": 6, "fp": 30}},
                                        "helmet": {"bases": {"HELMET": [2]}, "affixes": [25, 37]}}})
    plan = bis.plan_bis(opts, DATA)
    template = [new_rule("TOP"), new_rule("------ BIS ITEMS (pick the bases) ------", enabled=False),
                new_rule("BIS - Helmet (pick bases)", enabled=False), new_rule("BIS - Weapon (pick type & bases)", enabled=False),
                new_rule("------ EXALTED & LEGENDARY ------", enabled=False), new_rule("ALL T8")]
    merged, removed, at = bis.place_bis(template, plan.rules)
    assert removed == 2 and at == 2 and names(merged)[2:2 + len(plan.rules)] == names(plan.rules)
    assert names(merged)[-2:] == ["------ EXALTED & LEGENDARY ------", "ALL T8"]
    again, removed, _ = bis.place_bis(merged, plan.rules[:1])                  # applying again replaces in place
    assert removed == len(plan.rules) and names(again) == ["TOP", "------ BIS ITEMS (pick the bases) ------",
                                                          plan.rules[0]["name"], "------ EXALTED & LEGENDARY ------", "ALL T8"]
    fresh, _, _ = bis.place_bis([new_rule("ALL T8")], plan.rules[:1])           # no BiS section: a header on top
    assert names(fresh) == [bis.HEADER, plan.rules[0]["name"], "ALL T8"]
    got = bis.read_picks(merged)
    assert got["found"] and got["rarity"] == ["MAGIC", "RARE", "EXALTED"]
    assert got["slots"]["weapons"]["bases"] == {"ONE_HANDED_AXE": [3]} and got["slots"]["weapons"]["affixes"] == [30, 63]
    assert got["slots"]["weapons"]["bis"] == {"enabled": True, "min": 2, "tier": 6, "fp": 30}   # min capped at the 2 picked
    assert got["slots"]["helmet"]["good"] == {"enabled": True, "min": 1, "tier": 6, "fp": None}
    assert bis.plan_bis(bis.parse_options({"slots": got["slots"], "rarity": got["rarity"]}), DATA).rules == plan.rules
    assert not bis.read_picks(template)["found"]                                 # the template's placeholders


def test_new_adds_the_bis_section_only_when_asked():
    from tests.test_starter import BUILD, FULL, FULL_CONFIG   # noqa: F401 - the starter fixtures
    from lefilter.starter import make_template, new_from_template
    data = {**FULL, "bases": FULL["bases"] + DATA["bases"][:1]}
    template = make_template(FULL_CONFIG, data)
    blank = new_from_template(FULL_CONFIG, data, template, {})
    assert "BIS - Weapon (pick type & bases)" in names(blank["rules"])
    doc = new_from_template(FULL_CONFIG, data, template, {"character_class": "Sentinel",
                                                          "bis": {"slots": {"helmet": {"affixes": [25]}}}})
    n = names(doc["rules"])
    assert "BIS - Helmet: 1+ T7" in n and "BIS - Weapon (pick type & bases)" not in n
    assert n.index("BIS - Helmet: 1+ T7") == n.index("------ BIS ITEMS (pick the bases) ------") + 1


def test_read_back_keeps_the_strictest_minimum_across_types():
    opts = bis.parse_options({"slots": {"weapons": {"bases": {"ONE_HANDED_AXE": [], "ONE_HANDED_SWORD": []},
                                                    "affixes": [30, 63]}}})
    plan = bis.plan_bis(opts, DATA)
    assert names(plan.rules)[:2] == ["BIS - One-Handed Axe: 2+ T7", "BIS - One-Handed Sword: 1+ T7"]   # capped per type
    got = bis.read_picks(plan.rules, DATA)
    assert got["slots"]["weapons"]["bis"]["min"] == 2 and got["slots"]["weapons"]["good"]["min"] == 1
    assert bis.plan_bis(bis.parse_options({"slots": got["slots"]}), DATA).rules == plan.rules


def test_a_class_lists_its_bases_when_none_are_ticked_and_reads_back():
    opts = bis.parse_options({"character_class": "Sentinel", "slots": {"relic": {"affixes": [30]},
                                                                        "helmet": {"affixes": [25]}}})
    plan = bis.plan_bis(opts, DATA)
    relic = next(r for r in plan.rules if "Relic" in r["name"])
    helmet = next(r for r in plan.rules if "Helmet" in r["name"])
    assert cond(relic, "SubTypeCondition")["subtypes"] == [3, 44]     # not the Primalist relic
    assert cond(helmet, "SubTypeCondition")["subtypes"] == []         # no class helmets: every base
    got = bis.read_picks(plan.rules, DATA)
    assert got["character_class"] == "Sentinel" and got["slots"]["relic"]["bases"] == {}
    assert bis.read_picks(plan.rules)["character_class"] == ""        # without the data: unknown
    hide = [new_rule("[A] Hide non-Mage class non-legendary items", type="HIDE"),
            new_rule("[A] Hide non-Sentinel class non-legendary items", type="HIDE", enabled=False)]
    plain = bis.plan_bis(bis.parse_options({"slots": {"helmet": {"affixes": [25]}}}), DATA).rules
    assert bis.read_picks(hide + plain, DATA)["character_class"] == "Mage"   # from the class hide rule that's on
    one = new_rule("[A] Hide items of other classes", type="HIDE",
                   conditions=[{"type": "ClassCondition", "classes": ["Primalist", "Sentinel", "Acolyte", "Rogue"]}])
    assert bis.read_picks([one] + plain, DATA)["character_class"] == "Mage"  # the class it leaves out
    assert bis.read_picks([{**one, "enabled": False}] + plain, DATA)["character_class"] == ""


def test_a_class_without_bases_of_a_type_makes_no_rule_for_it():
    data = {**DATA, "bases": DATA["bases"] + [base("BOW", "Bow", [sub(0, "Shortbow", cls=16), sub(1, "Birch Bow", cls=16)])],
            "affixes": DATA["affixes"] + [affix(433, "Added Bow Physical Damage", ["BOW"])]}
    plan = bis.plan_bis(bis.parse_options({"character_class": "Sentinel",
                                            "slots": {"weapons": {"bases": {"BOW": []}, "affixes": [433]}}}), data)
    assert plan.rules == [] and plan.warnings == ["Bow: no Sentinel bases; no rule"]
    rogue = bis.plan_bis(bis.parse_options({"character_class": "Rogue",
                                            "slots": {"weapons": {"bases": {"BOW": []}, "affixes": [433]}}}), data)
    assert cond(rogue.rules[0], "SubTypeCondition")["subtypes"] == []   # every bow is the Rogue's


def test_other_class_affixes_and_unknown_bases_are_left_out():
    plan = bis.plan_bis(bis.parse_options({"character_class": "Mage", "slots": {"relic": {"affixes": [603, 30]}}}), DATA)
    assert cond(plan.rules[0], "AffixCondition")["affixes"] == [30]  # Level of Smite is a Sentinel affix
    assert "Relic: 1 picked affixes are for another class; left out" in plan.warnings
    gone = bis.plan_bis(bis.parse_options({"slots": {"helmet": {"bases": {"HELMET": [999]}, "affixes": [25]}}}), DATA)
    assert gone.rules == [] and gone.warnings == ["Helmet: 1 picked bases aren't in this game version; left out"]
