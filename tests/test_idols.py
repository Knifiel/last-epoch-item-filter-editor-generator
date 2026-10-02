import pytest

from lefilter.filterdoc import new_rule, parse_rule_blocks
from lefilter.filterxml import render_rule
from lefilter.idols import idol_kinds, parse_options, plan_idols, read_picks, shadowing_rules
from lefilter.matcher import Context, evaluate
from lefilter.rules import ConfigError
from lefilter.sections import doc_infos, place


def sub(sid, name, cls=0, drops=True, omen=False):
    return {"id": sid, "name": name, "level": 0, "drops": drops, "class": cls, "omen": omen}


def base(tid, type_name, name, subtypes):
    return {"id": tid, "type": type_name, "name": name, "category": "Idols", "weapon": False, "subtypes": subtypes}


BASES = [
    base(25, "IDOL_1x1_ETERRA", "Small Idol", [sub(0, "Small Eterran Idol"), sub(1, "Small Orobyss Idol", drops=False),
                                               sub(2, "Small Weaver Idol", drops=False)]),
    base(26, "IDOL_1x1_LAGON", "Minor Idol", [sub(0, "Minor Lagonian Idol"), sub(1, "Minor Weaver Idol", drops=False)]),
    base(27, "IDOL_2x1", "Humble Idol", [sub(0, "Humble Eterran Idol"), sub(1, "Humble Weaver Idol", drops=False)]),
    base(28, "IDOL_1x2", "Stout Idol", [sub(0, "Stout Lagonian Idol"), sub(1, "Stout Weaver Idol", drops=False)]),
    base(29, "IDOL_3x1", "Grand Idol", [sub(2, "Grand Solar Idol", cls=4), {**sub(7, "Heretical Grand Solar Idol", cls=4, drops=False), "heretical": True},
                                        sub(12, "Grand Iron Omen Idol", cls=4, omen=True), sub(1, "Grand Glass Idol", cls=2)]),
    base(30, "IDOL_1x3", "Large Idol", [sub(2, "Large Rahyeh Idol", cls=4)]),
    base(31, "IDOL_4x1", "Ornate Idol", [sub(2, "Ornate Solar Idol", cls=4)]),
    base(32, "IDOL_1x4", "Huge Idol", []),
    base(33, "IDOL_2x2", "Adorned Idol", [sub(2, "Adorned Rahyeh Idol", cls=4)]),
]


def affix(aid, name, rolls_on, cls=0, special=0, category="General Idols"):
    return {"id": aid, "name": name, "category": category, "header": "Idols", "class": cls, "special": special,
            "idol": True, "prefix": True, "level": 0, "rolls_on": list(rolls_on)}


AFFIXES = [
    affix(105, "Idol Health", (26, 30, 33), cls=29),           # NonSpecific | Mage | Sentinel | Acolyte
    affix(110, "Armor", (25, 29), cls=0),                      # no restriction
    affix(111, "Idol Fire Resistance", (25,), cls=19),         # NonSpecific | Primalist | Acolyte: not Sentinel
    affix(196, "Idol Sentinel Increased Armor", (29, 31), cls=8, category="Sentinel Idols"),
    affix(197, "Idol Sentinel Block Effectiveness", (30, 32, 33), cls=8, category="Sentinel Idols"),
    affix(174, "Frostbite Duration", (29,), cls=4, category="Mage Idols"),
    affix(840, "Crit Avoidance and Crit Chance", (25,), cls=1, special=5, category="Weaver Idols"),
    affix(1070, "All Resistances for you and your Minions", range(25, 34), special=6, category="Corrupted"),
    affix(900, "Enchanted thing", (29,), special=4, category="Enchanted Idols"),
    affix(30, "Increased Physical Damage", (16,), category="Damage Type"),
]
DATA = {"bases": BASES, "affixes": AFFIXES}
KINDS = {k.key: k for k in idol_kinds(DATA)}


def pool(key):
    return [(a["id"], a["group"]) for a in KINDS[key].pool]


def test_kinds_by_size_class_and_variant():
    assert list(KINDS) == ["IDOL_1x1_ETERRA", "IDOL_1x1_LAGON", "IDOL_2x1", "IDOL_1x2",
                           "IDOL_1x1_ETERRA/weaver", "IDOL_1x1_LAGON/weaver", "IDOL_2x1/weaver", "IDOL_1x2/weaver",
                           "IDOL_3x1/Mage", "IDOL_3x1/Sentinel", "IDOL_1x3/Sentinel", "IDOL_4x1/Sentinel",
                           "IDOL_2x2/Sentinel", "IDOL_3x1/Sentinel/omen"]
    small = KINDS["IDOL_1x1_ETERRA"]
    assert (small.width, small.height, small.subtypes, small.label) == (1, 1, [0], "1x1 Small")
    assert KINDS["IDOL_1x1_ETERRA/weaver"].subtypes == [2] and KINDS["IDOL_2x1/weaver"].subtypes == [1]
    assert KINDS["IDOL_3x1/Sentinel"].subtypes == [2]                  # no omen base...
    assert KINDS["IDOL_3x1/Sentinel"].heretical_subtypes == [7]        # ...its heretical version rides along
    assert KINDS["IDOL_3x1/Sentinel/omen"].heretical_subtypes == [] and KINDS["IDOL_3x1/Mage"].heretical_subtypes == []
    assert KINDS["IDOL_3x1/Sentinel/omen"].subtypes == [12]
    assert (KINDS["IDOL_1x3/Sentinel"].width, KINDS["IDOL_1x3/Sentinel"].height) == (1, 3)


