from lefilter.affixtext import (ADDED, HUNDREDTH, INCREASED, INTEGER, MORE, PREFIX_ADDED_TO, PREFIX_INCREASED,
                                PREFIX_LESS, PREFIX_NONE, PREFIX_PERCENT_OF, PREFIX_REDUCED, TENTH, THOUSANDTH,
                                PropertyLists, affix_lines, display, format_line, format_value, prefix_type, resolve,
                                rounding)
from lefilter.i18n import build_language, clean, strip_value_tag

LISTS = PropertyLists(
    master={59: {"propertyName": "Penetration", "roundingForAdded": HUNDREDTH},        # shown as +4%
            7: {"propertyName": "Health", "roundingForAdded": INTEGER},                # shown as +15
            0: {"propertyName": "Damage"},
            30: {"propertyName": "All Resistances", "roundingForAdded": HUNDREDTH, "displayAsAddedTo": True},
            51: {"propertyName": "Leech", "roundingForAdded": THOUSANDTH, "displayAddedAsPercentage": True,
                 "displayAsPercentageOf": True},
            115: {"propertyName": "More Damage", "roundingForMore": HUNDREDTH,
                  "moreRoundingOverrides": [{"specialTag": 16, "roundingForMore": THOUSANDTH}]}},
    ability={120: [{}, {}, {}, {"roundingForAdded": HUNDREDTH, "displayAddedAsPercentage": True, "dontDisplayPlus": True}]},
    player=[{}, {}, {}, {}, {"roundingForAdded": INTEGER},
            {"roundingForAdded": INTEGER, "hideModifierValue": True}],
    altar=[{"propertyName": "Maximum Omen Idols", "roundingForAdded": INTEGER}] * 13 +
          [{"propertyName": "Health per Equipped Heretical Idol", "roundingForAdded": INTEGER}])
TABLES = {
    "Descriptors": {"59,4,0,0": "Cold Penetration", "7,0,0,0": "Health", "0,8,0,3": "Increased Fire Damage",
                    "0,8,0,4": "Reduced Fire Damage", "30,0,0,2": "All Resistances",
                    "51,2,0,1": "of Lightning Damage Leeched as Health", "98,4,0,0": "Bees Per 10 Seconds",
                    "58,120,3,0": "Increased Skeleton Damage", "115,0,16,0,5": "More Damage per stack of Frailty",
                    "98,3": "increased Damage Over Time for Minions"},
    "Item_Affixes": {"Item_Affix_20_DisplayName": "Health On Kill", "ItemAffix_314_Affix_A": "Damage Reflected for Skeletons"},
}


def single(aid, prop, tags, mod, tiers, special=0, name="", generated=1):
    return {"affixId": aid, "affixName": name, "affixDisplayName": "", "property": prop, "tags": tags,
            "specialTag": special, "extraTag": 0, "modifierType": mod, "useGeneratedNameForDisplayName": generated,
            "tiers": [{"minRoll": a, "maxRoll": b, "extraRolls": []} for a, b in tiers]}


def lines(affix):
    return affix_lines(affix, LISTS, TABLES)


def text(line, tier=0):
    return format_line(line, *line["tiers"][tier])


def test_prefix_rounding_and_display_rules():
    assert prefix_type(ADDED, {}) == PREFIX_NONE
    assert prefix_type(ADDED, {"displayAsPercentageOf": True}) == PREFIX_PERCENT_OF
    assert prefix_type(ADDED, {"displayAsAddedTo": True}) == PREFIX_ADDED_TO
    assert prefix_type(INCREASED, {}) == PREFIX_INCREASED and prefix_type(INCREASED, {}, False) == PREFIX_REDUCED
    assert prefix_type(INCREASED, {"nameIncludesModifier": True}) == PREFIX_NONE
    assert prefix_type(MORE, {}, False) == PREFIX_LESS
    assert rounding({"roundingForAdded": TENTH}, ADDED) == TENTH
    assert rounding({"roundingForMore": INTEGER}, INCREASED) == HUNDREDTH       # increased: always hundredths
    assert rounding(LISTS.master[115], MORE, 16) == THOUSANDTH and rounding(LISTS.master[115], MORE, 3) == HUNDREDTH
    assert display({}, INCREASED, HUNDREDTH) == (100, True)
    assert display({"displayAddedAsTenthOfValue": True}, ADDED, HUNDREDTH) == (10, True)
    assert display({"displayAddedAsTenthOfValue": True}, ADDED, INTEGER) == (1, False)
    assert display({"displayAddedAsPercentage": True}, ADDED, THOUSANDTH) == (100, True)


