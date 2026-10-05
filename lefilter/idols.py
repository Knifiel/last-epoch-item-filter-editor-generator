"""Idol rule generator: one show rule per idol kind for idols with the wanted affixes.

Idol kinds, from the game data (sizes are width x height, as the game names them):
- all-class idols: 1x1 Small (Eterran), 1x1 Minor (Lagonian), 2x1 Humble, 1x2 Stout;
- their Weaver versions ("enhanced"): the same pool plus the Weaver Idol affixes;
- class idols: 3x1 Grand, 1x3 Large, 4x1 Ornate, 1x4 Huge, 2x2 Adorned - one base per class;
- Omen idols: class 3x1 / 1x3 bases that also roll the 4x1, 1x4 and 2x2 affixes (corrupted ones too).
Heretical (enchanted) idols are crafted from class idols and never drop, but they are
separate bases: each class idol's rule also lists its heretical base, so one thrown out
of the inventory is shown like its normal version, and its pool also offers the Enchanted
Idol affixes (only heretical idols carry them).

An affix is in a kind's pool when it can roll on the idol's type (Omen: or on 4x1/1x4/2x2)
and its class restriction allows the idol: a class idol needs that class's bit, an
all-class idol the NonSpecific bit (no restriction counts for both). Corrupted and Enchanted
affixes are listed as groups of their own: only corrupted / heretical idols carry them.

Idol altars get a rule of their own: the preferred altar bases with any of the preferred
altar affixes (either side may be left open), with a beam; below it, optionally, a plainer
rule showing every other altar.

Each idol kind and the altar take one or more rulesets (picks), each making a rule of its own, so
an item shows when any of them matches: separate combinations (A + B, or C + D) that one list
would mix (A + C). A kind's rules needing both affixes go above those needing one (an idol with
both gets their look). A ruleset another one already covers - every item it would show, the
other shows the same way; of identical ones the first - makes no rule (a warning says so).

Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gamedata import (AFFIX_CLASS_BITS, AFFIX_NONSPECIFIC, CLASS_BITS, CLASS_IDOL_TYPES, CLASSES, COMMON_IDOL_TYPES,
                       OMEN_EXTRA_TYPES, TYPE_IDS, WEAVER_IDOL_SUBTYPES)
from .rules import RULE_KEYS, ConfigError, Rule, RuleSpec, _check_keys

IDOL_TYPES = COMMON_IDOL_TYPES + CLASS_IDOL_TYPES
ALTAR_TYPE = "IDOL_ALTAR"
ENCHANTED_SPECIAL, WEAVER_SPECIAL, CORRUPTED_SPECIAL = 4, 5, 6     # AffixList specialAffixType
STYLE_DEFAULTS = {
    "both": {"color": 15, "emphasized": True},   # rules asking for 2 wanted affixes
    "single": {"color": 15},                     # rules asking for 1
    "altar": {"color": 15, "emphasized": True, "beam_size": "LARGE", "beam_color": 19},   # the preferred idol altars
    "altar_other": {"color": 15},                # every other altar
}
OPTION_KEYS = {"picks", "altar", "show_other_altars", "rule_prefix", "header", "hide_others", "style"}


@dataclass
class IdolKind:
    key: str                 # "IDOL_1x3/Sentinel", "IDOL_2x1/weaver", "IDOL_3x1/Sentinel/omen"
    type: str                # EquipmentType
    type_id: int
    width: int
    height: int
    character_class: str     # "" = every class
    variant: str             # "" | "weaver" | "omen"
    label: str               # "1x3 Sentinel", "2x1 Humble Weaver" ...
    subtypes: list[int]
    base_names: list[str]
    pool: list[dict] = field(default_factory=list)   # [{"id", "name", "group"}]
    heretical_subtypes: list[int] = field(default_factory=list)   # its heretical (enchanted) version
    heretical_names: list[str] = field(default_factory=list)

    @property
    def all_subtypes(self) -> list[int]:
        return self.subtypes + self.heretical_subtypes


def _size(type_name: str) -> tuple[int, int]:
    w, h = re.search(r"(\d)x(\d)", type_name).groups()
    return int(w), int(h)


def _pool(type_name: str, character_class: str, variant: str, affixes: list[dict], heretical: bool = False) -> list[dict]:
    own = TYPE_IDS[type_name]
    types = {own} | ({TYPE_IDS[t] for t in OMEN_EXTRA_TYPES} if variant == "omen" else set())
    allowed = AFFIX_CLASS_BITS[character_class] if character_class else AFFIX_NONSPECIFIC
    out = []
    for a in affixes:
        rolls = set(a["rolls_on"])
        if a["special"] == 0 and rolls & types and (not a["class"] or a["class"] & allowed):
            group = a["category"]
        elif a["special"] == WEAVER_SPECIAL and variant == "weaver" and own in rolls:
            group = "Weaver Idols"
        elif a["special"] == ENCHANTED_SPECIAL and heretical and own in rolls and (not a["class"] or a["class"] & allowed):
            group = "Enchanted (heretical idols only)"
        elif a["special"] == CORRUPTED_SPECIAL and rolls & types:
            group = "Corrupted (corrupted idols only)"
        else:
            continue
        out.append({"id": a["id"], "name": a["name"], "group": group})
    order = {"General Idols": 0, "Weaver Idols": 2, "Enchanted (heretical idols only)": 2}
    return sorted(out, key=lambda a: (order.get(a["group"], 3 if a["group"].startswith("Corrupted") else 1),
                                      a["group"], a["name"]))


def idol_kinds(data: dict) -> list[IdolKind]:
    """Every idol kind that drops: all-class, Weaver, then per class the class sizes and Omen."""
    bases = {b["type"]: b for b in data["bases"]}
    kinds = []

    def add(type_name: str, cls: str, variant: str, subs: list[dict], label: str, heretical=()) -> None:
        if not subs:
            return
        w, h = _size(type_name)
        kinds.append(IdolKind(
            key="/".join(x for x in (type_name, cls, variant) if x), type=type_name, type_id=TYPE_IDS[type_name],
            width=w, height=h, character_class=cls, variant=variant, label=label,
            subtypes=[s["id"] for s in subs], base_names=[s["name"] for s in subs],
            pool=_pool(type_name, cls, variant, data["affixes"], bool(heretical)),
            heretical_subtypes=[s["id"] for s in heretical], heretical_names=[s["name"] for s in heretical]))

    for variant in ("", "weaver"):
        for t in COMMON_IDOL_TYPES:
            base = bases[t]
            weaver_sub = WEAVER_IDOL_SUBTYPES[t]
            if variant:
                subs = [s for s in base["subtypes"] if s["id"] == weaver_sub]
            else:
                subs = [s for s in base["subtypes"] if s["drops"] and s["id"] != weaver_sub]
            name = base["name"].replace(" Idol", "")
            add(t, "", variant, subs, f"{_size_text(t)} {name}" + (" Weaver" if variant else ""))
    for cls in CLASSES:
        bit = CLASS_BITS[cls]
        for t in CLASS_IDOL_TYPES:
            subs = [s for s in bases[t]["subtypes"] if s["drops"] and s["class"] == bit and not s.get("omen")]
            heretical = [s for s in bases[t]["subtypes"] if s.get("heretical") and s["class"] == bit]
            add(t, cls, "", subs, f"{_size_text(t)} {cls}", heretical)
        for t in CLASS_IDOL_TYPES:
            subs = [s for s in bases[t]["subtypes"] if s["drops"] and s["class"] == bit and s.get("omen")]
            add(t, cls, "omen", subs, f"{_size_text(t)} {cls} Omen")
    return kinds


def _size_text(type_name: str) -> str:
    w, h = _size(type_name)
    return f"{w}x{h}"


@dataclass
class AltarKind:
    type_id: int
    bases: list[dict]                 # droppable altars: [{"id", "name", "level"}]
    pool: list[dict]                  # [{"id", "name", "group"}]


def altar_kind(data: dict) -> AltarKind | None:
    """Idol altar bases and the affixes they roll (corrupted ones as their own group)."""
    base = next((b for b in data["bases"] if b["type"] == ALTAR_TYPE), None)
    if not base:
        return None
    pool = []
    for a in data["affixes"]:
        if base["id"] not in a["rolls_on"] or a["special"] not in (0, CORRUPTED_SPECIAL):
            continue
        group = "Corrupted (corrupted altars only)" if a["special"] else a["category"]
        pool.append({"id": a["id"], "name": a["name"], "group": group})
    pool.sort(key=lambda a: (a["group"].startswith("Corrupted"), a["group"], a["id"]))
    bases = [{"id": s["id"], "name": s["name"], "level": s["level"]}
             for s in sorted(base["subtypes"], key=lambda s: (s["level"], s["id"])) if s["drops"]]
    return AltarKind(type_id=base["id"], bases=bases, pool=pool)


# --- options / rules --------------------------------------------------------------

EMPTY_ALTAR = {"bases": [], "affixes": []}


@dataclass
class IdolOptions:
    picks: dict[str, list[dict]] = field(default_factory=dict)   # kind key -> its rulesets [{"affixes": [ids], "min": 1|2}]
    altar: list[dict] = field(default_factory=lambda: [dict(EMPTY_ALTAR)])   # its rulesets [{"bases": subtypes, "affixes": ids}]
    show_other_altars: bool = True   # below the preferred altars, show every other altar
    rule_prefix: str = "[I] "
    header: str = "------- IDOLS (auto) -------"
    hide_others: bool = False     # hide every other normal/magic/rare/exalted idol below the section's rules
    style: dict = field(default_factory=dict)

    def spec(self, kind: str) -> RuleSpec:
        options = {**STYLE_DEFAULTS[kind], **self.style.get(kind, {})}
        _check_keys(options, RULE_KEYS - {"label", "lp_min", "lp_max", "ww_min", "ww_max"}, f"idol style.{kind}")
        return RuleSpec(**options)


def _rulesets(value) -> list[dict]:
    """A kind's rulesets: a list of them, or one table (how picks were kept before rulesets)."""
    return [value] if isinstance(value, dict) else list(value)


