import json

import pytest

from lefilter.filterdoc import new_rule, parse_filter, parse_rule_blocks, render_filter
from lefilter.filterxml import render_rule
from lefilter.rules import Rule, RuleSpec

NL = "\r\n"


def rule_xml(conditions: list[str], name="R", order=0, enabled="true") -> list[str]:
    body = [" " * 8 + line for c in conditions for line in c.split(NL)]
    return ["    <Rule>", "      <type>SHOW</type>",
            *(["      <conditions>", *body, "      </conditions>"] if conditions else ["      <conditions />"]),
            "      <recolor>true</recolor>", "      <color>7</color>", f"      <isEnabled>{enabled}</isEnabled>",
            "      <levelDependent_deprecated>false</levelDependent_deprecated>",
            "      <minLvl_deprecated>0</minLvl_deprecated>", "      <maxLvl_deprecated>0</maxLvl_deprecated>",
            "      <emphasized>true</emphasized>",
            f"      <nameOverride>{name}</nameOverride>" if name else "      <nameOverride />",
            "      <SoundId>6</SoundId>", "      <MapIconId>8</MapIconId>", "      <BeamOverride>true</BeamOverride>",
            "      <BeamSizeOverride>LARGEST</BeamSizeOverride>", "      <BeamColorOverride>5</BeamColorOverride>",
            f"      <Order>{order}</Order>", "    </Rule>"]


def cond(ctype: str, *lines: str) -> str:
    if not lines:
        return f'<Condition i:type="{ctype}" />'
    return NL.join([f'<Condition i:type="{ctype}">', *[f"  {l}" for l in lines], "</Condition>"])


CONDITIONS = [
    cond("RarityCondition", "<rarity>UNIQUE SET</rarity>"),
    cond("SubTypeCondition", "<type>", "  <EquipmentType>RING</EquipmentType>", "</type>", "<subTypes>", "  <int>3</int>", "</subTypes>"),
    cond("SubTypeCondition", "<type />", "<subTypes />"),
    cond("AffixCondition", "<affixes>", "  <int>50</int>", "  <int>501</int>", "</affixes>", "<comparsion>MORE_OR_EQUAL</comparsion>",
         "<comparsionValue>6</comparsionValue>", "<minOnTheSameItem>2</minOnTheSameItem>",
         "<combinedComparsion>MORE_OR_EQUAL</combinedComparsion>", "<combinedComparsionValue>13</combinedComparsionValue>",
         "<advanced>true</advanced>"),
    cond("CharacterLevelCondition", "<minimumLvl>0</minimumLvl>", "<maximumLvl>29</maximumLvl>"),
    cond("PotentialCondition", "<MinLegendaryPotential>2</MinLegendaryPotential>", '<MaxLegendaryPotential i:nil="true" />',
         '<MinWeaversWill i:nil="true" />', "<MaxWeaversWill>16</MaxWeaversWill>", '<MinWeaversTouch i:nil="true" />',
         '<MaxWeaversTouch i:nil="true" />', '<MinForgingPotential i:nil="true" />', '<MaxForgingPotential i:nil="true" />'),
    cond("ClassCondition", "<req>Any</req>"),
    cond("ClassCondition", "<req>Mage Rogue</req>"),
    cond("UniqueModifiersCondition", "<Uniques>", "  <UniqueId>12</UniqueId>", "  <Rolls>", "    <UniqueModifierWithRollId>",
         "      <RollId>1</RollId>", "      <Modifier>", "        <MinRoll>0</MinRoll>", "        <MaxRoll>255</MaxRoll>",
         "      </Modifier>", "    </UniqueModifierWithRollId>", "  </Rolls>", "</Uniques>",
         "<Uniques>", "  <UniqueId>40</UniqueId>", "  <Rolls />", "</Uniques>"),
    cond("UniqueModifiersCondition"),
    cond("CorruptionCondition", "<Corruption>OnlyUncorrupted</Corruption>"),
    cond("FactionCondition", "<EligibleFactions>", "  <FactionID>CircleOfFortune</FactionID>", "</EligibleFactions>"),
    cond("KeysCondition", "<NonEquippableItemFilterFlags>AllKeys</NonEquippableItemFilterFlags>"),
    cond("GlyphCondition", "<GlyphFilterFlags>GlyphOfHope GlyphOfEnvy</GlyphFilterFlags>"),
    cond("SomeFutureCondition", "<whatever>1</whatever>"),
]


def filter_text(rules: list[list[str]], description="mine") -> str:
    """Game-format filter; rules given top first, written bottom first like the game."""
    numbered = []
    for order, r in enumerate(rules):
        numbered.append([line.replace("<Order>0</Order>", f"<Order>{order}</Order>") for line in r])
    body = [line for r in reversed(numbered) for line in r]
    return NL.join(['<ItemFilter xmlns:i="http://www.w3.org/2001/XMLSchema-instance">', "  <name>F &amp; G</name>",
                    "  <filterIcon>13</filterIcon>", "  <filterIconColor>2</filterIconColor>",
                    f"  <description>{description}</description>" if description else "  <description />",
                    "  <lastModifiedInVersion>1.5</lastModifiedInVersion>", "  <lootFilterVersion>9</lootFilterVersion>",
                    "  <rules>", *body, "  </rules>", "</ItemFilter>"])


