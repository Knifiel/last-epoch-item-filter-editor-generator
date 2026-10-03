"""Turn config.toml + extracted unique data into an ordered list of filter rules.

Ordering convention everywhere in this module: index 0 is the TOP of the
in-game rule list, i.e. the highest-priority rule (the first match wins).
"""
from __future__ import annotations

import copy
import difflib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .gamedata import CLASS_IDOL_TYPES, CLASSES, COMMON_IDOL_TYPES, RARITIES, TYPE_IDS

RARITY_TIERS = ("uncommon", "rare", "very_rare", "extremely_rare")  # ascending reroll-chance thresholds
DROP_TIERS = ("common", *RARITY_TIERS, "special")                    # special = cannot drop randomly
CATEGORIES = (*DROP_TIERS, "primordial", "cocooned", "weaver", *(f"set_{t}" for t in DROP_TIERS))
BEAM_SIZES = ("NONE", "LARGEST", "VERYLARGE", "LARGE", "MEDIUM", "SMALL", "VERYSMALL", "SMALLEST")

RULE_KEYS = {"label", "lp_min", "lp_max", "ww_min", "ww_max", "action", "color", "emphasized",
             "enabled", "sound", "map_icon", "beam_size", "beam_color"}
GROUP_KEYS = {"name", "header", "build_slot", "categories", "lpl_min", "lpl_max", "base_types", "only", "include",
              "exclude", "rules"}
BASE_TYPE_ALIASES = {"IDOLS": COMMON_IDOL_TYPES + CLASS_IDOL_TYPES}
SLOT_KEYS = RULE_KEYS - {"label"} | {"name"}
AFFIX_RULE_KEYS = RULE_KEYS - {"label", "lp_min", "lp_max", "ww_min", "ww_max"} | {"name", "affix_categories"}
CLASS_HIDE_KEYS = {"add", "name", "rarity", "enabled_for"}
# Defaults this version's config.toml changed, as (earlier versions' default, this version's): the
# rules of [[group]]s by name, and the [[exalted_rule]] and [[affix_rule]] lists. The packaged app's config.toml is a
# copy from its first run: read_config gives a setting still at the old default the new one (one
# the user changed stays theirs); released_defaults does the reverse, rebuilding what earlier
# versions generated from a config (see starter.sync_template).
UPDATED_GROUP_RULES = {
    "WEAVER": ([{"ww_min": 17, "color": 2, "emphasized": True}, {"ww_max": 16, "color": 2}],      # v0.2.0
               [{"ww_min": 19, "color": 7, "emphasized": True}, {"ww_min": 15, "ww_max": 18, "color": 2, "emphasized": True},
                {"ww_max": 14, "color": 2}]),
}
_ALL_UNIQUES = ["common", "uncommon", "rare", "very_rare", "extremely_rare", "special", "primordial", "cocooned", "weaver"]
# Other [[group]] settings, (group name, key) -> (earlier default, this version's).
UPDATED_GROUP_SETTINGS = {
    # v0.3.3: cocooned items (boxes holding a random unique) moved to the [starter] cocooned rule, below the
    # legendary one: the section is the primordial uniques', and no unique group lists cocooned items
    ("PRIMORDIAL", "header"): ("--- PRIMORDIAL / COCOONED ---", "--- PRIMORDIAL ---"),
    ("UNIQUE IDOLS", "categories"): (_ALL_UNIQUES, [c for c in _ALL_UNIQUES if c != "cocooned"]),
}
# [[group]]s a version dropped, as earlier versions had them, each with the group it came after (where
# released_defaults puts it back).
DROPPED_GROUPS = [({"name": "COCOONED", "categories": ["cocooned"], "rules": [{"label": "all", "color": 1}]}, "PRIMORDIAL")]   # v0.3.3
_EXALTED_V020 = [
    {"name": "ALL T8 ITEMS", "min": 1, "tier": 8, "color": 10, "emphasized": True, "beam_size": "LARGE", "beam_color": 13},
    {"name": "EXALTED - DOUBLE T7", "min": 2, "tier": 7, "uncorrupted": True, "color": 7, "emphasized": True},
    {"name": "EXALTED - T7 + T6", "min": 2, "tier": 6, "total": 13, "uncorrupted": True, "color": 7, "enabled": False},
    {"name": "EXALTED - SINGLE T7", "min": 1, "tier": 7, "uncorrupted": True, "color": 8},
]
CLASS_HIDE_NAME = "Hide items of other classes (select what classes you don't want to see)"
UPDATED_CLASS_HIDE_NAME = ("Hide non-{class} class non-legendary items", CLASS_HIDE_NAME)   # one rule per class before v0.3.1
UPDATED_AFFIX_RULES = (   # v0.3.2: Variant mods only come on two non-random uniques, which the unique rules show
    [{"name": "ALWAYS SHOW - PERSONAL & VARIANT AFFIXES", "affix_categories": ["Personal", "Variant"], "emphasized": True}],
    [{"name": "ALWAYS SHOW - PERSONAL AFFIXES", "affix_categories": ["Personal"], "emphasized": True}])