def parse_options(table: dict) -> IdolOptions:
    _check_keys(table, OPTION_KEYS, "idol options")
    opts = IdolOptions(**table)
    picks = {}
    for key, sets in opts.picks.items():
        picks[key] = []
        for pick in _rulesets(sets):
            _check_keys(pick, {"affixes", "min"}, f"idol pick {key}")
            if pick.get("min", 2) not in (1, 2):
                raise ConfigError(f"idol pick {key}: min must be 1 or 2 (idols carry two affixes)")
            picks[key].append({"affixes": list(pick.get("affixes", [])), "min": pick.get("min", 2)})
    opts.picks = picks
    altars = []
    for altar in _rulesets(opts.altar):
        _check_keys(altar, {"bases", "affixes"}, "idol altar")
        altars.append({"bases": list(altar.get("bases", [])), "affixes": list(altar.get("affixes", []))})
    opts.altar = altars or [dict(EMPTY_ALTAR)]
    bad = set(opts.style) - set(STYLE_DEFAULTS)
    if bad:
        raise ConfigError(f"idol style: unknown {sorted(bad)}; known: {', '.join(STYLE_DEFAULTS)}")
    return opts


@dataclass
class IdolPlan:
    rules: list[Rule]
    warnings: list[str]


def _number(i: int) -> str:
    """A ruleset's mark in its rule's name: none for the first, " #2" for the second..."""
    return f" #{i + 1}" if i else ""


