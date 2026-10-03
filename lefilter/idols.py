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

@dataclass
class IdolOptions:
    picks: dict[str, dict] = field(default_factory=dict)   # kind key -> {"affixes": [ids], "min": 1|2}
    altar: dict = field(default_factory=lambda: {"bases": [], "affixes": []})   # preferred altar subtypes / affix ids
    show_other_altars: bool = True   # below the preferred altars, show every other altar
    rule_prefix: str = "[I] "
    header: str = "------- IDOLS (auto) -------"
    hide_others: bool = False     # hide every other normal/magic/rare/exalted idol below the section's rules
    style: dict = field(default_factory=dict)

    def spec(self, kind: str) -> RuleSpec:
        options = {**STYLE_DEFAULTS[kind], **self.style.get(kind, {})}
        _check_keys(options, RULE_KEYS - {"label", "lp_min", "lp_max", "ww_min", "ww_max"}, f"idol style.{kind}")
        return RuleSpec(**options)


def parse_options(table: dict) -> IdolOptions:
    _check_keys(table, OPTION_KEYS, "idol options")
    opts = IdolOptions(**table)
    for key, pick in opts.picks.items():
        _check_keys(pick, {"affixes", "min"}, f"idol pick {key}")
        if pick.get("min", 2) not in (1, 2):
            raise ConfigError(f"idol pick {key}: min must be 1 or 2 (idols carry two affixes)")
    _check_keys(opts.altar, {"bases", "affixes"}, "idol altar")
    opts.altar = {"bases": list(opts.altar.get("bases", [])), "affixes": list(opts.altar.get("affixes", []))}
    bad = set(opts.style) - set(STYLE_DEFAULTS)
    if bad:
        raise ConfigError(f"idol style: unknown {sorted(bad)}; known: {', '.join(STYLE_DEFAULTS)}")
    return opts


@dataclass
class IdolPlan:
    rules: list[Rule]
    warnings: list[str]


def plan_idols(opts: IdolOptions, kinds: list[IdolKind], altar: AltarKind | None = None) -> IdolPlan:
    p = opts.rule_prefix
    rules, warnings = [], []
    known = {k.key: k for k in kinds}
    for key in opts.picks:
        if key not in known:
            warnings.append(f"unknown idol kind {key!r} skipped")
    for kind in kinds:
        pick = opts.picks.get(kind.key)
        if not pick or not pick.get("affixes"):
            continue
        pool = {a["id"] for a in kind.pool}
        wanted = [a for a in dict.fromkeys(pick["affixes"]) if a in pool]
        if len(wanted) < len(pick["affixes"]):
            warnings.append(f"{kind.label}: {len(pick['affixes']) - len(wanted)} picked affixes can't roll on it; left out")
        if not wanted:
            continue
        n = min(pick.get("min", 2), len(wanted)) if len(wanted) > 1 else 1
        rules.append(Rule(name=f"{p}{kind.label} idol - {n}+ of {len(wanted)} wanted affixes", group="idols",
                          spec=opts.spec("both" if n >= 2 else "single"), unique_ids=None, rarity=None,
                          affix_ids=wanted, affix_min=n, item_types=[kind.type], sub_types=kind.all_subtypes))
    if altar and (opts.altar["bases"] or opts.altar["affixes"]):
        rule = _altar_rule(opts, altar, warnings)
        if rule:
            rules.append(rule)
            if opts.show_other_altars:
                rules.append(Rule(name=f"{p}Idol altar - all other altars", group="idols", spec=opts.spec("altar_other"),
                                  unique_ids=None, rarity=None, item_types=[ALTAR_TYPE]))
    if opts.hide_others:
        rules.append(Rule(name=f"{p}Hide other idols", group="idols", spec=RuleSpec(action="hide"), unique_ids=None,
                          rarity="NORMAL MAGIC RARE EXALTED", item_types=list(IDOL_TYPES)))
    if rules and opts.header:
        rules.insert(0, Rule(name=f"{p}{opts.header}", group="idols", spec=RuleSpec(action="hide", enabled=False),
                             unique_ids=None, rarity=None))
    return IdolPlan(rules=rules, warnings=warnings)


def _altar_rule(opts: IdolOptions, altar: AltarKind, warnings: list[str]) -> Rule | None:
    known_bases, known_affixes = {b["id"] for b in altar.bases}, {a["id"] for a in altar.pool}
    bases = [b for b in dict.fromkeys(opts.altar["bases"]) if b in known_bases]
    affixes = [a for a in dict.fromkeys(opts.altar["affixes"]) if a in known_affixes]
    if len(bases) < len(opts.altar["bases"]) or len(affixes) < len(opts.altar["affixes"]):
        warnings.append("Idol altar: some picked altars or affixes don't exist in this game version; left out")
    if not bases and not affixes:
        return None
    what = " with ".join(x for x in ("preferred altars" if bases else "",
                                      f"1+ of {len(affixes)} preferred affixes" if affixes else "") if x)
    return Rule(name=f"{opts.rule_prefix}Idol altar - {what}", group="idols", spec=opts.spec("altar"), unique_ids=None,
                rarity=None, affix_ids=affixes or None, item_types=[ALTAR_TYPE], sub_types=bases)


def read_picks(rules: list[dict], prefix: str, kinds: list[IdolKind]) -> dict:
    """The options a previously generated idol section (editor rule dicts) was made with."""
    picks, hide_others, found = {}, False, False
    altar, show_other_altars = {"bases": [], "affixes": []}, False
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
                altar = {"bases": sub["subtypes"], "affixes": aff["affixes"] if aff else []}
            else:
                show_other_altars = True
            continue
        if not sub or not aff or len(sub["types"]) != 1:
            continue
        subs = set(sub["subtypes"])
        kind = next((k for k in kinds if k.type == sub["types"][0]
                     and set(k.subtypes) <= subs <= set(k.all_subtypes)), None)
        if kind:
            picks[kind.key] = {"affixes": aff["affixes"], "min": max(1, min(2, aff["min_on_same_item"]))}
    picked = altar["bases"] or altar["affixes"]   # without altar picks keep the default
    return {"found": found, "picks": picks, "hide_others": hide_others, "altar": altar,
            "show_other_altars": show_other_altars if picked else True}


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
