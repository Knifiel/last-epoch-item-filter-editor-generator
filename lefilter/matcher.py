"""Which rule of a filter catches an item: the game's matching logic, for the editor's item tester.

Mirrors ItemFilter.Match / Rule.Match / *Condition.Match (LE.dll): rules are checked from
the top, the first enabled rule whose conditions ALL match decides (show/hide + look);
an item no rule matches is shown with its default look. All Affix conditions of a rule
are evaluated together and must each match. An Item Type condition with one type checks
its bases; with several types, bases are ignored.

Items are dicts: {type, subtype, rarity, unique, affixes: [{id, tier}], lp, ww, wt, fp,
corrupted, faction}. Not modelled: unique roll ranges, sealed affixes, idol altars.
"""
from __future__ import annotations

from .gamedata import CLASS_BITS, CLASSES


class Context:
    """Game-data lookups the conditions need."""

    def __init__(self, data: dict):
        self.affixes = {a["id"]: a for a in data["affixes"]}
        self.uniques = {u["id"]: u for u in data["uniques"]}
        self.subtypes = {(b["type"], s["id"]): s for b in data["bases"] for s in b["subtypes"]}

    def affix_name(self, aid: int) -> str:
        a = self.affixes.get(aid)
        return a["name"] if a else f"affix {aid}"


def item_rarity(item: dict) -> str:
    """The rarity flag a Rarity condition sees: magic/rare items with a T6+ affix are exalted."""
    r = item.get("rarity", "NORMAL")
    if r in ("MAGIC", "RARE") and any(a.get("tier", 1) >= 6 for a in item.get("affixes", [])):
        return "EXALTED"
    return r


def _cmp(op: str, value: int, target: int) -> bool:
    return {"ANY": True, "EQUAL": value == target, "LESS": value < target, "LESS_OR_EQUAL": value <= target,
            "MORE": value > target, "MORE_OR_EQUAL": value >= target}.get(op, True)


def _in_range(value, lo, hi) -> bool:
    return value is not None and (lo is None or value >= lo) and (hi is None or value <= hi)


def _affix_condition(c: dict, item: dict, ctx: Context) -> tuple[bool, str]:
    wanted = set(c["affixes"])
    hits = [a for a in item.get("affixes", [])
            if (not wanted or a["id"] in wanted)
            and (not c["advanced"] or _cmp(c["comparsion"], a.get("tier", 1), c["comparsion_value"]))]
    need = c["min_on_same_item"]
    if len(hits) < need:
        return False, f"{len(hits)} of the listed affixes on the item, needs {need}"
    names = ", ".join(f"{ctx.affix_name(a['id'])} T{a.get('tier', 1)}" for a in hits) or "(any)"
    if c["advanced"] and c["combined_comparsion"] != "ANY":
        total = sum(a.get("tier", 1) for a in hits)
        if not _cmp(c["combined_comparsion"], total, c["combined_value"]):
            return False, f"combined tier {total} is not {c['combined_comparsion']} {c['combined_value']}"
    return True, f"has {names}"


