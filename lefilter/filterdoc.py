"""Editable model of a whole loot filter: XML <-> JSON-friendly dicts (the editor's format).

Unlike filterxml (which carries base-filter rules as opaque text), this decodes every
rule and condition. Writing reproduces the game's own serialization byte for byte
(element order, 2-space indent, `<x />`, `i:nil`, CRLF), so an unedited filter
round-trips unchanged. A condition or rule whose layout isn't recognised is kept as
raw XML ({"type": ..., "raw": "..."} / {"raw": "..."}) and written back as-is.

Rules are listed in in-game order (top first); the XML stores them bottom-up.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .gamedata import CLASSES, FACTIONS, FLAG_CONDITIONS, RARITIES, check_filter_version, flags_to_xml

XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSI = f"{{{XSI_NS}}}"
NL = "\r\n"
LOOT_FILTER_VERSION = 9

HEADER_TAGS = ["name", "filterIcon", "filterIconColor", "description", "lastModifiedInVersion",
               "lootFilterVersion", "rules"]
RULE_TAGS = ["type", "conditions", "recolor", "color", "isEnabled", "levelDependent_deprecated",
             "minLvl_deprecated", "maxLvl_deprecated", "emphasized", "nameOverride", "SoundId", "MapIconId",
             "BeamOverride", "BeamSizeOverride", "BeamColorOverride", "Order"]
POTENTIAL_FIELDS = [("lp_min", "MinLegendaryPotential"), ("lp_max", "MaxLegendaryPotential"),
                    ("ww_min", "MinWeaversWill"), ("ww_max", "MaxWeaversWill"),
                    ("wt_min", "MinWeaversTouch"), ("wt_max", "MaxWeaversTouch"),
                    ("fp_min", "MinForgingPotential"), ("fp_max", "MaxForgingPotential")]
# Field order from the class layouts; not seen in saved filters yet, so decoded only when they match.
AFFIX_COUNT_FIELDS = [("prefix_min", "minPrefixes"), ("prefix_max", "maxPrefixes"),
                      ("suffix_min", "minSuffixes"), ("suffix_max", "maxSuffixes")]


@dataclass
class Node:
    tag: str
    attrs: list[tuple[str, str]] = field(default_factory=list)
    text: str | None = None
    children: list[Node] = field(default_factory=list)

    def child_tags(self) -> list[str]:
        return [c.tag for c in self.children]

    def find(self, tag: str) -> Node:
        return next(c for c in self.children if c.tag == tag)


# --- generic XML node tree --------------------------------------------------------

def _attr_name(name: str) -> str:
    return "i:" + name[len(XSI):] if name.startswith(XSI) else name


def _from_et(el: ET.Element) -> Node:
    children = [_from_et(c) for c in el]
    return Node(tag=el.tag, attrs=[(_attr_name(k), v) for k, v in el.attrib.items()],
                text=None if children else el.text, children=children)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", NL)


def _write(node: Node, depth: int, out: list[str]) -> None:
    ind = "  " * depth
    attrs = "".join(f' {k}="{v}"' for k, v in node.attrs)
    if node.children:
        out.append(f"{ind}<{node.tag}{attrs}>")
        for c in node.children:
            _write(c, depth + 1, out)
        out.append(f"{ind}</{node.tag}>")
    elif node.text:
        out.append(f"{ind}<{node.tag}{attrs}>{_escape(node.text)}</{node.tag}>")
    else:
        out.append(f"{ind}<{node.tag}{attrs} />")


def node_to_xml(node: Node, depth: int = 0) -> str:
    out: list[str] = []
    _write(node, depth, out)
    return NL.join(out)


def xml_to_node(text: str) -> Node:
    """Parse a fragment written with the `i:` prefix (e.g. a raw condition)."""
    wrapped = f'<w xmlns:i="{XSI_NS}">{text}</w>'
    return _from_et(ET.fromstring(wrapped)).children[0]


def _leaf(tag: str, value) -> Node:
    if value is None:
        return Node(tag, [("i:nil", "true")])
    if isinstance(value, bool):
        value = "true" if value else "false"
    return Node(tag, text=str(value))


def _is_nil(n: Node) -> bool:
    return ("i:nil", "true") in n.attrs


def _int_or_none(n: Node) -> int | None:
    return None if _is_nil(n) else int(n.text)


def _bool(n: Node) -> bool:
    if n.text not in ("true", "false"):
        raise ValueError(f"<{n.tag}> is not a boolean: {n.text!r}")
    return n.text == "true"


# --- conditions -------------------------------------------------------------------

class _Unknown(Exception):
    """Condition layout not recognised: keep it raw."""


def _expect(node: Node, tags: list[str]) -> None:
    if node.child_tags() != tags:
        raise _Unknown


def _tokens(text: str | None, known: tuple[str, ...]) -> list[str]:
    tokens = (text or "").split()
    if any(t not in known for t in tokens):
        raise _Unknown
    return tokens


def decode_condition(node: Node) -> dict:
    ctype = dict(node.attrs).get("i:type", "")
    try:
        return {"type": ctype, **_decode_fields(ctype, node)}
    except (_Unknown, ValueError, TypeError, StopIteration):
        return {"type": ctype, "raw": node_to_xml(node)}


def _decode_fields(ctype: str, n: Node) -> dict:
    if [k for k, _ in n.attrs] != ["i:type"] or n.text:
        raise _Unknown
    if ctype == "RarityCondition":
        _expect(n, ["rarity"])
        tokens = (n.find("rarity").text or "").split()
        if tokens == ["NONE"]:
            tokens = []
        if any(t not in RARITIES for t in tokens):
            raise _Unknown
        return {"rarity": tokens}
    if ctype == "SubTypeCondition":
        _expect(n, ["type", "subTypes"])
        types, subs = n.find("type"), n.find("subTypes")
        if any(c.tag != "EquipmentType" for c in types.children) or any(c.tag != "int" for c in subs.children):
            raise _Unknown
        return {"types": [c.text for c in types.children], "subtypes": [int(c.text) for c in subs.children]}
    if ctype == "AffixCondition":
        _expect(n, ["affixes", "comparsion", "comparsionValue", "minOnTheSameItem", "combinedComparsion",
                    "combinedComparsionValue", "advanced"])
        aff = n.find("affixes")
        if any(c.tag != "int" for c in aff.children):
            raise _Unknown
        return {"affixes": [int(c.text) for c in aff.children],
                "comparsion": n.find("comparsion").text, "comparsion_value": int(n.find("comparsionValue").text),
                "min_on_same_item": int(n.find("minOnTheSameItem").text),
                "combined_comparsion": n.find("combinedComparsion").text,
                "combined_value": int(n.find("combinedComparsionValue").text),
                "advanced": _bool(n.find("advanced"))}
    if ctype == "CharacterLevelCondition":
        _expect(n, ["minimumLvl", "maximumLvl"])
        return {"min": int(n.find("minimumLvl").text), "max": int(n.find("maximumLvl").text)}
    if ctype == "PotentialCondition":
        _expect(n, [tag for _, tag in POTENTIAL_FIELDS])
        return {key: _int_or_none(n.find(tag)) for key, tag in POTENTIAL_FIELDS}
    if ctype == "ClassCondition":
        _expect(n, ["req"])
        text = n.find("req").text
        if text == "Any":
            return {"classes": list(CLASSES)}
        return {"classes": [] if text == "None" else _tokens(text, CLASSES)}
    if ctype == "UniqueModifiersCondition":
        uniques = []
        for u in n.children:
            if u.tag != "Uniques":
                raise _Unknown
            _expect(u, ["UniqueId", "Rolls"])
            rolls = []
            for r in u.find("Rolls").children:
                _expect(r, ["RollId", "Modifier"])
                m = r.find("Modifier")
                _expect(m, ["MinRoll", "MaxRoll"])
                rolls.append({"roll": int(r.find("RollId").text), "min": _int_or_none(m.find("MinRoll")),
                              "max": _int_or_none(m.find("MaxRoll"))})
            uniques.append({"id": int(u.find("UniqueId").text), "rolls": rolls})
        return {"uniques": uniques}
    if ctype == "CorruptionCondition":
        _expect(n, ["Corruption"])
        return {"corruption": n.find("Corruption").text}
    if ctype == "FactionCondition":
        _expect(n, ["EligibleFactions"])
        f = n.find("EligibleFactions")
        if any(c.tag != "FactionID" or c.text not in FACTIONS for c in f.children):
            raise _Unknown
        return {"factions": [c.text for c in f.children]}
    if ctype in FLAG_CONDITIONS:
        tag, known = FLAG_CONDITIONS[ctype]
        _expect(n, [tag])
        text = n.find(tag).text
        return {"flags": [] if text == "None" else _tokens(text, known)}
    if ctype == "AffixCountCondition":
        _expect(n, [tag for _, tag in AFFIX_COUNT_FIELDS] + ["sealedType"])
        return {**{key: _int_or_none(n.find(tag)) for key, tag in AFFIX_COUNT_FIELDS},
                "sealed": n.find("sealedType").text}
    if ctype == "LevelCondition":
        _expect(n, ["treshold", "type"])
        return {"threshold": int(n.find("treshold").text), "level_type": n.find("type").text}
    raise _Unknown


def encode_condition(c: dict) -> Node:
    ctype = c["type"]
    if "raw" in c:
        return xml_to_node(c["raw"])
    node = Node("Condition", [("i:type", ctype)])
    kids = node.children
    if ctype == "RarityCondition":
        kids.append(_leaf("rarity", flags_to_xml(c["rarity"], RARITIES, none="NONE")))
    elif ctype == "SubTypeCondition":
        kids += [Node("type", children=[_leaf("EquipmentType", t) for t in c["types"]]),
                 Node("subTypes", children=[_leaf("int", s) for s in c["subtypes"]])]
    elif ctype == "AffixCondition":
        kids += [Node("affixes", children=[_leaf("int", a) for a in c["affixes"]]),
                 _leaf("comparsion", c["comparsion"]), _leaf("comparsionValue", c["comparsion_value"]),
                 _leaf("minOnTheSameItem", c["min_on_same_item"]),
                 _leaf("combinedComparsion", c["combined_comparsion"]),
                 _leaf("combinedComparsionValue", c["combined_value"]), _leaf("advanced", c["advanced"])]
    elif ctype == "CharacterLevelCondition":
        kids += [_leaf("minimumLvl", c["min"]), _leaf("maximumLvl", c["max"])]
    elif ctype == "PotentialCondition":
        kids += [_leaf(tag, c.get(key)) for key, tag in POTENTIAL_FIELDS]
    elif ctype == "ClassCondition":
        kids.append(_leaf("req", flags_to_xml(c["classes"], CLASSES, none="None", everything="Any")))
    elif ctype == "UniqueModifiersCondition":
        for u in c["uniques"]:
            rolls = [Node("UniqueModifierWithRollId", children=[
                _leaf("RollId", r["roll"]),
                Node("Modifier", children=[_leaf("MinRoll", r["min"]), _leaf("MaxRoll", r["max"])])])
                for r in u.get("rolls", [])]
            kids.append(Node("Uniques", children=[_leaf("UniqueId", u["id"]), Node("Rolls", children=rolls)]))
    elif ctype == "CorruptionCondition":
        kids.append(_leaf("Corruption", c["corruption"]))
    elif ctype == "FactionCondition":
        kids.append(Node("EligibleFactions", children=[_leaf("FactionID", f) for f in c["factions"]]))
    elif ctype in FLAG_CONDITIONS:
        tag, known = FLAG_CONDITIONS[ctype]
        kids.append(_leaf(tag, " ".join(f for f in known if f in set(c["flags"])) or "None"))
    elif ctype == "AffixCountCondition":
        kids += [_leaf(tag, c.get(key)) for key, tag in AFFIX_COUNT_FIELDS]
        kids.append(_leaf("sealedType", c.get("sealed", "Any")))
    elif ctype == "LevelCondition":
        kids += [_leaf("treshold", c["threshold"]), _leaf("type", c["level_type"])]
    else:
        raise ValueError(f"cannot write condition type {ctype!r} without raw XML")
    return node


# --- rules ------------------------------------------------------------------------

def _raw_rule(node: Node) -> dict:
    """Unrecognised rule: kept verbatim; name/enabled are for display only."""
    t = {c.tag: c for c in node.children}
    name = t["nameOverride"].text if "nameOverride" in t else ""
    return {"raw": node_to_xml(node, 2), "name": name or "", "enabled": t.get("isEnabled", Node("")).text == "true"}


def decode_rule(node: Node) -> dict:
    if node.child_tags() != RULE_TAGS:
        return _raw_rule(node)
    t = {c.tag: c for c in node.children}
    try:
        return {
            "type": t["type"].text,
            "conditions": [decode_condition(c) for c in t["conditions"].children],
            "recolor": _bool(t["recolor"]),
            "color": int(t["color"].text),
            "enabled": _bool(t["isEnabled"]),
            "level_dependent": _bool(t["levelDependent_deprecated"]),
            "min_lvl": int(t["minLvl_deprecated"].text),
            "max_lvl": int(t["maxLvl_deprecated"].text),
            "emphasized": _bool(t["emphasized"]),
            "name": t["nameOverride"].text or "",
            "sound": int(t["SoundId"].text),
            "map_icon": int(t["MapIconId"].text),
            "beam_override": _bool(t["BeamOverride"]),
            "beam_size": t["BeamSizeOverride"].text,
            "beam_color": int(t["BeamColorOverride"].text),
        }
    except (ValueError, TypeError):
        return _raw_rule(node)


def encode_rule(r: dict, order: int) -> Node:
    if "raw" in r:
        node = xml_to_node(r["raw"])
        node.find("Order").text = str(order)
        return node
    return Node("Rule", children=[
        _leaf("type", r["type"]),
        Node("conditions", children=[encode_condition(c) for c in r["conditions"]]),
        _leaf("recolor", r["recolor"]), _leaf("color", r["color"]), _leaf("isEnabled", r["enabled"]),
        _leaf("levelDependent_deprecated", r.get("level_dependent", False)),
        _leaf("minLvl_deprecated", r.get("min_lvl", 0)), _leaf("maxLvl_deprecated", r.get("max_lvl", 0)),
        _leaf("emphasized", r["emphasized"]), _leaf("nameOverride", r["name"]),
        _leaf("SoundId", r["sound"]), _leaf("MapIconId", r["map_icon"]),
        _leaf("BeamOverride", r["beam_override"]), _leaf("BeamSizeOverride", r["beam_size"]),
        _leaf("BeamColorOverride", r["beam_color"]), _leaf("Order", order),
    ])


def new_rule(name: str = "", **fields) -> dict:
    """A rule as the in-game "Add Rule" button creates it (show, no conditions, default look)."""
    return {"type": "SHOW", "conditions": [], "recolor": False, "color": 0, "enabled": True,
            "level_dependent": False, "min_lvl": 0, "max_lvl": 0, "emphasized": False, "name": name,
            "sound": 0, "map_icon": 0, "beam_override": False, "beam_size": "NONE", "beam_color": 0, **fields}


# --- whole filter -----------------------------------------------------------------

def parse_filter(text: str) -> dict:
    """Filter XML (BOM optional) -> {"header": {...}, "rules": [...top first]}."""
    root = _from_et(ET.fromstring(text.lstrip("﻿")))
    if root.tag != "ItemFilter" or root.child_tags() != HEADER_TAGS:
        raise ValueError(f"not a loot filter this tool understands (elements: {root.child_tags()})")
    t = {c.tag: c for c in root.children}
    check_filter_version(int(t["lootFilterVersion"].text), text, LOOT_FILTER_VERSION)
    header = {"name": t["name"].text or "", "icon": int(t["filterIcon"].text),
              "icon_color": int(t["filterIconColor"].text), "description": t["description"].text or "",
              "version": t["lastModifiedInVersion"].text or ""}
    rules = [decode_rule(r) for r in t["rules"].children if r.tag == "Rule"]
    return {"header": header, "rules": list(reversed(rules))}


def render_filter(doc: dict) -> str:
    """{"header", "rules"} -> filter XML (no BOM; filterxml.write_filter adds it)."""
    h = doc["header"]
    rules = doc["rules"]
    root = Node("ItemFilter", [("xmlns:i", XSI_NS)], children=[
        _leaf("name", h["name"]), _leaf("filterIcon", h.get("icon", 0)),
        _leaf("filterIconColor", h.get("icon_color", 0)), _leaf("description", h.get("description", "")),
        _leaf("lastModifiedInVersion", h.get("version", "")), _leaf("lootFilterVersion", LOOT_FILTER_VERSION),
        Node("rules", children=[encode_rule(r, i) for i, r in reversed(list(enumerate(rules)))]),
    ])
    return node_to_xml(root)


def parse_rule_blocks(blocks: list[str]) -> list[dict]:
    """Rendered <Rule> blocks (filterxml.render_rule output) -> rule dicts."""
    return [decode_rule(xml_to_node(b.strip())) for b in blocks]


def is_separator(r: dict) -> bool:
    return "raw" not in r and not r["conditions"]