UPDATED_EXALTED_RULES = (_EXALTED_V020, _EXALTED_V020 + [
    {"name": "EXALTED - CORRUPTED DOUBLE T7", "min": 2, "tier": 7, "corrupted": True, "color": 11, "emphasized": True}])


def _swap_defaults(config: dict, to_new: bool) -> dict:
    def swap(old, new, current):
        if to_new:
            return new if current == old else current
        return old if current in (old, new) else current

    out = copy.deepcopy(config)
    for g in out.get("group", []):
        if g.get("name") in UPDATED_GROUP_RULES and "rules" in g:
            g["rules"] = swap(*UPDATED_GROUP_RULES[g["name"]], g["rules"])
        for (name, key), defaults in UPDATED_GROUP_SETTINGS.items():
            if g.get("name") == name and key in g:
                g[key] = swap(*defaults, g[key])
    if "group" in out:
        for group, after in DROPPED_GROUPS:
            if to_new:   # still as it was: gone (a changed one stays the user's)
                out["group"] = [g for g in out["group"] if g != group]
            elif not any(g.get("name") == group["name"] for g in out["group"]):
                at = next((i + 1 for i, g in enumerate(out["group"]) if g.get("name") == after), len(out["group"]))
                out["group"].insert(at, copy.deepcopy(group))
    if "exalted_rule" in out:
        out["exalted_rule"] = swap(*UPDATED_EXALTED_RULES, out["exalted_rule"])
    if "affix_rule" in out:
        out["affix_rule"] = swap(*UPDATED_AFFIX_RULES, out["affix_rule"])
    if "name" in out.get("class_hide", {}):
        out["class_hide"]["name"] = swap(*UPDATED_CLASS_HIDE_NAME, out["class_hide"]["name"])
    return out


def upgrade_config(config: dict) -> dict:
    """Settings still at an earlier version's default get this version's (UPDATED_*)."""
    return _swap_defaults(config, True)


def released_defaults(config: dict) -> dict:
    """The config as earlier versions used it: UPDATED_* settings at either default get the old
    one, DROPPED_GROUPS are back, no [starter] corrupted or cocooned rule (they had none) and shatter
    rules for exalted items too.
    (Their per-class hide rules: see starter.legacy_template_rules.)"""
    out = _swap_defaults(config, False)
    out["starter"] = {**out.get("starter", {}), "corrupted": False, "cocooned": False}   # their cocooned rule: an [A] group's
    out["class_hide"] = {"name": UPDATED_CLASS_HIDE_NAME[0], **out.get("class_hide", {})}
    out["shatter"] = {**out.get("shatter", {}), "rarity": ["MAGIC", "RARE", "EXALTED"]}   # exalted too, before v0.3.1
    return out


def renamed_rules(config: dict) -> dict[str, str]:
    """Generated rules a version renamed, old name -> new (rule_prefix included): filters and templates
    from before keep such a rule's on/off state - and a filled build slot - under its new name."""
    prefix = config.get("filter", {}).get("rule_prefix", "")
    slot = config.get("build_slots", {}).get("name", "EDIT FOR YOUR BUILD - {section}")
    names = {"--- PRIMORDIAL / COCOONED ---": "--- PRIMORDIAL ---",                             # v0.3.3
             slot.format(section="PRIMORDIAL / COCOONED"): slot.format(section="PRIMORDIAL")}   # v0.3.3
    return {prefix + a: prefix + b for a, b in names.items()}


def read_config(path: Path) -> dict:
    """config.toml, upgraded (upgrade_config)."""
    return upgrade_config(tomllib.loads(Path(path).read_text(encoding="utf-8")))


