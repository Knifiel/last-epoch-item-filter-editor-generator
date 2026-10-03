from lefilter.affixtext import (ADDED, HUNDREDTH, INCREASED, INTEGER, MORE, PREFIX_ADDED_TO, PREFIX_INCREASED,
                                PREFIX_LESS, PREFIX_NONE, PREFIX_PERCENT_OF, PREFIX_REDUCED, TENTH, THOUSANDTH,
                                PropertyLists, affix_lines, display, format_line, format_value, implicit_lines, prefix_type,
                                resolve, rounding)
from lefilter.i18n import build_language, clean, strip_value_tag

LISTS = PropertyLists(
    master={59: {"propertyName": "Penetration", "roundingForAdded": HUNDREDTH},        # shown as +4%
            7: {"propertyName": "Health", "roundingForAdded": INTEGER},                # shown as +15
            0: {"propertyName": "Damage"},
            30: {"propertyName": "All Resistances", "roundingForAdded": HUNDREDTH, "displayAsAddedTo": True},
            51: {"propertyName": "Leech", "roundingForAdded": THOUSANDTH, "displayAddedAsPercentage": True,
                 "displayAsPercentageOf": True},
            115: {"propertyName": "More Damage", "roundingForMore": HUNDREDTH,
                  "moreRoundingOverrides": [{"specialTag": 16, "roundingForMore": THOUSANDTH}]},
            43: {"propertyName": "Increased Ailment Effect", "roundingForAdded": HUNDREDTH, "dontDisplayPlus": True}},
    penetration_ailments={1},                                                  # Ignite adds penetration
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
                    "98,3": "unused: the game never reads these two-part keys", "43,8,1,0,0": "Fire Penetration with Ignite",
                    "43,0,8,0,0": "Armor Shred Effect", "98,275,0,0,6": "Damage over Time taken while you have Haste"},
    "Item_Affixes": {"Item_Affix_20_DisplayName": "Health On Kill", "Item_Affix_98_DisplayName": "Damage Over Time for Minions",
                     "Item_Affix_1003_DisplayName": "Increased Health Leech"},
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
    (dot,) = lines(single(98, 0, 8192, INCREASED, [(0.1, 0.2)], generated=0))      # display name + the prefix word
    assert dot["source"] == ["Item_Affixes", "Item_Affix_98_DisplayName", PREFIX_INCREASED]
    assert text(dot) == "10-20% increased Damage Over Time for Minions"
    (leech,) = lines(single(1003, 0, 0, INCREASED, [(0.1, 0.1)], generated=0))   # the game doesn't drop a doubled word
    assert text(leech) == "10% increased Increased Health Leech"
    affix = {"affixId": 992, "affixName": "Haste Armor", "affixDisplayName": "",
             "affixProperties": [{"property": 7, "tags": 0, "specialTag": 0, "extraTag": 0, "modifierType": ADDED,
                                  "modDisplayName": "", "useGeneratedNameForDisplayName": 1},
                                 {"property": 98, "tags": 275, "specialTag": 0, "extraTag": 0, "modifierType": MORE,
                                  "modDisplayName": "Reduced Armor during Haste", "useGeneratedNameForDisplayName": 0}],
             "tiers": [{"minRoll": 5, "maxRoll": 5, "extraRolls": [{"minRoll": -0.2, "maxRoll": -0.1}]}]}
    first, second = lines(affix)
    assert first["text"] == "Health" and first["tiers"] == [[5, 5]]
    # English shows the property's own name; other languages resolve the descriptor (source)
    assert second["text"] == "less Reduced Armor during Haste" and second["tiers"] == [[0.1, 0.2]]
    assert second["source"] == ["Descriptors", "98,275,0,0,6", 0]


def test_penetration_ailments_use_the_penetration_info():
    (ignite,) = lines(single(182, 43, 8, ADDED, [(0.09, 0.16)], special=1))
    assert text(ignite) == "+9-16% Fire Penetration with Ignite"
    (shred,) = lines(single(370, 43, 0, ADDED, [(0.1, 0.2)], special=8))
    assert text(shred) == "10-20% Armor Shred Effect"


def test_idol_altar_stats_use_the_altar_list():
    (line,) = lines(single(1088, 130, 13, ADDED, [(2, 2)]))
    assert text(line) == "+2 Health per Equipped Heretical Idol"


