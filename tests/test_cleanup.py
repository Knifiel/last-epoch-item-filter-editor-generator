from lefilter.cleanup import remove_common_uniques, remove_leveling, remove_separators
from lefilter.filterdoc import new_rule, parse_rule_blocks
from lefilter.filterxml import render_rule
from lefilter.rules import plan_rules

THRESHOLDS = {"uncommon": 0.25, "rare": 0.5, "very_rare": 0.75, "extremely_rare": 0.95}


def unique(uid, lpl, reroll=0.0, drops=True):
    return {"id": uid, "name": f"U{uid}", "internal_name": f"U{uid}", "lpl": lpl, "level": lpl, "reroll_chance": reroll,
            "can_drop_randomly": drops, "weavers_will": False, "is_set": False, "is_primordial": False,
            "is_cocooned": False, "hidden": False, "base_type": 21, "base_type_name": "Ring"}


UNIQUES = [unique(1, 10), unique(2, 45), unique(3, 70), unique(4, 20, reroll=0.3), unique(5, 20, reroll=0.6),
           unique(6, 20, drops=False)]
LP = [{"lp_min": 2}, {"lp_min": 1}, {"label": "0LP+", "enabled": False}]
CONFIG = {
    "filter": {"rule_prefix": "[A] "},
    "rarity": THRESHOLDS,
    "build_slots": {"add": True, "name": "EDIT FOR YOUR BUILD - {section}"},
    "group": [{"name": "ANY UNIQUE", "header": "--- UNIQUES ---", "build_slot": False,
               "categories": ["common", "uncommon", "rare", "special"], "rules": [{"lp_min": 3}]},
              {"name": "RARE", "header": "--- RANDOM DROPS ---", "categories": ["rare"], "rules": LP},
              {"name": "UNCOMMON LPL 0-59", "categories": ["uncommon"], "lpl_max": 59, "rules": LP},
              {"name": "COMMON LPL 60+", "categories": ["common"], "lpl_min": 60, "rules": LP},
              {"name": "COMMON LPL 0-59", "categories": ["common"], "lpl_max": 59, "rules": LP},
              {"name": "SPECIAL", "header": "--- NON-RANDOM ---", "categories": ["special"], "rules": LP}],
}


def doc_rules():
    return parse_rule_blocks([render_rule(r) for r in plan_rules(CONFIG, UNIQUES).rules])


def level(lo, hi):
    return {"type": "CharacterLevelCondition", "min": lo, "max": hi}


def test_separators_are_switched_off_rules_without_conditions():
    rules = [new_rule("---- A ----", enabled=False), new_rule("show all"), new_rule("x", conditions=[level(0, 9)]),
             new_rule("", enabled=False, type="HIDE"), new_rule("hide rest", type="HIDE")]
    kept, removed = remove_separators(rules)
    assert [r["name"] for r in kept] == ["show all", "x", "hide rest"]   # enabled catch-alls stay
    assert removed == ["---- A ----", "(unnamed)"]


def test_leveling_removes_the_section_and_rules_off_before_the_cap():
    rules = [new_rule("top"), new_rule("---- LEVELING ----", enabled=False),
             new_rule("till 25", conditions=[level(0, 24)]), new_rule("[L] header", enabled=False),
             new_rule("[L] Ring good bases 0-59", conditions=[level(0, 59)]),
             new_rule("---- LATE ----", enabled=False), new_rule("off at 80", conditions=[level(0, 79)]),
             new_rule("hide rest", type="HIDE")]
    kept, removed = remove_leveling(rules, "[L] ", 60)
    # the emptied LEVELING heading goes too; a bottom catch-all doesn't keep a section alive
    assert [r["name"] for r in kept] == ["top", "---- LATE ----", "off at 80", "hide rest"]
    assert removed == ["---- LEVELING ----", "till 25", "[L] header", "[L] Ring good bases 0-59"]


def test_common_uniques_low_lp_rules_go_build_slots_and_others_stay():
    rules = doc_rules()
    rules[-1]["conditions"][1]["uniques"] = [{"id": 1, "rolls": []}]   # filled the NON-RANDOM build slot in-game
    rules.append(new_rule("my commons", conditions=[{"type": "UniqueModifiersCondition", "uniques": [{"id": 1, "rolls": []}]}]))
    kept, removed = remove_common_uniques(rules, CONFIG, UNIQUES)
    assert removed == ["[A] UNCOMMON LPL 0-59 - 2LP+", "[A] UNCOMMON LPL 0-59 - 1LP+", "[A] UNCOMMON LPL 0-59 - 0LP+",
                       "[A] COMMON LPL 0-59 - 2LP+", "[A] COMMON LPL 0-59 - 1LP+", "[A] COMMON LPL 0-59 - 0LP+"]
    names = [r["name"] for r in kept]
    assert "[A] ANY UNIQUE - 3LP+" in names and "[A] COMMON LPL 60+ - 1LP+" in names and "[A] RARE - 0LP+" in names
    assert "[A] SPECIAL - 0LP+" in names                                  # non-random (boss) uniques stay
    assert "[A] EDIT FOR YOUR BUILD - NON-RANDOM" in names and "my commons" in names   # hand-picked lists stay
    assert "[A] --- RANDOM DROPS ---" in names                            # its section still has rules