class ConfigError(Exception):
    pass


@dataclass
class RuleSpec:
    label: str = ""
    lp_min: int | None = None
    lp_max: int | None = None
    ww_min: int | None = None
    ww_max: int | None = None
    action: str = "show"
    color: int | None = None       # None keeps the game's default colour (no recolour)
    emphasized: bool = False
    enabled: bool = True
    sound: int = 0                 # 0 = default drop sound, 1 = none
    map_icon: int = 0
    beam_size: str | None = None   # None = no beam override
    beam_color: int = 0

    def auto_label(self) -> str:
        if self.label:
            return self.label
        parts = []
        if self.lp_min is not None or self.lp_max is not None:  # "2LP+", "0-1LP"
            parts.append(f"{self.lp_min or 0}LP+" if self.lp_max is None else f"{self.lp_min or 0}-{self.lp_max}LP")
        if self.ww_min is not None or self.ww_max is not None:  # "17+ WW", "0-16 WW"
            parts.append(f"{self.ww_min or 0}+ WW" if self.ww_max is None else f"{self.ww_min or 0}-{self.ww_max} WW")
        return " ".join(parts) or "all"

    def covers(self, other: RuleSpec) -> bool:
        """True if every item matching `other` also matches self (self would shadow it from above)."""
        return (_range_covers(self.lp_min, self.lp_max, other.lp_min, other.lp_max)
                and _range_covers(self.ww_min, self.ww_max, other.ww_min, other.ww_max))


@dataclass
class Group:
    name: str
    header: str = ""               # separator rule emitted above the group (always, even if it selects nothing)
    build_slot: bool | dict = True # for header groups: False = no build slot for this section, table = restyle it
    categories: list[str] = field(default_factory=list)
    lpl_min: int | None = None
    lpl_max: int | None = None
    base_types: list[str] = field(default_factory=list)   # item types (EquipmentType names, or IDOLS); empty = any
    only: list = field(default_factory=list)
    include: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    rules: list[RuleSpec] = field(default_factory=list)


@dataclass
class Rule:
    """One concrete filter rule, ready for XML.

    rarity None means no Rarity condition; unique_ids None means no Uniques condition,
    [] an empty one (a build slot to fill in-game); affix_ids adds an Affix condition
    (at least affix_min of them on the item); item_types (+ sub_types, which the game
    only honours for a single type) an Item Type condition; char_level a Character
    Level condition (min, max); classes a Class Requirement condition (items only those
    classes can use). affix_tier / affix_total make the Affix condition count only affixes
    of at least that tier / need their tiers to add up to at least that; corruption adds a
    Corruption condition ("OnlyCorrupted" / "OnlyUncorrupted"). A rule with none of them is
    a section separator.
    """
    name: str
    group: str
    spec: RuleSpec
    unique_ids: list[int] | None
    rarity: str | None = "UNIQUE"
    affix_ids: list[int] | None = None
    affix_min: int = 1
    item_types: list[str] | None = None
    sub_types: list[int] = field(default_factory=list)
    char_level: tuple[int, int] | None = None
    classes: list[str] | None = None
    affix_tier: int | None = None
    affix_total: int | None = None
    corruption: str | None = None

    @property
    def is_separator(self) -> bool:
        return (self.rarity is None and self.unique_ids is None and self.affix_ids is None
                and self.item_types is None and self.char_level is None and self.classes is None
                and self.corruption is None)


def separator(name: str, group: str = "") -> Rule:
    """Disabled, condition-less rule used purely as a visual section header in-game."""
    return Rule(name=name, group=group, spec=RuleSpec(action="hide", enabled=False), unique_ids=None, rarity=None)


def _section_title(header: str) -> str:
    return re.sub(r"^[\s=-]+|[\s=-]+$", "", header)


def _rarity_for(items: list[dict]) -> str:
    sets = sum(u["is_set"] for u in items)
    return "SET" if items and sets == len(items) else "UNIQUE SET" if sets else "UNIQUE"


@dataclass
class _Section:
    title: str
    slot: dict | None               # build-slot rule options, None = no slot
    members: list[dict] = field(default_factory=list)
    last_group: str = ""


def _slot_options(config: dict, group: Group) -> dict | None:
    defaults = dict(config.get("build_slots", {}))
    if not defaults.pop("add", False) or group.build_slot is False:
        return None
    options = {**defaults, **(group.build_slot if isinstance(group.build_slot, dict) else {})}
    _check_keys(options, SLOT_KEYS, f"build slot of group '{group.name}'")
    return options