def altar_picked(opts: IdolOptions) -> bool:
    return any(a["bases"] or a["affixes"] for a in opts.altar)


def redundant(rulesets: dict[int, object], covers) -> dict[int, int]:
    """The rulesets another one makes pointless: {index: index of a kept one that covers it}. rulesets:
    index -> what its rule takes (only those making a rule); covers(a, b): every item b's rule shows, a's
    shows the same way. Of rulesets covering each other (identical) the first is kept."""
    def above(y, x):
        return covers(rulesets[y], rulesets[x]) and (not covers(rulesets[x], rulesets[y]) or y < x)
    kept = [x for x in rulesets if not any(above(y, x) for y in rulesets if y != x)]
    return {x: next(y for y in kept if above(y, x)) for x in rulesets if x not in kept}


def _idol_covers(a: tuple[int, list], b: tuple[int, list]) -> bool:
    """(n, affixes): idols with n of b's affixes have n of a's (same n: same look)."""
    return a[0] == b[0] and set(b[1]) <= set(a[1])


def _altar_covers(a: tuple[list, list], b: tuple[list, list]) -> bool:
    """(bases, affixes), empty = any: every altar b takes, a takes."""
    return all(not wide or (narrow and set(narrow) <= set(wide)) for wide, narrow in zip(a, b))