def test_values_round_half_to_even_in_single_precision():
    line = {"step": 0.01, "mult": 100, "percent": True}
    assert format_value(0.125, line) == "12%" and format_value(0.135, line) == "14%"
    assert format_value(1.2, {"step": 0.1, "mult": 1, "percent": False}) == "1.2"


def test_korean_puts_values_after_and_omits_to():
    words = {PREFIX_ADDED_TO: "~", PREFIX_INCREASED: "증가"}
    ko = {"value_after": True, "omit_added_to": True, "modifiers_last": True, "values_prepend_modifiers": True}
    assert resolve(["Descriptors", "k", PREFIX_ADDED_TO], {"Descriptors": {"k": "모든 저항"}}, words, ko) == "모든 저항"
    armor = resolve(["Item_Affixes", "n", PREFIX_INCREASED], {"Item_Affixes": {"n": "방어도"}}, words, ko)
    assert armor == "방어도 {0} 증가"
    line = {"text": armor, "sign": "", "step": 0.01, "mult": 100, "percent": True, "hide": False}
    assert format_line(line, 0.1, 0.1, value_after=True) == "방어도 10% 증가"
    line = {"text": "냉기 저항", "sign": "+", "step": 0.01, "mult": 100, "percent": True, "hide": False}
    assert format_line(line, 0.04, 0.04, value_after=True) == "냉기 저항 +4%"


def test_translation_cleanup_and_overlay():
    assert clean("[ns]Zweihandschwert") == "Zweihandschwert"
    assert clean("[ms]Verfluchter[fs]Verfluchte[ns]Verfluchtes[p]Verfluchte") == "Verfluchter"
    assert clean("[fs]maudite[ms]maudit[fp]maudites[mp]maudits") == "maudit"
    assert clean("{【ルーンボルト】}の詠唱") == "【ルーンボルト】の詠唱"
    assert clean("화염 피해 {0} 증가") == "화염 피해 {0} 증가" and strip_value_tag("화염 피해 {0} 증가") == "화염 피해 증가"
    data = {"uniques": [{"id": 42}],
            "bases": [{"id": 16, "subtypes": [{"id": 0, "implicits": [{"source": ["Descriptors", "7,0,0,0", 0]},
                                                                      {"source": None}]}, {"id": 1}]}],
            "affixes": [{"id": 35, "lines": [{"source": ["Descriptors", "59,4,0,0", 0]}]},
                        {"id": 46, "lines": [{"source": ["Descriptors", "30,0,0,2", PREFIX_ADDED_TO]}]},
                        {"id": 1, "filter_name": True, "lines": [{"source": None}]}]}
    tables = {"Item_Names": {"Unique_Name_42": "Fackel", "Item_BaseType_Name_16": "[ns]Zweihandschwert",
                             "Item_SubType_Name_16_0": "Bastardschwert"},
              "Item_Affixes": {"Item_Affix_35_DisplayName": "Kältedurchdringung", "Item_Affix_1_DisplayName": "Rüstung",
                               "Item_Affix_1_FilterOverride": "Erhöhte Rüstung"},
              "Descriptors": {"59,4,0,0": "Kältedurchdringung", "30,0,0,2": "alle Widerstände", "7,0,0,0": "Gesundheit"},
              "Common": {"ModFormat_AddedToPrefix_To": "auf"}}
    lang = build_language(tables, data, "de")
    assert lang["uniques"] == {42: "Fackel"} and lang["base_types"] == {16: "Zweihandschwert"}
    assert lang["subtypes"] == {"16/0": "Bastardschwert"}
    assert lang["affixes"] == {35: "Kältedurchdringung", 1: "Erhöhte Rüstung"}     # the filter picker's name
    assert lang["lines"] == {35: ["Kältedurchdringung"], 46: ["auf alle Widerstände"]}
    assert lang["implicits"] == {"16/0": ["Gesundheit", None]}                       # None: English stays
    assert lang["value_after"] is False and build_language(tables, data, "ko")["value_after"] is True


def test_implicits_read_like_affix_stats_with_their_roll_range():
    def imp(prop, tags, mod, lo, hi, special=0):
        return {"property": prop, "tags": tags, "specialTag": special, "extraTag": 0, "type": mod,
                "implicitValue": lo, "implicitMaxValue": hi}
    health, fire, pen = implicit_lines([imp(7, 0, ADDED, 30, 40), imp(0, 8, INCREASED, -0.12, -0.02),
                                        imp(59, 4, ADDED, 0.04, 0.04)], LISTS, TABLES)
    assert text(health) == "+30-40 Health" and health["source"] == ["Descriptors", "7,0,0,0", 0]
    assert text(fire) == "2-12% Reduced Fire Damage"          # negative increased: reduced, no sign
    assert text(pen) == "+4% Cold Penetration"                 # a fixed implicit: one value


