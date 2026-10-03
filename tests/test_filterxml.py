import xml.etree.ElementTree as ET

import pytest

from lefilter.filterxml import (MAX_RULES, BaseFilter, FilterHeader, assemble, merge, read_filter,
                                render_rule, write_filter)
from lefilter.rules import Rule, RuleSpec, separator

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"

# Element order of a <Rule> as written by the game (lootFilterVersion 9).
GAME_RULE_ORDER = ["type", "conditions", "recolor", "color", "isEnabled", "levelDependent_deprecated",
                   "minLvl_deprecated", "maxLvl_deprecated", "emphasized", "nameOverride", "SoundId",
                   "MapIconId", "BeamOverride", "BeamSizeOverride", "BeamColorOverride", "Order"]
GAME_POTENTIAL_ORDER = ["MinLegendaryPotential", "MaxLegendaryPotential", "MinWeaversWill", "MaxWeaversWill",
                        "MinWeaversTouch", "MaxWeaversTouch", "MinForgingPotential", "MaxForgingPotential"]


def rule(name, ids=(1, 2), rarity="UNIQUE", **spec):
    return Rule(name=name, group="g", spec=RuleSpec(**spec), unique_ids=None if ids is None else list(ids),
                rarity=rarity)


def parse(text):
    return ET.fromstring(text)


def test_rule_layout_matches_game():
    text = assemble(FilterHeader(name="F"), [render_rule(rule("[A] R & D - 1LP+", lp_min=1, color=6, emphasized=True))])
    r = parse(text).find("rules/Rule")
    assert [c.tag for c in r] == GAME_RULE_ORDER
    conditions = {c.get(XSI): c for c in r.find("conditions")}
    assert list(conditions) == ["RarityCondition", "UniqueModifiersCondition", "PotentialCondition"]
    assert [c.tag for c in conditions["PotentialCondition"]] == GAME_POTENTIAL_ORDER
    assert [u.find("UniqueId").text for u in conditions["UniqueModifiersCondition"]] == ["1", "2"]
    assert r.find("nameOverride").text == "[A] R & D - 1LP+"
    assert r.find("recolor").text == "true" and r.find("emphasized").text == "true"


def test_rule_without_potential_or_ids():
    r = parse(assemble(FilterHeader(name="F"), [render_rule(rule("all", ids=None, action="hide"))])).find("rules/Rule")
    assert r.find("type").text == "HIDE"
    assert [c.get(XSI) for c in r.find("conditions")] == ["RarityCondition"]
    assert r.find("recolor").text == "false"


def test_rules_are_stored_bottom_up_with_order_zero_on_top():
    blocks = [render_rule(rule(n)) for n in ("top", "middle", "bottom")]
    rules = parse(assemble(FilterHeader(name="F"), blocks)).findall("rules/Rule")
    assert [(r.find("nameOverride").text, r.find("Order").text) for r in rules] == [
        ("bottom", "2"), ("middle", "1"), ("top", "0")]


def test_rule_limit():
    with pytest.raises(ValueError, match="200"):
        assemble(FilterHeader(name="F"), [render_rule(rule("r"))] * (MAX_RULES + 1))


def test_written_file_matches_game_encoding(tmp_path):
    path = tmp_path / "f.xml"
    write_filter(path, assemble(FilterHeader(name="F"), [render_rule(rule("r"))]))
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert not raw.endswith(b"\n")


def test_read_and_merge_round_trip(tmp_path):
    base_blocks = [render_rule(rule(n)) for n in ("keep top", "UNIQUES - OLD", "[A] stale", "keep bottom")]
    path = tmp_path / "base.xml"
    write_filter(path, assemble(FilterHeader(name="Base", icon=3, description="mine"), base_blocks))

    base = read_filter(path)
    assert base.header.name == "Base" and base.header.icon == 3
    assert [BaseFilter.rule_name(b) for b in base.blocks] == ["keep top", "UNIQUES - OLD", "[A] stale", "keep bottom"]

    new = [render_rule(rule("[A] new 1")), render_rule(rule("[A] new 2"))]
    result = merge(base, new, prefix="[A] ", drop=[r"^UNIQUES - "])
    assert result.removed == ["UNIQUES - OLD", "[A] stale"]
    assert [BaseFilter.rule_name(b) for b in result.blocks] == ["keep top", "[A] new 1", "[A] new 2", "keep bottom"]