def _build_slot(section: _Section, prefix: str) -> Rule:
    """Empty, disabled rule at the end of a section: add items to it in-game to show
    them even when the section's own rules would let them fall through to the hide rule."""
    options = dict(section.slot)
    name = options.pop("name", "EDIT FOR YOUR BUILD - {section}").format(section=section.title)
    options.setdefault("enabled", False)
    return Rule(name=f"{prefix}{name}", group=section.last_group, spec=RuleSpec(**options), unique_ids=[],
                rarity=_rarity_for(section.members))


@dataclass
class Plan:
    rules: list[Rule]
    members: dict[str, list[dict]]      # group name -> member uniques
    uncovered: list[dict]               # uniques no group selected
    warnings: list[str]
    slot_categories: dict[str, set[str]] = field(default_factory=dict)   # build slot name -> its section's categories


def _range_covers(lo, hi, olo, ohi) -> bool:
    lo = 0 if lo is None else lo
    olo = 0 if olo is None else olo
    hi = float("inf") if hi is None else hi
    ohi = float("inf") if ohi is None else ohi
    return lo <= olo and hi >= ohi


def _check_keys(table: dict, allowed: set, where: str) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}")


def parse_groups(config: dict) -> list[Group]:
    groups = []
    for i, g in enumerate(config.get("group", [])):
        where = f"[[group]] #{i + 1} ({g.get('name', '?')})"
        _check_keys(g, GROUP_KEYS, where)
        if "name" not in g:
            raise ConfigError(f"{where}: missing name")
        bad = set(g.get("categories", [])) - set(CATEGORIES)
        if bad:
            raise ConfigError(f"{where}: unknown categories {sorted(bad)}; known: {', '.join(CATEGORIES)}")
        bad = [t for t in g.get("base_types", []) if t not in TYPE_IDS and t not in BASE_TYPE_ALIASES]
        if bad:
            raise ConfigError(f"{where}: unknown base_types {bad}; use item types like RING or {', '.join(BASE_TYPE_ALIASES)}")
        rules = []
        for j, r in enumerate(g.get("rules", [])):
            _check_keys(r, RULE_KEYS, f"{where} rule #{j + 1}")
            spec = RuleSpec(**r)
            if spec.action not in ("show", "hide"):
                raise ConfigError(f"{where} rule #{j + 1}: action must be 'show' or 'hide'")
            if spec.beam_size is not None and spec.beam_size.upper() not in BEAM_SIZES:
                raise ConfigError(f"{where} rule #{j + 1}: beam_size must be one of {BEAM_SIZES}")
            rules.append(spec)
        if not rules:
            raise ConfigError(f"{where}: needs at least one rule")
        groups.append(Group(**{**g, "rules": rules}))
    names = [g.name for g in groups]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ConfigError(f"duplicate group names: {sorted(dupes)}")
    return groups


def _drop_tier(u: dict, thresholds: dict[str, float]) -> str:
    if not u["can_drop_randomly"]:
        return "special"
    tier = "common"
    for t in RARITY_TIERS:
        if u["reroll_chance"] >= thresholds[t]:
            tier = t
    return tier


def categorize(u: dict, thresholds: dict[str, float]) -> str:
    if u["is_set"]:
        return f"set_{_drop_tier(u, thresholds)}"
    if u["weavers_will"]:
        return "weaver"
    if u["is_cocooned"]:
        return "cocooned"
    if u["is_primordial"]:
        return "primordial"
    return _drop_tier(u, thresholds)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class UniqueIndex:
    def __init__(self, uniques: list[dict]):
        self.by_id = {u["id"]: u for u in uniques}
        self.by_name: dict[str, dict] = {}
        for u in uniques:
            for n in (u["name"], u["internal_name"]):
                self.by_name.setdefault(_norm(n), u)

    def resolve(self, refs: list, where: str) -> list[dict]:
        out = []
        for ref in refs:
            u = self.by_id.get(ref) if isinstance(ref, int) else self.by_name.get(_norm(str(ref)))
            if u is None:
                close = difflib.get_close_matches(_norm(str(ref)), self.by_name, n=3)
                hint = f" (did you mean: {', '.join(self.by_name[c]['name'] for c in close)})" if close else ""
                raise ConfigError(f"{where}: unknown unique {ref!r}{hint}")
            out.append(u)
        return out


