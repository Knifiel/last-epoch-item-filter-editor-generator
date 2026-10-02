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


def insert_position(infos: list[RuleInfo], prefix: str, section: str = "LEVELING",
                    fallback: str = "bottom") -> tuple[list[int], int]:
    """(indices of the previous section's rules to remove, index in the remaining list to insert at).

    Replaces a previous section in place; else goes directly under a separator whose name
    contains `section`; else at the top (fallback "top") or above a bottom catch-all hide
    rule / at the bottom (fallback "bottom")."""
    old = [i for i, r in enumerate(infos) if r.name.startswith(prefix)]
    if old:
        return old, old[0]
    for i, r in enumerate(infos):
        if r.separator and not r.catch_all and section in r.name.upper():
            return [], i + 1
    if fallback == "top":
        return [], 0
    if infos and infos[-1].catch_all:
        return [], len(infos) - 1
    return [], len(infos)


def place(items: list, infos: list[RuleInfo], new: list, prefix: str, section: str = "LEVELING",
          fallback: str = "bottom") -> tuple[list, int, int]:
    """items with the old section (by name prefix) replaced by `new`. Returns (items, removed, position)."""
    old, at = insert_position(infos, prefix, section, fallback)
    gone = set(old)
    kept = [x for i, x in enumerate(items) if i not in gone]
    return kept[:at] + list(new) + kept[at:], len(old), at


def doc_infos(rules: list[dict]) -> list[RuleInfo]:
    """RuleInfo for the editor's rule dicts (filterdoc format)."""
    return [RuleInfo(name=r.get("name", ""), separator="raw" not in r and not r["conditions"],
                     catch_all="raw" not in r and not r["conditions"] and r["enabled"] and r["type"] == "HIDE")
            for r in rules]
