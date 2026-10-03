from lefilter.extract import build_affixes


def raw_affix(aid, name, category, type_=0):
    return {"affixId": aid, "affixName": name, "affixDisplayName": name, "displayCategory": category, "classSpecificity": 0,
            "specialAffixType": 0, "rollsOn": 0, "type": type_, "levelRequirement": 0, "weighting": 1.0, "canRollOn": [16],
            "standardAffixEffectModifier": 0.0}


def test_affixes_carry_their_place_in_the_in_game_picker():
    data = {"affixDisplayCategories": ["Damage Type", "Melee", "Health", "Loose"],
            "categoryHeaders": [{"name": "Offensive", "categories": [1, 0]}, {"name": "Defensive", "categories": [2]}],
            "singleAffixes": [raw_affix(3, "Health", 2), raw_affix(1, "Fire Damage", 0), raw_affix(2, "Melee Speed", 1, 1)],
            "multiAffixes": [raw_affix(4, "Odd one", 3)]}
    got = {a["id"]: (a["header"], a["category"], a["order"]) for a in build_affixes(data)}
    assert got == {1: ("Offensive", "Damage Type", [0, 1]), 2: ("Offensive", "Melee", [0, 0]),
                   3: ("Defensive", "Health", [1, 0]), 4: ("", "Loose", [2, 3])}   # no header: after the rest


def test_affix_names_are_the_in_game_pickers():
    data = {"affixDisplayCategories": ["Idol Altars"], "categoryHeaders": [{"name": "Idols", "categories": [0]}],
            "singleAffixes": [{**raw_affix(1098, "Maximum Idols Equipped", 0)},
                              {**raw_affix(25, "Health", 0), "affixLootFilterOverrideName": "Added Health"},
                              {**raw_affix(7, "Odd", 0), "affixDisplayName": ""}],
            "multiAffixes": []}
    tables = {"Item_Affixes": {"Item_Affix_1098_DisplayName": "increased Mana Regen per Equipped Ornate Idol",
                               "Item_Affix_25_DisplayName": "Health", "Item_Affix_25_FilterOverride": "Added Health"}}
    got = {a["id"]: (a["name"], a["internal_name"]) for a in build_affixes(data, tables=tables)}
    assert got == {1098: ("increased Mana Regen per Equipped Ornate Idol", "Maximum Idols Equipped"),   # its display name
                   25: ("Added Health", "Health"),                                                   # the filter override first
                   7: ("Odd", "Odd")}                                                                # no text: its own name


def test_affixes_off_equipment_stop_at_t7(monkeypatch):
    from lefilter import extract
    tiers = [[t, t + 1] for t in range(8)]
    monkeypatch.setattr(extract.affixtext, "affix_lines", lambda a, *rest: [{"text": "x", "tiers": tiers}])
    lists = type("Lists", (), {"master": True})()
    data = {"affixDisplayCategories": ["c"], "categoryHeaders": [], "multiAffixes": [],
            "singleAffixes": [{**raw_affix(1098, "Altar thing", 0), "canRollOn": [41]},       # idol altar
                              {**raw_affix(30, "Gear thing", 0), "canRollOn": [16, 41]}]}     # equipment too
    got = {a["id"]: len(a["lines"][0]["tiers"]) for a in extract.build_affixes(data, lists)}
    assert got == {1098: 7, 30: 8}


def test_a_variant_mod_has_its_one_fixed_value(monkeypatch):
    from lefilter import extract
    same, ladder = [[1.0, 1.0]] * 8, [[t, t + 1] for t in range(8)]
    monkeypatch.setattr(extract.affixtext, "affix_lines", lambda a, *rest: [{"text": "x", "tiers": same if a["affixId"] == 1 else ladder}])
    lists = type("Lists", (), {"master": True})()
    data = {"affixDisplayCategories": ["Variant"], "categoryHeaders": [], "multiAffixes": [],
            "singleAffixes": [{**raw_affix(1, "You have Berserking Rage", 0), "specialAffixType": 7},
                              {**raw_affix(2, "Variant with tiers", 0), "specialAffixType": 7},
                              {**raw_affix(3, "Ordinary", 0)}]}
    got = {a["id"]: len(a["lines"][0]["tiers"]) for a in extract.build_affixes(data, lists)}
    assert got == {1: 1, 2: 8, 3: 8}