def plan_rules(config: dict, uniques: list[dict]) -> Plan:
    thresholds = {k: float(v) for k, v in config.get("rarity", {}).items()}
    missing = set(RARITY_TIERS) - set(thresholds)
    if missing:
        raise ConfigError(f"[rarity] missing thresholds: {sorted(missing)}")
    prefix = config.get("filter", {}).get("rule_prefix", "")
    groups = parse_groups(config)
    index = UniqueIndex(uniques)
    cat = {u["id"]: categorize(u, thresholds) for u in uniques}

    rules, members, warnings, selected, slot_cats = [], {}, [], set(), {}
    section: _Section | None = None
    for g in groups:
        where = f"group '{g.name}'"
        if g.header:
            if section and section.slot is not None:
                rules.append(_build_slot(section, prefix))
                slot_cats[rules[-1].name] = {cat[u["id"]] for u in section.members}
            section = _Section(title=_section_title(g.header), slot=_slot_options(config, g), last_group=g.name)
            rules.append(separator(f"{prefix}{g.header}", g.name))
        types = {TYPE_IDS[t] for name in g.base_types for t in BASE_TYPE_ALIASES.get(name, (name,))}
        if g.only:
            chosen = index.resolve(g.only, where)
        else:
            chosen = [u for u in uniques   # hidden: hideFromPlayers - never drop, the game's picker leaves them out
                      if cat[u["id"]] in g.categories and not u.get("hidden")
                      and (g.lpl_min is None or u["lpl"] >= g.lpl_min)
                      and (g.lpl_max is None or u["lpl"] <= g.lpl_max)
                      and (not types or u["base_type"] in types)]
        chosen += index.resolve(g.include, where)
        excluded = {u["id"] for u in index.resolve(g.exclude, where)}
        chosen = sorted({u["id"]: u for u in chosen if u["id"] not in excluded}.values(),
                        key=lambda u: (u["lpl"], u["name"]))
        if not chosen:
            if g.categories:  # an empty `only` list is a placeholder, not a mistake
                warnings.append(f"{where} selects no uniques; skipped")
            continue
        members[g.name] = chosen
        selected.update(u["id"] for u in chosen)
        if section:
            section.members += chosen
            section.last_group = g.name
        ids = [u["id"] for u in chosen]
        rarity = _rarity_for(chosen)
        for spec in g.rules:
            rules.append(Rule(name=f"{prefix}{g.name} - {spec.auto_label()}", group=g.name, spec=spec,
                              unique_ids=ids, rarity=rarity))
        active = [s for s in g.rules if s.enabled]
        for hi, upper in enumerate(active):
            for lower in active[hi + 1:]:
                if upper.covers(lower):
                    warnings.append(f"{where}: rule '{lower.auto_label()}' can never match - "
                                    f"'{upper.auto_label()}' above it already catches those items")

    if section and section.slot is not None:
        rules.append(_build_slot(section, prefix))
        slot_cats[rules[-1].name] = {cat[u["id"]] for u in section.members}

    uncovered = [u for u in uniques if u["id"] not in selected and not u.get("hidden")]
    return Plan(rules=rules, members=members, uncovered=uncovered, warnings=warnings, slot_categories=slot_cats)


def build_slot_filters(config: dict, uniques: list[dict]) -> dict[str, str]:
    """Build slot name -> the uniques filter the editor's picker starts with for it: "weaver" for the
    slot of the section with the Weaver's Will uniques, "primordial" for the one with the primordial
    uniques (its other groups - cocooned items, which only hold a random unique, and the unique idols
    let through - aren't what a build picks there). Other slots: none."""
    try:
        plan = plan_rules(config, uniques)
    except ConfigError:
        return {}
    out = {}
    for name, cats in plan.slot_categories.items():
        if "weaver" in cats:
            out[name] = "weaver"
        elif "primordial" in cats:
            out[name] = "primordial"
    for was, now in renamed_rules(config).items():   # a filter not refreshed since has the slot by its old name
        if now in out:
            out.setdefault(was, out[now])
    return out