def test_unique_tooltip_in_game_order():
    from lefilter.affixtext import unique_tooltip
    mod = lambda prop, lo, hi, roll, rid=0, hide=False: {"property": prop, "tags": 0, "specialTag": 0, "extraTag": 0, "type": ADDED,
                                                          "value": lo, "maxValue": hi, "canRoll": roll, "rollID": rid,
                                                          "hideInTooltip": hide}
    unique = {"uniqueID": 7, "mods": [mod(7, 40, 60, True, 1), mod(7, 10, 0, False), mod(7, 5, 5, False, hide=True)],
              "tooltipDescriptions": [{"description": "[10,20,2]% more fun", "setRequirement": 2}],
              "tooltipEntries": [{"modDisplay": 128}, {"modDisplay": 0}, {"modDisplay": 1}, {"modDisplay": 2}]}
    tables = {**TABLES, "Item_Names": {"Unique_Tooltip_0_7": "[10,20,2]% more fun (named)"}}
    lines = unique_tooltip(unique, LISTS, tables)
    assert lines[0] == {"text": "[10,20,2]% more fun (named)", "desc": 0, "set": 2}
    assert text(lines[1]) == "+40-60 Health" and lines[1]["roll"] and (lines[1]["roll_id"], lines[1]["vmin"], lines[1]["vmax"]) == (1, 40, 60)
    assert text(lines[2]) == "+10 Health" and not lines[2]["roll"] and len(lines) == 3      # hidden mod left out


def test_set_bonuses_in_game_order_with_the_pieces_they_need():
    from lefilter.affixtext import set_bonuses
    bonus = lambda prop, value, pieces, hide=False: {"property": prop, "tags": 0, "specialTag": 0, "extraTag": 0, "type": ADDED,
                                                     "value": value, "setRequirement": pieces, "hideInTooltip": hide}
    entry = {"setID": 1, "setName": "Isadora's", "mods": [bonus(7, 1, 3, hide=True), bonus(7, 20, 3)],
             "tooltipDescriptions": [{"description": "+30% Mana Efficiency", "setRequirement": 3},
                                     {"description": "Damned on hit", "setRequirement": 2}],
             "tooltipEntries": [{"modDisplay": 129}, {"modDisplay": 1}, {"modDisplay": 128}, {"modDisplay": 0}]}
    lines = set_bonuses(entry, LISTS, TABLES)
    assert lines[0] == {"text": "Damned on hit", "desc": 1, "set": 2}
    assert text(lines[1]) == "+20 Health" and lines[1]["set"] == 3
    assert lines[2] == {"text": "+30% Mana Efficiency", "desc": 0, "set": 3} and len(lines) == 3   # the described mod: out


def test_unique_rolls_offer_hidden_and_fixed_mods_like_the_game():
    from lefilter.affixtext import unique_rolls
    mod = lambda prop, lo, hi, roll, rid, hide=False: {"property": prop, "tags": 0, "specialTag": 0, "extraTag": 0,
                                                       "type": ADDED, "value": lo, "maxValue": hi, "canRoll": roll,
                                                       "rollID": rid, "hideInTooltip": hide}
    unique = {"uniqueID": 9, "mods": [mod(7, 40, 60, True, 1), mod(7, 5, 9, True, 0, hide=True), mod(7, 10, 0, True, 2),
                                      mod(7, 3, 3, False, 3)],
              "tooltipDescriptions": [{"description": "[5,9,0] stacks of fun", "setRequirement": 0}]}
    rolls = unique_rolls(unique, LISTS, TABLES)
    assert [(r["roll_id"], r["hidden"], r["varies"]) for r in rolls] == [(1, False, True), (0, True, True), (2, False, False)]
    assert rolls[1]["desc"] == 0 and "desc" not in rolls[0]            # the hidden roll's value shows in description 0
    assert (rolls[2]["vmin"], rolls[2]["vmax"]) == (10, 10)            # max below value: a fixed value


def test_ranges_across_zero_keep_their_signs():
    from lefilter.affixtext import stat_lines
    line = stat_lines([{"property": 7, "tags": 0, "specialTag": 0, "type": ADDED, "lo": -20, "hi": 50}], LISTS, TABLES)[0]
    assert line["signed"] and text(line) == "-20 to +50 Health"