def _skipped(label: str, skip: dict[int, int]) -> list[str]:
    return [f"{label}: ruleset {x + 1} makes no rule of its own: ruleset {y + 1} already shows everything it would"
            for x, y in sorted(skip.items())]


def plan_idols(opts: IdolOptions, kinds: list[IdolKind], altar: AltarKind | None = None) -> IdolPlan:
    p = opts.rule_prefix
    rules, warnings = [], []
    known = {k.key: k for k in kinds}
    for key in opts.picks:
        if key not in known:
            warnings.append(f"unknown idol kind {key!r} skipped")
    for kind in kinds:
        pool = {a["id"] for a in kind.pool}
        made = {}   # ruleset index -> (affixes needed, wanted affixes)
        for i, pick in enumerate(opts.picks.get(kind.key, [])):
            if not pick["affixes"]:
                continue
            wanted = [a for a in dict.fromkeys(pick["affixes"]) if a in pool]
            if len(wanted) < len(pick["affixes"]):
                warnings.append(f"{kind.label}: {len(pick['affixes']) - len(wanted)} picked affixes can't roll on it; left out")
            if wanted:
                made[i] = (min(pick["min"], len(wanted)) if len(wanted) > 1 else 1, wanted)
        skip = redundant(made, _idol_covers)
        warnings += _skipped(kind.label, skip)
        for i, (n, wanted) in sorted(((i, m) for i, m in made.items() if i not in skip), key=lambda x: -x[1][0]):
            rules.append(Rule(name=f"{p}{kind.label} idol{_number(i)} - {n}+ of {len(wanted)} wanted affixes", group="idols",
                              spec=opts.spec("both" if n >= 2 else "single"), unique_ids=None, rarity=None,
                              affix_ids=wanted, affix_min=n, item_types=[kind.type], sub_types=kind.all_subtypes))
    if altar and altar_picked(opts):
        made = {i: picked for i, a in enumerate(opts.altar) if (picked := _altar_picks(a, altar, warnings))}
        skip = redundant(made, _altar_covers)
        warnings += _skipped("Idol altar", skip)
        altars = [_altar_rule(opts, *made[i], i) for i in made if i not in skip]
        rules += altars
        if altars and opts.show_other_altars:
            rules.append(Rule(name=f"{p}Idol altar - all other altars", group="idols", spec=opts.spec("altar_other"),
                              unique_ids=None, rarity=None, item_types=[ALTAR_TYPE]))
    if opts.hide_others:
        rules.append(Rule(name=f"{p}Hide other idols", group="idols", spec=RuleSpec(action="hide"), unique_ids=None,
                          rarity="NORMAL MAGIC RARE EXALTED", item_types=list(IDOL_TYPES)))
    if rules and opts.header:
        rules.insert(0, Rule(name=f"{p}{opts.header}", group="idols", spec=RuleSpec(action="hide", enabled=False),
                             unique_ids=None, rarity=None))
    return IdolPlan(rules=rules, warnings=list(dict.fromkeys(warnings)))