def plan_affix_rules(config: dict, affixes: list[dict]) -> tuple[list[Rule], dict[str, list[dict]], list[str]]:
    """[[affix_rule]] entries -> rules matching items with any affix of the given picker categories.

    Returns (rules, rule name -> member affixes, warnings).
    """
    prefix = config.get("filter", {}).get("rule_prefix", "")
    known = sorted({a["category"] for a in affixes if a["category"]})
    by_category: dict[str, list[dict]] = {}
    for a in affixes:
        by_category.setdefault(a["category"].lower(), []).append(a)
    rules, members, warnings = [], {}, []
    for i, entry in enumerate(config.get("affix_rule", [])):
        where = f"[[affix_rule]] #{i + 1} ({entry.get('name', '?')})"
        _check_keys(entry, AFFIX_RULE_KEYS, where)
        options = dict(entry)
        name = options.pop("name", None)
        categories = options.pop("affix_categories", [])
        if not name or not categories:
            raise ConfigError(f"{where}: needs name and affix_categories")
        chosen = []
        for c in categories:
            if c.lower() not in by_category:
                raise ConfigError(f"{where}: unknown affix category {c!r}; known: {', '.join(known)}")
            chosen += by_category[c.lower()]
        rule = Rule(name=f"{prefix}{name}", group=name, spec=RuleSpec(**options), unique_ids=None, rarity=None,
                    affix_ids=[a["id"] for a in chosen])
        rules.append(rule)
        members[rule.name] = chosen
    return rules, members, warnings


def class_hide_name(config: dict) -> str:
    """The [class_hide] rule's name, rule_prefix included (a per-class name with {class}, from
    before it was one rule, gives the default)."""
    name = config.get("class_hide", {}).get("name", CLASS_HIDE_NAME)
    return config.get("filter", {}).get("rule_prefix", "") + (CLASS_HIDE_NAME if "{class}" in name else name)


def plan_class_hide(config: dict, per_class: bool = False) -> list[Rule]:
    """[class_hide] -> one rule hiding the class-specific items (normal/magic/rare by default) of
    the classes it lists. With `enabled_for` (the classes the build plays) it's on and lists every
    other class; else it's off and lists all five - untick yours in a build's copy (none ticked
    would match every item). per_class: the rule per class earlier versions made instead, for
    telling their templates' rules apart."""
    cfg = config.get("class_hide", {})
    _check_keys(cfg, CLASS_HIDE_KEYS, "[class_hide]")
    if not cfg.get("add", False):
        return []
    rarity = cfg.get("rarity", ["NORMAL", "MAGIC", "RARE"])
    enabled_for = cfg.get("enabled_for", [])
    if not rarity or set(rarity) - set(RARITIES):
        raise ConfigError(f"[class_hide] rarity: pick from {', '.join(RARITIES)}")
    if set(enabled_for) - set(CLASSES):
        raise ConfigError(f"[class_hide] enabled_for: classes are {', '.join(CLASSES)}")
    rarity = " ".join(r for r in RARITIES if r in rarity)
    if per_class:
        prefix = config.get("filter", {}).get("rule_prefix", "")
        name = cfg.get("name", UPDATED_CLASS_HIDE_NAME[0])
        if "{class}" not in name:
            return []
        return [Rule(name=f"{prefix}{name.replace('{class}', c)}", group="class items",
                     spec=RuleSpec(action="hide", enabled=c in enabled_for), unique_ids=None,
                     rarity=rarity, classes=[o for o in CLASSES if o != c]) for c in CLASSES]
    hidden = [c for c in CLASSES if c not in enabled_for] if enabled_for else list(CLASSES)
    if not hidden:
        raise ConfigError("[class_hide] enabled_for lists every class: there's no other class to hide")
    return [Rule(name=class_hide_name(config), group="class items", spec=RuleSpec(action="hide", enabled=bool(enabled_for)),
                 unique_ids=None, rarity=rarity, classes=hidden)]


def lpl_histogram(uniques: list[dict], thresholds: dict[str, float], edges=(30, 60, 80, 100, 200)):
    """category -> counts per LPL bucket, for picking split points."""
    labels = [f"<{edges[0]}"] + [f"{a}-{b - 1}" for a, b in zip(edges, edges[1:])] + [f"{edges[-1]}+"]
    table = {c: [0] * len(labels) for c in CATEGORIES}
    for u in uniques:
        c = categorize(u, thresholds)
        bucket = sum(u["lpl"] >= e for e in edges)
        table[c][bucket] += 1
    return labels, table
