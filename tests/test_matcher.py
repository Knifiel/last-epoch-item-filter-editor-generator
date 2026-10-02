from lefilter.filterdoc import new_rule
from lefilter.matcher import Context, evaluate, item_rarity

DATA = {
    "affixes": [{"id": 30, "name": "Increased Physical Damage", "prefix": True},
                {"id": 25, "name": "Added Health", "prefix": False},
                {"id": 13, "name": "Fire Resistance", "prefix": False}],
    "uniques": [{"id": 7, "name": "Some Unique"}],
    "bases": [{"type": "TWO_HANDED_SWORD", "subtypes": [{"id": 0, "name": "Bastard Sword", "level": 0, "class": 0},
                                                        {"id": 2, "name": "Imperial Warblade", "level": 24, "class": 0}]},
              {"type": "RELIC", "subtypes": [{"id": 3, "name": "Mage relic", "level": 10, "class": 2}]}],
}
CTX = Context(DATA)


def rule(*conditions, name="r", **fields):
    return new_rule(name, conditions=list(conditions), **fields)


def rarity(*r):
    return {"type": "RarityCondition", "rarity": list(r)}


def subtype(types, subs=()):
    return {"type": "SubTypeCondition", "types": list(types), "subtypes": list(subs)}


def affixes(ids, n=1, advanced=False, cmp="ANY", value=0, combined="ANY", combined_value=1):
    return {"type": "AffixCondition", "affixes": list(ids), "min_on_same_item": n, "advanced": advanced,
            "comparsion": cmp, "comparsion_value": value, "combined_comparsion": combined, "combined_value": combined_value}


def level(lo, hi):
    return {"type": "CharacterLevelCondition", "min": lo, "max": hi}


SWORD = {"type": "TWO_HANDED_SWORD", "subtype": 2, "rarity": "RARE", "affixes": [{"id": 30, "tier": 4}, {"id": 25, "tier": 2}]}


def first(rules, item=SWORD, lvl=25):
    return evaluate(rules, item, lvl, CTX)["index"]


def test_first_enabled_matching_rule_wins():
    rules = [rule(rarity("MAGIC")), rule(rarity("RARE"), enabled=False), rule(rarity("RARE")), rule()]
    assert first(rules) == 2


def test_no_match_is_none_and_conditionless_rule_matches_everything():
    assert first([rule(rarity("MAGIC"))]) is None
    assert first([rule(rarity("MAGIC")), rule(name="catch all", type="HIDE")]) == 1


def test_subtype_bases_only_count_with_a_single_type():
    assert first([rule(subtype(["TWO_HANDED_SWORD"], [0]))]) is None
    assert first([rule(subtype(["TWO_HANDED_SWORD"], [2]))]) == 0
    assert first([rule(subtype(["TWO_HANDED_SWORD", "RELIC"], [0]))]) == 0   # bases ignored with two types
    assert first([rule(subtype([]))]) is None


def test_affix_condition_counts_and_tiers():
    assert first([rule(affixes([30, 25], n=2))]) == 0
    assert first([rule(affixes([30, 13], n=2))]) is None
    assert first([rule(affixes([30, 25], n=1, advanced=True, cmp="MORE_OR_EQUAL", value=4))]) == 0
    assert first([rule(affixes([30, 25], n=2, advanced=True, cmp="MORE_OR_EQUAL", value=4))]) is None
    assert first([rule(affixes([30, 25], n=2, advanced=True, combined="MORE_OR_EQUAL", combined_value=7))]) is None
    assert first([rule(affixes([30, 25], n=2, advanced=True, combined="MORE_OR_EQUAL", combined_value=6))]) == 0
    assert first([rule(affixes([], n=2))]) == 0                                # empty list: any affix counts
    # every affix condition of a rule has to match
    assert first([rule(affixes([30]), affixes([13]))]) is None


def test_character_level_window():
    rules = [rule(level(0, 9), name="0-9"), rule(level(10, 19), name="10-19"), rule(level(20, 29), name="20-29")]
    assert first(rules, lvl=9) == 0 and first(rules, lvl=10) == 1 and first(rules, lvl=29) == 2
    assert first(rules, lvl=30) is None


def test_exalted_rarity_from_tier_six():
    assert item_rarity({"rarity": "RARE", "affixes": [{"id": 30, "tier": 6}]}) == "EXALTED"
    assert item_rarity({"rarity": "RARE", "affixes": [{"id": 30, "tier": 5}]}) == "RARE"
    assert item_rarity({"rarity": "UNIQUE", "affixes": [{"id": 30, "tier": 7}]}) == "UNIQUE"


def test_class_condition_needs_class_specific_item():
    relic = {"type": "RELIC", "subtype": 3, "rarity": "MAGIC", "affixes": []}
    cls = lambda *c: {"type": "ClassCondition", "classes": list(c)}
    assert first([rule(cls("Mage"))], item=relic) == 0
    assert first([rule(cls("Rogue"))], item=relic) is None
    assert first([rule(cls("Mage"))]) is None          # the sword isn't class-specific
    assert first([rule(cls())]) == 0


def test_unrecognised_condition_is_not_guessed():
    res = evaluate([rule({"type": "X", "raw": "<Condition />"}), rule(name="next")], SWORD, 1, CTX)
    assert res["results"][0]["matched"] is None and res["index"] == 1
