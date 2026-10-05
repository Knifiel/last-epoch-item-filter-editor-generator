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
IDOL_PLACEMENT = {"section": "IDOL", "before": "UNIQUE", "fallback": "top"}   # right before the uniques
LEVELING_PLACEMENT = {"section": "LEVELING", "fallback": "bottom"}   # above the bottom hide-everything rule
# The leveling generator's endgame rares: right below the exalted & legendary section, else before the uniques
ENDGAME_PLACEMENT = {"section": "ENDGAME", "after": "EXALTED", "before": "UNIQUE", "fallback": "bottom"}
BIS_PLACEMENT = {"section": "BIS", "fallback": "top"}


def place_leveling(items: list, infos, leveling: list, endgame: list, prefix: str, endgame_prefix: str) -> tuple[list, int, int]:
    """items with the leveling section and its endgame rares section (by their prefixes) replaced by the new
    ones, each where its placement says; infos(items) -> their RuleInfos. Returns (items, rules removed,
    position of the leveling section)."""
    out, gone, _ = place(items, infos(items), endgame, endgame_prefix, **ENDGAME_PLACEMENT)
    out, removed, at = place(out, infos(out), leveling, prefix, **LEVELING_PLACEMENT)
    return out, gone + removed, at


# The top of a filter: the always-show rules, the shatter section (above the class hide rules, so
# its rules for other classes' affixes can fire: those affixes give an item their class's
# requirement), then the class hide rules (above every other rule, so other classes' items stay
# out of all of them). Entries: [(rule name, condition-less)].

def _leading(entries: list[tuple[str, bool]], top_names) -> int:
    at = 0
    while at < len(entries) and not entries[at][1] and entries[at][0] in top_names:
        at += 1
    return at


def _shatter_span(entries: list[tuple[str, bool]], start: int = 0) -> tuple[int, int] | None:
    """(first, end) of the first shatter section from `start`: a separator named like SHATTER and
    the rules under it up to the next condition-less rule."""
    for i in range(start, len(entries)):
        if entries[i][1] and "SHATTER" in entries[i][0].upper():
            j = i + 1
            while j < len(entries) and not entries[j][1]:
                j += 1
            return i, j
    return None


def class_hide_index(entries: list[tuple[str, bool]], top_names) -> int:
    """Where the class hide rules go in a filter without them: right below the always-show rules
    leading it and the shatter section, if that comes right after them."""
    at = _leading(entries, top_names)
    span = _shatter_span(entries, at)
    return span[1] if span and span[0] == at else at


def _entries(rules: list[dict]) -> list[tuple[str, bool]]:
    return [(r.get("name", ""), "raw" not in r and not r["conditions"]) for r in rules]


def place_class_hide(rules: list[dict], top_names, hide_names) -> list[dict]:
    """The class hide rules (named in hide_names) where class_hide_index says. The other rules
    keep their order."""
    is_hide = [("raw" not in r and r.get("name") in hide_names) for r in rules]
    rest = [r for r, h in zip(rules, is_hide) if not h]
    at = class_hide_index(_entries(rest), top_names)
    return rest[:at] + [r for r, h in zip(rules, is_hide) if h] + rest[at:]


def place_shatter(rules: list[dict], top_names, hide_names=()) -> list[dict]:
    """The shatter section moved right below the always-show rules leading the filter (class hide
    rules under it stay where they are). Unchanged without a shatter section."""
    keep = [i for i, r in enumerate(rules) if "raw" in r or r.get("name") not in hide_names]
    entries = _entries([rules[i] for i in keep])
    span = _shatter_span(entries)
    if span is None:
        return list(rules)
    block = {keep[i] for i in range(*span)}
    rest = [r for i, r in enumerate(rules) if i not in block]
    at = _leading(_entries(rest), top_names)
    return rest[:at] + [rules[i] for i in sorted(block)] + rest[at:]


def place_uniques(rules: list[dict], prefix: str, skip_names) -> list[dict]:
    """The generated unique & set block - the `prefix` rules but the always-show and class hide ones
    (skip_names) - moved right above the leveling section, else above the bottom catch-all hide
    rule: it's rarely edited, so the exalted, BiS ... sections come first. The user's own rules
    within its span move with it (unless another section's header sits in there: then only the
    generated rules move). Unchanged without such a spot."""
    named = lambda r: "raw" not in r and (r.get("name") or "")
    mine = [i for i, r in enumerate(rules) if named(r).startswith(prefix) and r.get("name") not in skip_names]
    if not prefix or not mine:
        return list(rules)
    span = range(mine[0], mine[-1] + 1)
    foreign = any("raw" not in rules[i] and not rules[i].get("conditions") and not named(rules[i]).startswith(prefix)
                  for i in span)
    take = (set(mine) if foreign else set(span)) - {i for i in span if rules[i].get("name") in skip_names}
    rest = [r for i, r in enumerate(rules) if i not in take]
    infos = doc_infos(rest)
    fallback = "bottom" if infos and infos[-1].catch_all else None
    _, at = insert_position(infos, "\0", section="\0", before="LEVELING", fallback=fallback)
    if at is None:
        return list(rules)
    return rest[:at] + [rules[i] for i in sorted(take)] + rest[at:]


def reorder_generated(rules: list[dict], prefixes: dict[str, str], top_names=(), hide_names=()) -> tuple[list[dict], list[str]]:
    """The generated sections moved back to where they belong: the unique & set block (prefixes
    "uniques", see place_uniques) first, then BiS rules, the idol section, the leveling section and
    its endgame rares ({"bis", "idols", "leveling", "endgame"} -> rule name prefix; see the placements), each only when the
    filter has that spot; then the shatter section and the class hide rules to the top (see
    above). Returns (rules, labels of what moved)."""
    placements = (("BiS rules", prefixes.get("bis"), BIS_PLACEMENT), ("idol section", prefixes.get("idols"), IDOL_PLACEMENT),
                  ("leveling section", prefixes.get("leveling"), LEVELING_PLACEMENT),
                  ("endgame rares section", prefixes.get("endgame"), ENDGAME_PLACEMENT))
    out, moved = list(rules), []
    if prefixes.get("uniques"):
        new = place_uniques(out, prefixes["uniques"], set(top_names) | set(hide_names))
        if [id(r) for r in new] != [id(r) for r in out]:
            moved.append("unique section")
        out = new
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
    top_names, hide_names = set(top_names), set(hide_names)
    for label, step in (("shatter section", place_shatter), ("class hide rules", place_class_hide)):
        new = step(out, top_names, hide_names)
        if [id(r) for r in new] != [id(r) for r in out]:
            moved.append(label)
        out = new
    return out, moved


def doc_infos(rules: list[dict]) -> list[RuleInfo]:
    """RuleInfo for the editor's rule dicts (filterdoc format)."""
    return [RuleInfo(name=r.get("name", ""), separator="raw" not in r and not r["conditions"],
                     catch_all="raw" not in r and not r["conditions"] and r["enabled"] and r["type"] == "HIDE")
            for r in rules]