def test_lines_read_like_the_game():
    (pen,) = lines(single(35, 59, 4, ADDED, [(0.04, 0.04), (0.24, 0.3)]))
    assert text(pen) == "+4% Cold Penetration" and text(pen, 1) == "+24-30% Cold Penetration"
    (hp,) = lines(single(25, 7, 0, ADDED, [(5, 15)]))
    assert text(hp) == "+5-15 Health"
    (inc,) = lines(single(12, 0, 8, INCREASED, [(0.06, 0.12)]))
    assert text(inc) == "6-12% Increased Fire Damage"               # no sign on increased / more
    (res,) = lines(single(46, 30, 0, ADDED, [(0.05, 0.05)]))
    assert text(res) == "+5% to All Resistances"                    # added-to: "to" in front
    (leech,) = lines(single(42, 51, 2, ADDED, [(0.003, 0.004)]))
    assert text(leech) == "0.3-0.4% of Lightning Damage Leeched as Health"   # percentage of: no sign
    (frail,) = lines(single(981, 115, 0, MORE, [(0.004, 0.004)], special=16))
    assert text(frail) == "0.4% More Damage per stack of Frailty"   # per-stat rounding override


def test_negative_rolls_read_as_reduced():
    (red,) = lines(single(13, 0, 8, INCREASED, [(-0.16, -0.06)]))
    assert red["tiers"] == [[0.06, 0.16]] and text(red) == "6-16% Reduced Fire Damage"
    (hp,) = lines(single(26, 7, 0, ADDED, [(-10, -5)]))
    assert hp["sign"] == "-" and text(hp) == "-5 to -10 Health"


def test_ability_and_player_stats_use_their_own_lists():
    (skel,) = lines(single(192, 58, 120, ADDED, [(0.1, 0.14)], special=3))
    assert text(skel) == "10-14% Increased Skeleton Damage"
    (bees,) = lines(single(216, 98, 4, ADDED, [(3, 7)]))
    assert text(bees) == "+3-7 Bees Per 10 Seconds"
    (rage,) = lines(single(1111, 98, 5, ADDED, [(1, 1)], name="You have Berserking Rage"))
    assert rage["hide"] and text(rage) == "You have Berserking Rage"


def test_display_name_affixes_and_multi_affix_lines():
    (kill,) = lines(single(20, 7, 0, ADDED, [(2, 2)], generated=0))
    assert kill["source"] == ["Item_Affixes", "Item_Affix_20_DisplayName", 0] and text(kill) == "+2 Health On Kill"
    (dot,) = lines(single(98, 0, 8192, INCREASED, [(0.1, 0.2)], generated=0))
    assert text(dot) == "10-20% increased Damage Over Time for Minions"
    affix = {"affixId": 314, "affixName": "Damage Reflected For Skeletons And Mages", "affixDisplayName": "",
             "affixProperties": [{"property": 0, "tags": 0, "specialTag": 77, "extraTag": 0, "modifierType": ADDED},
                                 {"property": 7, "tags": 0, "specialTag": 0, "extraTag": 0, "modifierType": ADDED}],
             "tiers": [{"minRoll": 0.2, "maxRoll": 0.4, "extraRolls": [{"minRoll": 5, "maxRoll": 5}]}]}
    first, second = lines(affix)
    assert first["text"] == "Damage Reflected for Skeletons" and second["text"] == "Health"
    assert first["tiers"] == [[0.2, 0.4]] and second["tiers"] == [[5, 5]]