def test_pools_follow_type_and_class_restrictions():
    assert pool("IDOL_1x1_ETERRA") == [(110, "General Idols"), (111, "General Idols"),
                                       (1070, "Corrupted (corrupted idols only)")]
    assert pool("IDOL_1x1_ETERRA/weaver") == [(110, "General Idols"), (111, "General Idols"), (840, "Weaver Idols"),
                                              (1070, "Corrupted (corrupted idols only)")]
    assert pool("IDOL_3x1/Sentinel") == [(110, "General Idols"), (196, "Sentinel Idols"),
                                         (1070, "Corrupted (corrupted idols only)")]
    assert [i for i, _ in pool("IDOL_3x1/Mage")] == [110, 174, 1070]
    # Omen: own size plus the 4x1 / 1x4 / 2x2 affixes
    assert sorted(i for i, _ in pool("IDOL_3x1/Sentinel/omen")) == [105, 110, 196, 197, 1070]


def test_plan_rules_per_picked_kind():
    opts = parse_options({"picks": {"IDOL_1x3/Sentinel": {"affixes": [197, 105, 999], "min": 2},
                                    "IDOL_1x1_ETERRA": {"affixes": [111], "min": 2},
                                    "IDOL_2x1": {"affixes": []}},
                          "hide_others": True})
    plan = plan_idols(opts, list(KINDS.values()))
    header, small, large, hide = plan.rules
    assert header.is_separator and header.name == "[I] ------- IDOLS (auto) -------"
    assert small.item_types == ["IDOL_1x1_ETERRA"] and small.sub_types == [0] and small.affix_min == 1   # only 1 pick
    assert small.spec.color == 15 and not small.spec.emphasized
    assert large.affix_ids == [197, 105] and large.affix_min == 2 and large.sub_types == [2] and large.spec.emphasized
    assert large.name == "[I] 1x3 Sentinel idol - 2+ of 2 wanted affixes"
    assert hide.spec.action == "hide" and hide.rarity == "NORMAL MAGIC RARE EXALTED" and len(hide.item_types) == 9
    assert any("can't roll" in w for w in plan.warnings)


def test_picks_read_back_from_generated_rules():
    opts = parse_options({"picks": {"IDOL_3x1/Sentinel/omen": {"affixes": [196, 197], "min": 1}}, "hide_others": True})
    rules = parse_rule_blocks([render_rule(r) for r in plan_idols(opts, list(KINDS.values())).rules])
    got = read_picks([new_rule("mine")] + rules, "[I] ", list(KINDS.values()))
    assert got == {"found": True, "picks": {"IDOL_3x1/Sentinel/omen": {"affixes": [196, 197], "min": 1}},
                   "hide_others": True}
    assert read_picks([new_rule("mine")], "[I] ", list(KINDS.values()))["found"] is False


def test_heretical_versions_share_their_class_idol_rule():
    opts = parse_options({"picks": {"IDOL_3x1/Sentinel": {"affixes": [196, 110], "min": 2}}, "hide_others": True})
    plan = plan_idols(opts, list(KINDS.values()))
    assert len(plan.rules) == 3 and plan.rules[1].sub_types == [2, 7]      # header, 3x1 Sentinel (+ heretical), hide
    rules = parse_rule_blocks([render_rule(r) for r in plan.rules])
    ctx = Context({**DATA, "uniques": []})
    wanted = [{"id": 196, "tier": 3}, {"id": 110, "tier": 3}]
    for subtype in (2, 7):   # normal and heretical
        idol = {"type": "IDOL_3x1", "subtype": subtype, "rarity": "MAGIC", "affixes": wanted}
        assert rules[evaluate(rules, idol, 50, ctx)["index"]]["name"].startswith("[I] 3x1 Sentinel idol")
    # picks read back from rules with or without the heretical base (older sections)
    assert read_picks(rules, "[I] ", list(KINDS.values()))["picks"] == {"IDOL_3x1/Sentinel": {"affixes": [196, 110], "min": 2}}
    old = [{**r, "conditions": [{**c, "subtypes": [2]} if c["type"] == "SubTypeCondition" else c for c in r["conditions"]]}
           for r in rules]
    assert "IDOL_3x1/Sentinel" in read_picks(old, "[I] ", list(KINDS.values()))["picks"]


def test_section_goes_on_top_without_idol_separator_and_warns_about_shadowing():
    show_all = new_rule("all idols", conditions=[{"type": "SubTypeCondition", "types": ["IDOL_2x2"], "subtypes": []}])
    current = [new_rule("a"), show_all]
    merged, removed, at = place(current, doc_infos(current), ["[I] x"], "[I] ", section="IDOL", fallback="top")
    assert merged[0] == "[I] x" and at == 0 and removed == 0
    assert shadowing_rules(current, 2) == ["#2 all idols"]
    sep = new_rule("---- IDOL RULES ----")
    current = [new_rule("a"), sep, new_rule("b")]
    merged, _, at = place(current, doc_infos(current), ["[I] x"], "[I] ", section="IDOL", fallback="top")
    assert at == 2 and merged[2] == "[I] x"


def test_option_errors():
    with pytest.raises(ConfigError, match="min must be 1 or 2"):
        parse_options({"picks": {"IDOL_2x1": {"affixes": [1], "min": 3}}})
    with pytest.raises(ConfigError, match="unknown key"):
        parse_options({"pick": {}})