def match_condition(c: dict, item: dict, level: int, ctx: Context) -> tuple[bool | None, str]:
    """(matched, explanation); matched None = can't evaluate (raw/unknown condition)."""
    t = c["type"]
    if "raw" in c:
        return None, f"{t}: not evaluated (unrecognised layout)"
    sub = ctx.subtypes.get((item.get("type"), item.get("subtype")))
    if t == "RarityCondition":
        r = item_rarity(item)
        return r in c["rarity"], f"rarity {r}" + ("" if r in c["rarity"] else f" not in {' '.join(c['rarity']) or 'none'}")
    if t == "SubTypeCondition":
        types = c["types"]
        if not types:
            return False, "no item type selected"
        if item.get("type") not in types:
            return False, f"{item.get('type')} is not {', '.join(types)}"
        if len(types) == 1 and c["subtypes"] and item.get("subtype") not in c["subtypes"]:
            return False, f"base {sub['name'] if sub else item.get('subtype')} not selected"
        return True, "item type matches"
    if t == "CharacterLevelCondition":
        ok = c["min"] <= level <= c["max"]
        return ok, f"character level {level} {'in' if ok else 'outside'} {c['min']}-{c['max']}"
    if t == "ClassCondition":
        req = sum(CLASS_BITS[x] for x in c["classes"])
        item_req = sub["class"] if sub else 0
        if not req:
            return True, "no class selected"
        if not item_req:
            return False, "item is not class-specific"
        ok = req & item_req == item_req
        return ok, f"item class {'/'.join(x for x in CLASSES if item_req & CLASS_BITS[x])}"
    if t == "UniqueModifiersCondition":
        uid = item.get("unique")
        ok = uid is not None and uid in {u["id"] for u in c["uniques"]}
        return ok, ("unique listed" if ok else "unique not listed") + " (roll ranges not checked)"
    if t == "PotentialCondition":
        return _potential(c, item)
    if t == "CorruptionCondition":
        corrupted = bool(item.get("corrupted"))
        ok = {"Any": True, "OnlyCorrupted": corrupted, "OnlyUncorrupted": not corrupted}.get(c["corruption"], True)
        return ok, "corrupted" if corrupted else "not corrupted"
    if t == "FactionCondition":
        f = item.get("faction")
        return f in c["factions"], f"faction {f or 'none'}"
    if t == "AffixCountCondition":
        affixes = [ctx.affixes.get(a["id"]) for a in item.get("affixes", [])]
        pre = sum(1 for a in affixes if a and a["prefix"])
        suf = sum(1 for a in affixes if a and not a["prefix"])
        ok = _range_ok(pre, c.get("prefix_min"), c.get("prefix_max")) and _range_ok(suf, c.get("suffix_min"), c.get("suffix_max"))
        return ok, f"{pre} prefixes, {suf} suffixes"
    if t == "LevelCondition":
        item_level = sub["level"] if sub else 0
        return _level_condition(c, item_level, level)
    if t in ("KeysCondition", "CraftingMaterialsCondition", "ResonancesCondition", "WovenEchoesCondition",
             "GlyphCondition", "RuneCondition"):
        return False, "only matches non-equipment items"
    if t == "AffixCondition":
        return _affix_condition(c, item, ctx)
    return None, f"{t}: not evaluated"


def _range_ok(value, lo, hi) -> bool:
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def _potential(c: dict, item: dict) -> tuple[bool, str]:
    lp, ww = item.get("lp"), item.get("ww")
    has_lp = c.get("lp_min") is not None or c.get("lp_max") is not None
    has_ww = c.get("ww_min") is not None or c.get("ww_max") is not None
    ok, why = True, []
    if ww is not None and has_ww:
        ok = _in_range(ww, c.get("ww_min"), c.get("ww_max"))
        why.append(f"{ww} WW")
    elif has_lp:
        ok = _in_range(lp, c.get("lp_min"), c.get("lp_max"))
        why.append(f"{lp if lp is not None else 'no'} LP")
    elif has_ww:
        ok = False
        why.append("no WW")
    for key, label in (("wt", "WT"), ("fp", "FP")):
        if c.get(f"{key}_min") is not None or c.get(f"{key}_max") is not None:
            v = item.get(key)
            ok = ok and _in_range(v, c.get(f"{key}_min"), c.get(f"{key}_max"))
            why.append(f"{v if v is not None else 'no'} {label}")
    return ok, ", ".join(why) or "no potential range set"


def _level_condition(c: dict, item_level: int, level: int) -> tuple[bool, str]:
    t, n = c["level_type"], c["threshold"]
    ok = {"BELOW_LEVEL": item_level < n, "ABOVE_LEVEL": item_level > n,
          "MAX_LVL_BELOW_CHARACTER_LEVEL": item_level <= level - n,
          "HIGHEST_USABLE_LEVEL": item_level <= level}.get(t, True)
    return ok, f"item level {item_level} (approximate)"


def match_rule(rule: dict, item: dict, level: int, ctx: Context) -> dict:
    if "raw" in rule:
        return {"matched": None, "checks": [[None, "rule layout not recognised; not evaluated"]]}
    checks = [match_condition(c, item, level, ctx) for c in rule["conditions"]]
    if any(ok is False for ok, _ in checks):
        matched = False
    elif any(ok is None for ok, _ in checks):
        matched = None
    else:
        matched = True
    return {"matched": matched, "checks": [list(c) for c in checks]}


def evaluate(rules: list[dict], item: dict, level: int, ctx: Context) -> dict:
    """{"index": first enabled matching rule or None, "results": per-rule match_rule (+ enabled)}."""
    results, index = [], None
    for i, r in enumerate(rules):
        res = match_rule(r, item, level, ctx)
        res["enabled"] = bool(r.get("enabled", True)) if "raw" not in r else True
        results.append(res)
        if index is None and res["enabled"] and res["matched"]:
            index = i
    return {"index": index, "results": results, "rarity": item_rarity(item)}