def test_idol_altar_stats_use_the_altar_list():
    (line,) = lines(single(1088, 130, 13, ADDED, [(2, 2)]))
    assert text(line) == "+2 Health per Equipped Heretical Idol"


def test_values_round_half_to_even_in_single_precision():
    line = {"step": 0.01, "mult": 100, "percent": True}
    assert format_value(0.125, line) == "12%" and format_value(0.135, line) == "14%"
    assert format_value(1.2, {"step": 0.1, "mult": 1, "percent": False}) == "1.2"


def test_korean_puts_values_after_and_omits_to():
    words = {PREFIX_ADDED_TO: "~", PREFIX_INCREASED: "증가"}
    ko = {"value_after": True, "omit_added_to": True, "modifiers_last": True}
    assert resolve(["Descriptors", "k", PREFIX_ADDED_TO], {"Descriptors": {"k": "모든 저항"}}, words, ko) == "모든 저항"
    assert resolve(["Item_Affixes", "n", PREFIX_INCREASED], {"Item_Affixes": {"n": "방어도"}}, words, ko) == "방어도 증가"
    line = {"text": "냉기 저항", "sign": "+", "step": 0.01, "mult": 100, "percent": True, "hide": False}
    assert format_line(line, 0.04, 0.04, value_after=True) == "냉기 저항 +4%"


def test_translation_cleanup_and_overlay():
    assert clean("[ns]Zweihandschwert") == "Zweihandschwert"
    assert clean("[ms]Verfluchter[fs]Verfluchte[ns]Verfluchtes[p]Verfluchte") == "Verfluchter"
    assert clean("[fs]maudite[ms]maudit[fp]maudites[mp]maudits") == "maudit"
    assert clean("{【ルーンボルト】}の詠唱") == "【ルーンボルト】の詠唱"
    assert clean("화염 피해 {0} 증가") == "화염 피해 {0} 증가" and strip_value_tag("화염 피해 {0} 증가") == "화염 피해 증가"
    data = {"uniques": [{"id": 42}], "bases": [{"id": 16, "subtypes": [{"id": 0}]}],
            "affixes": [{"id": 35, "lines": [{"source": ["Descriptors", "59,4,0,0", 0]}]},
                        {"id": 46, "lines": [{"source": ["Descriptors", "30,0,0,2", PREFIX_ADDED_TO]}]},
                        {"id": 1, "filter_name": True, "lines": [{"source": None}]}]}
    tables = {"Item_Names": {"Unique_Name_42": "Fackel", "Item_BaseType_Name_16": "[ns]Zweihandschwert",
                             "Item_SubType_Name_16_0": "Bastardschwert"},
              "Item_Affixes": {"Item_Affix_35_DisplayName": "Kältedurchdringung", "Item_Affix_1_DisplayName": "Rüstung",
                               "Item_Affix_1_FilterOverride": "Erhöhte Rüstung"},
              "Descriptors": {"59,4,0,0": "Kältedurchdringung", "30,0,0,2": "alle Widerstände"},
              "Common": {"ModFormat_AddedToPrefix_To": "auf"}}
    lang = build_language(tables, data, "de")
    assert lang["uniques"] == {42: "Fackel"} and lang["base_types"] == {16: "Zweihandschwert"}
    assert lang["subtypes"] == {"16/0": "Bastardschwert"}
    assert lang["affixes"] == {35: "Kältedurchdringung", 1: "Erhöhte Rüstung"}     # the filter picker's name
    assert lang["lines"] == {35: ["Kältedurchdringung"], 46: ["auf alle Widerstände"]}
    assert lang["value_after"] is False and build_language(tables, data, "ko")["value_after"] is True
