"""Placing a generated section (leveling, idols) in an existing filter.

A section is recognised by its rules' name prefix, so generating again replaces it in place.
Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuleInfo:
    name: str
    separator: bool      # condition-less rule (section header or a catch-all)
    catch_all: bool      # enabled, condition-less HIDE rule


def _heading(r: RuleInfo, word: str) -> bool:
    return r.separator and not r.catch_all and word in r.name.upper()


def insert_position(infos: list[RuleInfo], prefix: str, section: str = "LEVELING", fallback: str | None = "bottom",
                    after: str | None = None, before: str | None = None) -> tuple[list[int], int | None]:
    """(indices of the previous section's rules to remove, index in the remaining list to insert at).

    Replaces a previous section in place; else goes right after the section headed by a
    separator whose name contains `after` (it runs until the next condition-less rule); else
    directly under a separator whose name contains `section`; else right above one whose name
    contains `before`; else at the top (fallback "top"), above a bottom catch-all hide rule /
    at the bottom (fallback "bottom"), or nowhere (fallback None: position None)."""
    old = [i for i, r in enumerate(infos) if r.name.startswith(prefix)]
    if old:
        return old, old[0]
    if after:
        for i, r in enumerate(infos):
            if _heading(r, after):
                j = i + 1
                while j < len(infos) and not infos[j].separator:
                    j += 1
                return [], j
    for i, r in enumerate(infos):
        if _heading(r, section):
            return [], i + 1
    if before:
        for i, r in enumerate(infos):
            if _heading(r, before):
                return [], i
    if fallback is None:
        return [], None
    if fallback == "top":
        return [], 0
    if infos and infos[-1].catch_all:
        return [], len(infos) - 1
    return [], len(infos)


def place(items: list, infos: list[RuleInfo], new: list, prefix: str, section: str = "LEVELING",
          fallback: str = "bottom", after: str | None = None, before: str | None = None) -> tuple[list, int, int]:
    """items with the old section (by name prefix) replaced by `new`. Returns (items, removed, position)."""
    old, at = insert_position(infos, prefix, section, fallback, after, before)
    gone = set(old)
    kept = [x for i, x in enumerate(items) if i not in gone]
    return kept[:at] + list(new) + kept[at:], len(old), at


# Where each generated section goes in a filter that doesn't have it yet (and where
# reorder_generated puts it back): place() keyword arguments.
IDOL_PLACEMENT = {"section": "IDOL", "after": "SHATTER", "before": "UNIQUE", "fallback": "top"}   # after shatter, before uniques
LEVELING_PLACEMENT = {"section": "LEVELING", "fallback": "bottom"}   # above the bottom hide-everything rule
BIS_PLACEMENT = {"section": "BIS", "fallback": "top"}


def reorder_generated(rules: list[dict], prefixes: dict[str, str]) -> tuple[list[dict], list[str]]:
    """The generated sections - BiS rules, the idol section, the leveling section; prefixes:
    {"bis", "idols", "leveling"} -> rule name prefix - moved back to where they belong (see the
    placements), each only when the filter has that spot. Returns (rules, labels of sections moved)."""
    placements = (("BiS rules", prefixes.get("bis"), BIS_PLACEMENT), ("idol section", prefixes.get("idols"), IDOL_PLACEMENT),
                  ("leveling section", prefixes.get("leveling"), LEVELING_PLACEMENT))
    out, moved = list(rules), []
    for label, prefix, where in placements:
        if not prefix:
            continue
        mine = [i for i, r in enumerate(out) if "raw" not in r and (r.get("name") or "").startswith(prefix)]
        if not mine:
            continue
        block = [out[i] for i in mine]
        rest = [r for i, r in enumerate(out) if i not in set(mine)]
        infos = doc_infos(rest)
        # its own spot only: a "bottom" section's is above a bottom catch-all hide rule
        fallback = "bottom" if where["fallback"] == "bottom" and infos and infos[-1].catch_all else None
        _, at = insert_position(infos, prefix, **{**where, "fallback": fallback})
        if at is None:   # no spot for it in this filter: leave it where it is
            continue
        new = rest[:at] + block + rest[at:]
        if [id(r) for r in new] != [id(r) for r in out]:
            moved.append(label)
        out = new
    return out, moved


def doc_infos(rules: list[dict]) -> list[RuleInfo]:
    """RuleInfo for the editor's rule dicts (filterdoc format)."""
    return [RuleInfo(name=r.get("name", ""), separator="raw" not in r and not r["conditions"],
                     catch_all="raw" not in r and not r["conditions"] and r["enabled"] and r["type"] == "HIDE")
            for r in rules]