def _altar_picks(pick: dict, altar: AltarKind, warnings: list[str]) -> tuple[list, list] | None:
    """An altar ruleset's (bases, affixes) that exist in this game version; None when it has neither."""
    known_bases, known_affixes = {b["id"] for b in altar.bases}, {a["id"] for a in altar.pool}
    bases = [b for b in dict.fromkeys(pick["bases"]) if b in known_bases]
    affixes = [a for a in dict.fromkeys(pick["affixes"]) if a in known_affixes]
    if len(bases) < len(pick["bases"]) or len(affixes) < len(pick["affixes"]):
        warnings.append("Idol altar: some picked altars or affixes don't exist in this game version; left out")
    return (bases, affixes) if bases or affixes else None


def _altar_rule(opts: IdolOptions, bases: list, affixes: list, i: int) -> Rule:
    """The rule of the altar's ruleset i."""
    what = " with ".join(x for x in ("preferred altars" if bases else "",
                                      f"1+ of {len(affixes)} preferred affixes" if affixes else "") if x)
    return Rule(name=f"{opts.rule_prefix}Idol altar{_number(i)} - {what}", group="idols", spec=opts.spec("altar"),
                unique_ids=None, rarity=None, affix_ids=affixes or None, item_types=[ALTAR_TYPE], sub_types=bases)


def _ruleset_number(rule: dict) -> int:
    """The ruleset a generated rule came from, by the "#2" in its name (none: the first)."""
    m = re.search(r" #(\d+) - ", rule["name"])
    return int(m.group(1)) if m else 1


def _in_order(numbered: list[tuple[int, dict]]) -> list[dict]:
    return [x for _, x in sorted(numbered, key=lambda x: x[0])]   # stable: unnumbered ones keep their order


def read_picks(rules: list[dict], prefix: str, kinds: list[IdolKind]) -> dict:
    """The options a previously generated idol section (editor rule dicts) was made with: each rule
    of a kind (or of the altar) a ruleset, in the order of the numbers in their names (#2 ...), else
    in theirs."""
    picks, hide_others, found = {}, False, False
    altar, show_other_altars = [], False
    for r in rules:
        if "raw" in r or not r.get("name", "").startswith(prefix):
            continue
        found = True
        sub = next((c for c in r["conditions"] if c["type"] == "SubTypeCondition" and "raw" not in c), None)
        aff = next((c for c in r["conditions"] if c["type"] == "AffixCondition" and "raw" not in c), None)
        if r["type"] == "HIDE" and sub and len(sub["types"]) > 1:
            hide_others = True
        if sub and sub["types"] == [ALTAR_TYPE]:
            if sub["subtypes"] or aff:
                altar.append((_ruleset_number(r), {"bases": sub["subtypes"], "affixes": aff["affixes"] if aff else []}))
            else:
                show_other_altars = True
            continue
        if not sub or not aff or len(sub["types"]) != 1:
            continue
        subs = set(sub["subtypes"])
        kind = next((k for k in kinds if k.type == sub["types"][0]
                     and set(k.subtypes) <= subs <= set(k.all_subtypes)), None)
        if kind:
            picks.setdefault(kind.key, []).append((_ruleset_number(r), {"affixes": aff["affixes"], "min": max(1, min(2, aff["min_on_same_item"]))}))
    picks = {k: _in_order(sets) for k, sets in picks.items()}
    altar = _in_order(altar)
    return {"found": found, "picks": picks, "hide_others": hide_others, "altar": altar or [dict(EMPTY_ALTAR)],
            "show_other_altars": show_other_altars if altar else True}   # without altar picks keep the default


def shadowing_rules(rules: list[dict], position: int, altar: bool = False) -> list[str]:
    """Enabled rules above `position` that catch idols (and, with `altar`, idol altars) by item
    type alone (no affix condition): they decide first, so generated rules below them never
    show their look."""
    watched = set(IDOL_TYPES) | ({ALTAR_TYPE} if altar else set())
    out = []
    for i, r in enumerate(rules[:position]):
        if "raw" in r or not r["enabled"]:
            continue
        types = {t for c in r["conditions"] if c["type"] == "SubTypeCondition" and "raw" not in c for t in c["types"]}
        if types & watched and not any(c["type"] == "AffixCondition" for c in r["conditions"]):
            out.append(f"#{i + 1} {r['name'] or '(unnamed)'}")
    return out