def test_merge_without_removals_uses_after_or_top(tmp_path):
    path = tmp_path / "base.xml"
    write_filter(path, assemble(FilterHeader(name="Base"), [render_rule(rule(n)) for n in ("a", "--- UNIQUES ---", "b")]))
    base = read_filter(path)
    new = [render_rule(rule("[A] x"))]
    names = lambda r: [BaseFilter.rule_name(b) for b in r.blocks]
    assert names(merge(base, new, "[A] ", [], after="UNIQUES")) == ["a", "--- UNIQUES ---", "[A] x", "b"]
    assert names(merge(base, new, "[A] ", [])) == ["[A] x", "a", "--- UNIQUES ---", "b"]


def test_keep_above_moves_own_rules_directly_above_generated_block(tmp_path):
    path = tmp_path / "base.xml"
    names_in = ("head", "UNIQUES - OLD", "idols", "EDIT FOR YOUR BUILD - WW", "tail")
    write_filter(path, assemble(FilterHeader(name="Base"), [render_rule(rule(n)) for n in names_in]))
    result = merge(read_filter(path), [render_rule(rule("[A] x"))], "[A] ", [r"^UNIQUES - "],
                   keep_above=[r"^EDIT FOR YOUR BUILD"])
    assert [BaseFilter.rule_name(b) for b in result.blocks] == ["head", "EDIT FOR YOUR BUILD - WW", "[A] x", "idols", "tail"]
    assert result.moved_above == ["EDIT FOR YOUR BUILD - WW"]
    assert result.insert_at == 2


def test_old_filter_version_is_rejected(tmp_path):
    path = tmp_path / "old.xml"
    path.write_text('<ItemFilter><name>x</name><lootFilterVersion>2</lootFilterVersion><rules /></ItemFilter>')
    with pytest.raises(ValueError, match="lootFilterVersion 2"):
        read_filter(path)
    path.write_text('<ItemFilter><name>x</name><lootFilterVersion>0</lootFilterVersion><rules /></ItemFilter>')
    assert read_filter(path).header.name == "x"          # made by the game itself: current layout


def test_separator_renders_without_conditions():
    r = parse(assemble(FilterHeader(name="F"), [render_rule(separator("--- X ---"))])).find("rules/Rule")
    assert list(r.find("conditions")) == [] and r.find("isEnabled").text == "false"
    assert "<conditions />" in render_rule(separator("--- X ---"))


def write_base(tmp_path, blocks):
    path = tmp_path / "base.xml"
    write_filter(path, assemble(FilterHeader(name="Base"), blocks))
    return read_filter(path)


def test_keep_whitelist_with_sections_separators_and_matchers(tmp_path):
    blocks = [
        render_rule(separator("------ EXALTED ------")),
        render_rule(rule("Double T7", ids=None, rarity=None, lp_min=1)),        # blanket (no SubType)
        render_rule(rule("Wanted Exalted Affixes", ids=None, rarity=None, lp_min=1)),
        render_rule(separator("------ IDOLS ------")),
        render_rule(rule("Idol rule", ids=None, rarity=None, lp_min=1)),
        render_rule(separator("------ UNIQUE ITEM RULES ------")),
        render_rule(rule("", ids=None, rarity="LEGENDARY", lp_min=1)),
        render_rule(rule("UNIQUES - COMMON - 1LP+")),
        render_rule(separator("------ LEVELING ------")),
        render_rule(rule("Leveling gear", ids=None, rarity="RARE", lp_min=1)),
        render_rule(rule("", ids=None, rarity=None, action="hide")),             # catch-all
    ]
    base = write_base(tmp_path, blocks)
    keep = [{"rarity": "LEGENDARY"}, {"name": "^Double T7$", "blanket": True}, {"section": "LEVELING"}]
    result = merge(base, [render_rule(rule("[A] gen"))], "[A] ", [r"^UNIQUES - "], keep=keep)
    names = [BaseFilter.rule_name(b) for b in result.blocks]
    assert names == ["------ EXALTED ------", "Double T7", "------ UNIQUE ITEM RULES ------", "",
                     "[A] gen", "------ LEVELING ------", "Leveling gear", ""]
    assert result.left_out == ["Wanted Exalted Affixes", "------ IDOLS ------", "Idol rule"]