def test_every_condition_layout_round_trips_byte_for_byte():
    text = filter_text([rule_xml(CONDITIONS, name="R &amp; D &lt;x&gt; 'q' \"z\""), rule_xml([], name="", enabled="false")])
    doc = parse_filter("﻿" + text)
    assert render_filter(doc) == text
    assert render_filter(json.loads(json.dumps(doc))) == text


def test_decoded_conditions():
    doc = parse_filter(filter_text([rule_xml(CONDITIONS)]))
    r = doc["rules"][0]
    by = [c for c in r["conditions"]]
    assert by[0] == {"type": "RarityCondition", "rarity": ["UNIQUE", "SET"]}
    assert by[1] == {"type": "SubTypeCondition", "types": ["RING"], "subtypes": [3]}
    assert by[3]["min_on_same_item"] == 2 and by[3]["advanced"] is True and by[3]["affixes"] == [50, 501]
    assert by[5]["lp_min"] == 2 and by[5]["lp_max"] is None and by[5]["ww_max"] == 16
    assert by[6]["classes"] == ["Primalist", "Mage", "Sentinel", "Acolyte", "Rogue"]
    assert by[7]["classes"] == ["Mage", "Rogue"]
    assert by[8]["uniques"] == [{"id": 12, "rolls": [{"roll": 1, "min": 0, "max": 255}]}, {"id": 40, "rolls": []}]
    assert by[9]["uniques"] == []
    assert by[13]["flags"] == ["GlyphOfHope", "GlyphOfEnvy"]
    assert "raw" in by[14] and by[14]["type"] == "SomeFutureCondition"
    assert r["name"] == "R" and r["sound"] == 6 and r["beam_size"] == "LARGEST" and r["recolor"] and r["color"] == 7


def test_edits_are_written_in_game_format():
    doc = parse_filter(filter_text([rule_xml(CONDITIONS[:1]), rule_xml([], name="sep")]))
    cls = {"type": "ClassCondition", "classes": ["Rogue", "Primalist"]}
    doc["rules"][0]["conditions"] += [cls, {"type": "RarityCondition", "rarity": []}]
    doc["rules"].insert(0, new_rule("new"))
    text = render_filter(doc)
    assert "<req>Primalist Rogue</req>" in text            # declaration order, like the game
    assert "<rarity>NONE</rarity>" in text
    again = parse_filter(text)
    assert [r["name"] for r in again["rules"]] == ["new", "R", "sep"]
    assert again["rules"][0]["conditions"] == [] and "<conditions />" in text


def test_unknown_rule_layout_is_kept_raw_with_its_name():
    text = filter_text([rule_xml([], name="odd")]).replace("<SoundId>6</SoundId>", "<SoundId>6</SoundId>\r\n      <Extra>1</Extra>")
    doc = parse_filter(text)
    assert doc["rules"][0]["name"] == "odd" and "raw" in doc["rules"][0]
    assert render_filter(doc) == text


def test_rejects_other_filter_versions():
    with pytest.raises(ValueError, match="lootFilterVersion 8"):
        parse_filter(filter_text([]).replace("<lootFilterVersion>9<", "<lootFilterVersion>8<"))
    with pytest.raises(ValueError, match="lootFilterVersion 10"):
        parse_filter(filter_text([]).replace("<lootFilterVersion>9<", "<lootFilterVersion>10<"))


def test_a_filter_the_game_just_created_opens_and_saves_as_version_9():
    # The game writes lootFilterVersion 0 into the filters it creates, in the current layout.
    text = filter_text([rule_xml([], name="mine")]).replace("<lootFilterVersion>9<", "<lootFilterVersion>0<")
    doc = parse_filter(text)
    assert doc["rules"][0]["name"] == "mine" and "raw" not in doc["rules"][0]
    assert "<lootFilterVersion>9</lootFilterVersion>" in render_filter(doc)
    # an old one, as the game upgrades it (level fields, beam ids, renamed types): refused
    for old in ("<BeamId>3</BeamId>", "<type>HIGHLIGHT</type>", "<minLvl>5</minLvl>", "TWO_HANDED_POLEARM"):
        with pytest.raises(ValueError, match="lootFilterVersion 0"):
            parse_filter(text.replace("<SoundId>", old + "<SoundId>", 1))


def test_generated_rules_decode_like_editor_rules():
    rule = Rule(name="[L] x", group="g", spec=RuleSpec(color=14, emphasized=True), unique_ids=None, rarity="MAGIC RARE",
                affix_ids=[1, 2], affix_min=2, item_types=["BOW"], sub_types=[0, 4], char_level=(10, 19))
    (decoded,) = parse_rule_blocks([render_rule(rule)])
    assert [c["type"] for c in decoded["conditions"]] == ["SubTypeCondition", "RarityCondition", "AffixCondition",
                                                          "CharacterLevelCondition"]
    assert decoded["conditions"][0] == {"type": "SubTypeCondition", "types": ["BOW"], "subtypes": [0, 4]}
    assert decoded["conditions"][2]["min_on_same_item"] == 2
    assert decoded["conditions"][3] == {"type": "CharacterLevelCondition", "min": 10, "max": 19}
    # and the editor writes it back exactly as filterxml rendered it
    doc = {"header": {"name": "F"}, "rules": [decoded]}
    assert render_rule(rule) in render_filter(doc)
