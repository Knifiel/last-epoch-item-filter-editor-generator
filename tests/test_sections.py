from lefilter.filterdoc import new_rule
from lefilter.sections import IDOL_PLACEMENT, class_hide_index, doc_infos, place, reorder_generated


def sep(name):
    return new_rule(name, enabled=False)


def rule(name):
    return new_rule(name, conditions=[{"type": "RarityCondition", "rarity": ["RARE"]}])


def names(rules):
    return [r["name"] for r in rules]


HIDE = ["[A] Hide non-Mage class items", "[A] Hide non-Rogue class items"]
TOP = ["[A] ALWAYS SHOW"]
# The template's order: always-show, shatter, class hide, BiS, exalted & legendary, uniques ..., hide the rest.
TEMPLATE = ([rule("[A] ALWAYS SHOW"), sep("------ SHATTER AFFIXES ------"), rule("SHATTER - RARE-ROLL")]
            + [rule(n) for n in HIDE]
            + [sep("------ BIS ITEMS ------"), rule("BIS - Helmet"), sep("------ EXALTED & LEGENDARY ------"), rule("ALL T8"),
               sep("[A] ------- UNIQUES -------"), rule("[A] ANY UNIQUE"), new_rule("HIDE EVERYTHING ELSE", type="HIDE")])
# v0.3.0's: shatter right before the uniques
V030 = [TEMPLATE[0], *TEMPLATE[3:9], *TEMPLATE[1:3], *TEMPLATE[9:]]


def test_a_new_idol_section_goes_right_before_the_uniques():
    idols = [sep("[I] ------- IDOLS (auto) -------"), rule("[I] Small idol")]
    for base in (TEMPLATE, V030):
        merged, removed, at = place(base, doc_infos(base), idols, "[I] ", **IDOL_PLACEMENT)
        assert removed == 0 and names(merged)[at + 2] == "[A] ------- UNIQUES -------"
    bare = [rule("Mine")]
    assert names(place(bare, doc_infos(bare), idols, "[I] ", **IDOL_PLACEMENT)[0])[0] == "[I] ------- IDOLS (auto) -------"


def test_class_hide_rules_go_below_the_always_show_rules_and_a_shatter_section_right_after_them():
    entries = lambda rules: [(r["name"], not r["conditions"]) for r in rules if r["name"] not in HIDE]
    assert class_hide_index(entries(TEMPLATE), TOP) == 3                 # after the shatter section
    assert class_hide_index(entries(V030), TOP) == 1                     # shatter further down: right below always-show
    assert class_hide_index(entries(TEMPLATE[1:]), TOP) == 2             # no always-show rule: after shatter at the top


def test_reorder_moves_generated_sections_back_and_leaves_the_rest():
    rules = ([sep("[I] ------- IDOLS (auto) -------"), rule("[I] Small idol")] + V030[:-1]
             + [rule("[L] Helmet 0-59"), rule("Mine at the bottom")] + V030[-1:])
    rules.insert(4, rule("[L] Sword 0-9"))                         # a stray leveling rule up top
    out, moved = reorder_generated(rules, {"bis": "BIS - ", "idols": "[I] ", "leveling": "[L] "}, TOP, HIDE)
    n = names(out)
    assert moved == ["idol section", "leveling section", "shatter section"]
    assert n[:5] == ["[A] ALWAYS SHOW", "------ SHATTER AFFIXES ------", "SHATTER - RARE-ROLL", *HIDE]
    assert n.index("[I] Small idol") == n.index("[A] ------- UNIQUES -------") - 1
    assert n[-4:] == ["Mine at the bottom", "[L] Sword 0-9", "[L] Helmet 0-59", "HIDE EVERYTHING ELSE"]
    assert reorder_generated(out, {"bis": "BIS - ", "idols": "[I] ", "leveling": "[L] "}, TOP, HIDE) == (out, [])
    custom = [rule("[I] Small idol"), rule("Mine")]                 # no spot for idols: left where they are
    assert reorder_generated(custom, {"idols": "[I] "}) == (custom, [])


def test_reorder_puts_class_hide_rules_below_the_shatter_section():
    old = [V030[0]] + [r for r in V030[1:] if r["name"] not in HIDE]
    at = names(old).index("------ SHATTER AFFIXES ------")
    old = old[:at] + [rule(n) for n in HIDE] + old[at:]             # v0.2.0: class hide right above the shatter section
    out, moved = reorder_generated(old, {}, TOP, HIDE)
    assert moved == ["shatter section", "class hide rules"] and names(out) == names(TEMPLATE)
    assert reorder_generated(out, {}, TOP, HIDE) == (out, [])


def test_reorder_puts_the_unique_block_right_above_the_leveling_section():
    # what a refresh with the old per-class hide rules did: uniques right after the shatter section
    uniques = [sep("[A] ------- UNIQUES -------"), rule("[A] ANY UNIQUE"), rule("Mine among the uniques"),
               sep("[A] --- SET ITEMS ---"), rule("[A] SET RARE+")]
    rules = ([TEMPLATE[0], *TEMPLATE[1:3], *uniques, *TEMPLATE[3:5], sep("------ BIS ITEMS ------"), rule("BIS - Helmet"),
              sep("------ EXALTED & LEGENDARY ------"), rule("ALL T8"), sep("[I] ------- IDOLS (auto) -------"), rule("[I] Small idol"),
              sep("[L] ------- LEVELING (auto) -------"), rule("[L] Helmet 0-59"), new_rule("HIDE EVERYTHING ELSE", type="HIDE")])
    prefixes = {"uniques": "[A] ", "bis": "BIS - ", "idols": "[I] ", "leveling": "[L] "}
    out, moved = reorder_generated(rules, prefixes, TOP, HIDE)
    n = names(out)
    assert moved == ["unique section"]
    assert n == ["[A] ALWAYS SHOW", "------ SHATTER AFFIXES ------", "SHATTER - RARE-ROLL", *HIDE, "------ BIS ITEMS ------",
                 "BIS - Helmet", "------ EXALTED & LEGENDARY ------", "ALL T8", "[I] ------- IDOLS (auto) -------", "[I] Small idol",
                 *[r["name"] for r in uniques], "[L] ------- LEVELING (auto) -------", "[L] Helmet 0-59", "HIDE EVERYTHING ELSE"]
    assert reorder_generated(out, prefixes, TOP, HIDE) == (out, [])
    # no leveling section: right above the bottom hide rule; the template's order stays as it is
    bare = [r for r in rules if not r["name"].startswith("[L]")]
    assert names(reorder_generated(bare, prefixes, TOP, HIDE)[0])[-2:] == ["[A] SET RARE+", "HIDE EVERYTHING ELSE"]
    assert reorder_generated(TEMPLATE, prefixes, TOP, HIDE) == (TEMPLATE, [])