def test_blanket_matcher_rejects_item_type_rules():
    from lefilter.filterxml import RuleInfo, keep_matcher
    m = keep_matcher({"name": "^Double T7", "blanket": True})
    assert m(RuleInfo("Double T7", True, ["AffixCondition"], set()))
    assert not m(RuleInfo("Double T7", True, ["SubTypeCondition", "AffixCondition"], set()))
    with pytest.raises(ValueError, match="unknown key"):
        keep_matcher({"nme": "x"})


def test_empty_uniques_condition_for_build_slots():
    block = render_rule(rule("EDIT FOR YOUR BUILD - X", ids=[], enabled=False, color=3))
    assert '<Condition i:type="UniqueModifiersCondition" />' in block
    conditions = [c.get(XSI) for c in parse(assemble(FilterHeader(name="F"), [block])).find("rules/Rule/conditions")]
    assert conditions == ["RarityCondition", "UniqueModifiersCondition"]


# Element order of an AffixCondition as written by the game.
GAME_AFFIX_ORDER = ["affixes", "comparsion", "comparsionValue", "minOnTheSameItem", "combinedComparsion",
                    "combinedComparsionValue", "advanced"]


def affix_rule(name, ids=(698, 1111)):
    return Rule(name=name, group="a", spec=RuleSpec(emphasized=True), unique_ids=None, rarity=None,
                affix_ids=list(ids))


def test_affix_rule_layout_matches_game():
    r = parse(assemble(FilterHeader(name="F"), [render_rule(affix_rule("[A] ALWAYS"))])).find("rules/Rule")
    (cond,) = r.find("conditions")
    assert cond.get(XSI) == "AffixCondition"
    assert [c.tag for c in cond] == GAME_AFFIX_ORDER
    assert [i.text for i in cond.find("affixes")] == ["698", "1111"]
    assert cond.find("comparsion").text == "ANY" and cond.find("minOnTheSameItem").text == "1"
    assert not affix_rule("x").is_separator


def test_top_rules_go_first_and_never_anchor_the_block(tmp_path):
    # A previous template as base: its old top rule comes first, then sections with old [A] rules.
    base = write_base(tmp_path, [
        render_rule(affix_rule("[A] ALWAYS")),
        render_rule(rule("Double T7", ids=None, rarity=None, lp_min=1)),
        render_rule(rule("[A] old unique rule")),
        render_rule(rule("leveling", ids=None, rarity="RARE")),
    ])
    result = merge(base, [render_rule(rule("[A] new unique rule"))], "[A] ", [],
                   top=[render_rule(affix_rule("[A] ALWAYS"))])
    assert [BaseFilter.rule_name(b) for b in result.blocks] == [
        "[A] ALWAYS", "Double T7", "[A] new unique rule", "leveling"]


def test_class_condition_renders_like_the_game():
    from lefilter.filterdoc import parse_rule_blocks
    block = render_rule(Rule(name="[A] Hide non-Sentinel class non-legendary items", group="c",
                             spec=RuleSpec(action="hide", enabled=False), unique_ids=None, rarity="NORMAL MAGIC RARE",
                             classes=["Primalist", "Mage", "Acolyte", "Rogue"]))
    assert "<req>Primalist Mage Acolyte Rogue</req>" in block
    (r,) = parse_rule_blocks([block])
    assert r["conditions"] == [{"type": "ClassCondition", "classes": ["Primalist", "Mage", "Acolyte", "Rogue"]},
                               {"type": "RarityCondition", "rarity": ["NORMAL", "MAGIC", "RARE"]}]
    assert r["type"] == "HIDE" and not r["enabled"]


def test_elsewhere_rules_never_anchor_the_block(tmp_path):
    base = write_base(tmp_path, [render_rule(rule("[A] Hide non-Mage")), render_rule(separator("---- U ----")),
                                 render_rule(rule("[A] old"))])
    result = merge(base, [render_rule(rule("[A] new"))], "[A] ", [], elsewhere=[render_rule(rule("[A] Hide non-Mage"))])
    assert [BaseFilter.rule_name(b) for b in result.blocks] == ["---- U ----", "[A] new"]
