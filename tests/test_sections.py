from lefilter.filterdoc import new_rule
from lefilter.sections import IDOL_PLACEMENT, doc_infos, place, reorder_generated


def sep(name):
    return new_rule(name, enabled=False)


def rule(name):
    return new_rule(name, conditions=[{"type": "RarityCondition", "rarity": ["RARE"]}])


def names(rules):
    return [r["name"] for r in rules]


# The template's order: always-show, BiS, exalted & legendary (+ class hide), shatter, uniques ..., hide the rest.
TEMPLATE = [rule("[A] ALWAYS SHOW"), sep("------ BIS ITEMS ------"), rule("BIS - Helmet"),
            sep("------ EXALTED & LEGENDARY ------"), rule("ALL T8"), rule("[A] Hide non-Mage class items"),
            sep("------ SHATTER AFFIXES ------"), rule("SHATTER - RARE-ROLL"),
            sep("[A] ------- UNIQUES -------"), rule("[A] ANY UNIQUE"),
            new_rule("HIDE EVERYTHING ELSE", type="HIDE")]


def test_a_new_idol_section_goes_after_shatter_before_the_uniques():
    idols = [sep("[I] ------- IDOLS (auto) -------"), rule("[I] Small idol")]
    merged, removed, at = place(TEMPLATE, doc_infos(TEMPLATE), idols, "[I] ", **IDOL_PLACEMENT)
    assert removed == 0 and names(merged)[at - 1:at + 3] == ["SHATTER - RARE-ROLL", "[I] ------- IDOLS (auto) -------",
                                                             "[I] Small idol", "[A] ------- UNIQUES -------"]
    no_shatter = [r for r in TEMPLATE if "SHATTER" not in r["name"]]
    merged, _, at = place(no_shatter, doc_infos(no_shatter), idols, "[I] ", **IDOL_PLACEMENT)
    assert names(merged)[at + 2] == "[A] ------- UNIQUES -------"            # no shatter: just before the uniques
    bare = [rule("Mine")]
    assert names(place(bare, doc_infos(bare), idols, "[I] ", **IDOL_PLACEMENT)[0])[0] == "[I] ------- IDOLS (auto) -------"


def test_reorder_moves_generated_sections_back_and_leaves_the_rest():
    rules = ([sep("[I] ------- IDOLS (auto) -------"), rule("[I] Small idol")] + TEMPLATE[:-1]
             + [rule("[L] Helmet 0-59"), rule("Mine at the bottom")] + TEMPLATE[-1:])
    rules.insert(3, rule("[L] Sword 0-9"))                         # a stray leveling rule up top
    out, moved = reorder_generated(rules, {"bis": "BIS - ", "idols": "[I] ", "leveling": "[L] "})
    n = names(out)
    assert moved == ["idol section", "leveling section"]
    assert n.index("[I] Small idol") == n.index("SHATTER - RARE-ROLL") + 2
    assert n[-4:] == ["Mine at the bottom", "[L] Sword 0-9", "[L] Helmet 0-59", "HIDE EVERYTHING ELSE"]
    assert reorder_generated(out, {"bis": "BIS - ", "idols": "[I] ", "leveling": "[L] "}) == (out, [])
    custom = [rule("[I] Small idol"), rule("Mine")]                 # no spot for idols: left where they are
    assert reorder_generated(custom, {"idols": "[I] "}) == (custom, [])
