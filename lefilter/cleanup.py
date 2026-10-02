"""Freeing rule slots in a filter (the game allows 200 rules) by removing rules that stop
mattering: decorative section separators, the campaign leveling rules once the campaign is
done, and the generated rules for the most common uniques at low LP.

Works on the editor's rule dicts (filterdoc format). Each removal returns the kept rules and
the names of the removed ones.

Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

from .rules import categorize, plan_rules

COMMON_CATEGORIES = ("common", "uncommon")
COMMON_LPL_BELOW = 60   # the template's common / uncommon groups split at LPL 60: the low half goes
COMMON_MAX_LP = 2       # rules for items with up to 2 LP (3 LP+ is caught by ANY UNIQUE above them)


def _parsed(r: dict) -> bool:
    return "raw" not in r


def is_separator(r: dict) -> bool:
    """A decorative rule: no conditions and switched off, so it never matches anything."""
    return _parsed(r) and not r["conditions"] and not r["enabled"]


def _cond(r: dict, ctype: str) -> dict | None:
    return next((c for c in r["conditions"] if c["type"] == ctype and "raw" not in c), None)


def _remove(rules: list[dict], gone: set[int]) -> tuple[list[dict], list[str]]:
    """Drop the rules at `gone`, plus the separator heading any section all of whose rules went."""
    gone = set(gone)
    head = None
    members: dict[int, list[int]] = {}
    for i, r in enumerate(rules):
        if is_separator(r):
            head = i
            members[i] = []
        elif head is not None and not (_parsed(r) and not r["conditions"]):   # a bottom catch-all isn't the section's
            members[head].append(i)
    gone |= {h for h, idx in members.items() if idx and set(idx) <= gone}
    return ([r for i, r in enumerate(rules) if i not in gone],
            [rules[i].get("name") or "(unnamed)" for i in sorted(gone)])


def remove_separators(rules: list[dict]) -> tuple[list[dict], list[str]]:
    return _remove(rules, {i for i, r in enumerate(rules) if is_separator(r)})


def remove_leveling(rules: list[dict], prefix: str = "[L] ", cap: int = 60) -> tuple[list[dict], list[str]]:
    """The generated leveling section (rules named with `prefix`) and every other rule a
    Character Level condition switches off before level `cap`: after the campaign they never
    match again."""
    def campaign(r: dict) -> bool:
        if prefix and r.get("name", "").startswith(prefix):
            return True
        lvl = _cond(r, "CharacterLevelCondition") if _parsed(r) else None
        return lvl is not None and lvl["max"] < cap
    return _remove(rules, {i for i, r in enumerate(rules) if campaign(r)})


def remove_common_uniques(rules: list[dict], config: dict, uniques: list[dict]) -> tuple[list[dict], list[str]]:
    """Generated unique rules (named with [filter].rule_prefix, build slots excluded) that only
    list common / uncommon uniques below LPL 60 - random drops, so no boss or quest uniques -
    and that show items from 0, 1 or 2 LP on."""
    prefix = config.get("filter", {}).get("rule_prefix", "")
    thresholds = {k: float(v) for k, v in config.get("rarity", {}).items()}
    slots = {r.name for r in plan_rules(config, uniques).rules if r.unique_ids == []}
    common = {u["id"] for u in uniques
              if categorize(u, thresholds) in COMMON_CATEGORIES and u["lpl"] < COMMON_LPL_BELOW}

    def low_common(r: dict) -> bool:
        name = r.get("name", "")
        if not _parsed(r) or not prefix or not name.startswith(prefix) or name in slots:
            return False
        listed = _cond(r, "UniqueModifiersCondition")
        if not listed or not listed["uniques"] or not {u["id"] for u in listed["uniques"]} <= common:
            return False
        lp = _cond(r, "PotentialCondition")
        return lp is None or lp.get("lp_min") is None or lp["lp_min"] <= COMMON_MAX_LP
    return _remove(rules, {i for i, r in enumerate(rules) if low_common(r)})
