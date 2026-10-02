"""Leveling section generator: show rules for campaign gear that fits a rough build profile.

Toggles pick affixes by name: a damage type takes every ordinary gear affix whose name
contains "<type> damage" / "<type> penetration", a build focus its keyword ("minion",
"throwing", ...), a defence toggle its picker category. Only ordinary affixes that
can roll on the item types of a rule are used (no set, corrupted, experimental,
personal or idol affixes; class-specific ones only for the chosen class).

Weapons (and off-hands) are the core: for every selected type the droppable bases below
the level cap are grouped into batches of `step` levels by level requirement. Each batch
gets a rule active from the character level its batch starts at until the next batch
takes over (so exactly one batch of a type is shown at any level, and nothing after the
cap). Armour and jewelry get one rule per slot group for items with enough build affixes.

Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gamedata import (AFFIX_CLASS_BITS, AFFIX_NONSPECIFIC, ARMOUR_TYPES, CLASS_BITS, CLASSES, JEWELRY_TYPES,
                       OFFHAND_TYPES, RARITIES, WEAPON_TYPES)
from .rules import RULE_KEYS, ConfigError, Rule, RuleSpec, _check_keys


@dataclass(frozen=True)
class Toggle:
    key: str
    label: str
    group: str                          # damage | focus | defence
    phrases: tuple[str, ...] = ()       # lower-case substrings of the affix name
    categories: tuple[str, ...] = ()    # affix-picker categories taken whole
    exclude: tuple[str, ...] = ()       # lower-case substrings that disqualify


def _damage(key: str, label: str, also: tuple[str, ...] = ()) -> Toggle:
    words = (key, *also)
    return Toggle(key, label, "damage", tuple(p for w in words for p in (f"{w} damage", f"{w} penetration")))


TOGGLES = (
    _damage("physical", "Physical"),
    _damage("fire", "Fire", also=("elemental",)),
    _damage("cold", "Cold", also=("elemental",)),
    _damage("lightning", "Lightning", also=("elemental",)),
    _damage("void", "Void"),
    _damage("necrotic", "Necrotic"),
    _damage("poison", "Poison"),
    Toggle("melee", "Melee", "focus", ("melee",), exclude=("minion",)),
    Toggle("spell", "Spell / magic", "focus", ("spell", "cast speed"), exclude=("minion",)),
    Toggle("throwing", "Throwing", "focus", ("throwing",), exclude=("minion",)),
    Toggle("bow", "Bow", "focus", ("bow",), exclude=("minion",)),
    Toggle("minion", "Minion", "focus", ("minion",)),
    Toggle("crit", "Critical strike", "focus", ("crit",), exclude=("avoidance", "reduced bonus damage")),
    Toggle("dot", "Damage over time", "focus", ("damage over time",)),
    Toggle("ailments", "Ailment chance", "focus", categories=("Ailments",), exclude=("attackers",)),
    Toggle("health", "Health", "defence", categories=("Health",)),
    Toggle("resistances", "Resistances", "defence", ("resistance",), categories=(), exclude=("minion",)),
    Toggle("armour", "Armour", "defence", ("armor", "endurance"), exclude=("minion", "shred")),
    Toggle("dodge", "Dodge", "defence", categories=("Dodge",)),
    Toggle("block", "Block", "defence", categories=("Block",)),
    Toggle("ward", "Ward", "defence", categories=("Ward",)),
    Toggle("mana", "Mana", "defence", categories=("Mana",)),
    Toggle("attributes", "Attributes", "defence", categories=("Attributes",)),
    Toggle("movement", "Movement speed", "defence", categories=("Movement",)),
    Toggle("sustain", "Health regen / leech", "defence", categories=("Health Recovery", "Leech")),
    Toggle("cooldown", "Cooldown recovery", "defence", categories=("Cooldown",)),
)
TOGGLE_BY_KEY = {t.key: t for t in TOGGLES}
DELIVERY = ("melee", "spell", "bow", "throwing")   # how a hit is dealt; narrows damage-type picks
CLASS_CATEGORIES = set(CLASSES)                    # picker categories holding class-specific affixes
WEAPON_MODES = ("highlight", "require", "bases")

STYLE_DEFAULTS = {
    "weapon_affix": {"color": 14, "emphasized": True},   # batch base with a build affix
    "weapon_base": {},                                   # batch base without one (rarity colour)
    "gear": {"color": 13, "emphasized": True},           # armour / jewelry with enough build affixes
    "gear_single": {},                                   # ... with one build affix, early levels only
}
OPTION_KEYS = {"enabled", "damage", "focus", "defence", "weapons", "offhands", "armour", "jewelry",
               "character_class", "step", "cap", "weapon_mode", "rarity", "gear_min_affixes",
               "single_affix_until", "rule_prefix", "header", "style"}


@dataclass
class LevelingOptions:
    damage: list[str] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    defence: list[str] = field(default_factory=list)
    weapons: list[str] = field(default_factory=list)      # EquipmentType names (weapons and off-hands)
    offhands: list[str] = field(default_factory=list)
    armour: bool = False
    jewelry: bool = False
    character_class: str = ""                              # "" = no class-specific affixes
    step: int = 10
    cap: int = 60                                          # every rule is off from this character level on
    weapon_mode: str = "highlight"   # highlight: affix rule + plain base rule; require: affix rule only; bases: base only
    rarity: list[str] = field(default_factory=lambda: ["MAGIC", "RARE", "EXALTED"])
    gear_min_affixes: int = 2
    single_affix_until: int = 30     # armour/jewelry with 1 build affix are shown below this level (0 = never)
    rule_prefix: str = "[L] "
    header: str = "------- LEVELING (auto) -------"
    style: dict = field(default_factory=dict)

    def spec(self, kind: str) -> RuleSpec:
        options = {**STYLE_DEFAULTS[kind], **self.style.get(kind, {})}
        _check_keys(options, RULE_KEYS - {"label", "lp_min", "lp_max", "ww_min", "ww_max"}, f"leveling style.{kind}")
        return RuleSpec(**options)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _type_aliases(bases: list[dict]) -> dict[str, str]:
    """Loose spellings -> EquipmentType name: TWO_HANDED_SWORD, "Two-Handed Sword", "2h sword"."""
    aliases = {}
    for b in bases:
        for spelling in (b["type"], b["name"], b["type"].replace("TWO_HANDED", "2H").replace("ONE_HANDED", "1H"),
                         b["name"].replace("Two-Handed", "2H").replace("One-Handed", "1H")):
            aliases[_norm(spelling)] = b["type"]
    return aliases


def parse_options(table: dict, bases: list[dict]) -> LevelingOptions:
    """A [leveling] config table (or the editor's JSON) -> validated options."""
    _check_keys(table, OPTION_KEYS, "[leveling]")
    opts = LevelingOptions(**{k: v for k, v in table.items() if k != "enabled"})
    for group in ("damage", "focus", "defence"):
        known = [t.key for t in TOGGLES if t.group == group]
        bad = [k for k in getattr(opts, group) if k not in known]
        if bad:
            raise ConfigError(f"[leveling] {group}: unknown {bad}; known: {', '.join(known)}")
    aliases = _type_aliases(bases)
    for attr, allowed in (("weapons", WEAPON_TYPES + OFFHAND_TYPES), ("offhands", OFFHAND_TYPES)):
        resolved = []
        for name in getattr(opts, attr):
            t = aliases.get(_norm(name))
            if t not in allowed:
                raise ConfigError(f"[leveling] {attr}: unknown item type {name!r}; known: {', '.join(allowed)}")
            resolved.append(t)
        setattr(opts, attr, list(dict.fromkeys(resolved)))
    if opts.character_class and opts.character_class not in CLASSES:
        raise ConfigError(f"[leveling] character_class must be one of {', '.join(CLASSES)} (or empty)")
    if opts.weapon_mode not in WEAPON_MODES:
        raise ConfigError(f"[leveling] weapon_mode must be one of {', '.join(WEAPON_MODES)}")
    if not 1 <= opts.step <= 100 or not opts.step <= opts.cap <= 100:
        raise ConfigError("[leveling] needs 1 <= step <= cap <= 100")
    if any(r not in RARITIES for r in opts.rarity):
        raise ConfigError(f"[leveling] rarity: known rarities are {', '.join(RARITIES)}")
    if not 1 <= opts.gear_min_affixes <= 4:
        raise ConfigError("[leveling] gear_min_affixes must be 1-4")
    bad_styles = set(opts.style) - set(STYLE_DEFAULTS)
    if bad_styles:
        raise ConfigError(f"[leveling] style: unknown {sorted(bad_styles)}; known: {', '.join(STYLE_DEFAULTS)}")
    for kind in STYLE_DEFAULTS:
        opts.spec(kind)
    return opts


# --- affixes ----------------------------------------------------------------------

def gear_affixes(affixes: list[dict], character_class: str = "") -> list[dict]:
    """Ordinary affixes that drop on gear: no class restriction, allowed on non-class items
    (e.g. Added Throwing Damage) or, with a class chosen, allowed for that class."""
    allowed = AFFIX_NONSPECIFIC | AFFIX_CLASS_BITS.get(character_class, 0)
    return [a for a in affixes
            if not a["special"] and not a["idol"]
            and (a["category"] not in CLASS_CATEGORIES or a["category"] == character_class)
            and (not a["class"] or a["class"] & allowed)]


def _matches(t: Toggle, a: dict) -> bool:
    name = a["name"].lower()
    hit = any(p in name for p in t.phrases) or a["category"] in t.categories
    return hit and not any(x in name for x in t.exclude)


def toggle_affixes(opts: LevelingOptions, affixes: list[dict]) -> dict[str, list[dict]]:
    """Selected toggle key -> affixes it picks (ordinary gear affixes only)."""
    pool = gear_affixes(affixes, opts.character_class)
    delivery = [d for d in DELIVERY if d in opts.focus]
    picked = {}
    for key in (*opts.damage, *opts.focus, *opts.defence):
        t = TOGGLE_BY_KEY[key]
        chosen = [a for a in pool if _matches(t, a)]
        if delivery and key not in DELIVERY and key != "minion":
            # "Added Melee Physical Damage" only counts for a physical build that also hits in melee.
            chosen = [a for a in chosen
                      if not (mentioned := [d for d in DELIVERY if d in a["name"].lower()])
                      or any(d in delivery for d in mentioned)]
        picked[key] = chosen
    return picked


def _union(groups: list[list[dict]]) -> list[dict]:
    return sorted({a["id"]: a for g in groups for a in g}.values(), key=lambda a: a["id"])


def build_affixes(opts: LevelingOptions, affixes: list[dict]) -> tuple[list[dict], list[dict]]:
    """(offense: damage + focus picks - what weapons use, everything: + defence - the other slots)."""
    picked = toggle_affixes(opts, affixes)
    return _union([picked[k] for k in (*opts.damage, *opts.focus)]), _union(list(picked.values()))


# --- rules ------------------------------------------------------------------------

@dataclass
class Window:
    min: int            # character level the rule switches on
    max: int            # ... and the last level it is on
    bases: list[dict]   # subtypes (id, name, level)


@dataclass
class LevelingPlan:
    rules: list[Rule]
    picked: dict[str, list[dict]]           # toggle -> affixes
    windows: dict[str, list[Window]]        # item type -> level windows
    rule_affixes: dict[str, list[dict]]     # rule name -> affixes its Affix condition lists
    warnings: list[str]


def level_windows(subtypes: list[dict], step: int, cap: int, character_class: str = "") -> list[Window]:
    """Droppable bases below `cap`, batched by level requirement; each batch is shown from the
    level its batch starts at (0 for the first) until the next non-empty batch starts."""
    bit = CLASS_BITS.get(character_class, 0)
    usable = [s for s in subtypes if s["drops"] and s["level"] < cap and (not s["class"] or (bit and s["class"] & bit))]
    batches: dict[int, list[dict]] = {}
    for s in sorted(usable, key=lambda s: (s["level"], s["id"])):
        batches.setdefault(s["level"] // step * step, []).append(s)
    starts = sorted(batches)
    return [Window(min=0 if i == 0 else start, max=(starts[i + 1] if i + 1 < len(starts) else cap) - 1,
                   bases=batches[start])
            for i, start in enumerate(starts)]


def plan_leveling(opts: LevelingOptions, data: dict) -> LevelingPlan:
    bases = {b["type"]: b for b in data["bases"]}
    picked = toggle_affixes(opts, data["affixes"])
    offense, everything = build_affixes(opts, data["affixes"])
    rarity = " ".join(r for r in RARITIES if r in opts.rarity) or None
    p = opts.rule_prefix
    rules: list[Rule] = []
    windows: dict[str, list[Window]] = {}
    rule_affixes: dict[str, list[dict]] = {}
    warnings: list[str] = []

    def add(rule: Rule, affixes: list[dict] | None = None) -> None:
        rules.append(rule)
        if affixes is not None:
            rule_affixes[rule.name] = affixes

    for t in dict.fromkeys(opts.weapons + opts.offhands):
        base = bases[t]
        pool = offense if t in WEAPON_TYPES else everything
        eligible = [a for a in pool if base["id"] in a["rolls_on"]]
        wins = windows[t] = level_windows(base["subtypes"], opts.step, opts.cap, opts.character_class)
        if not wins:
            warnings.append(f"{base['name']}: no droppable bases below level {opts.cap}")
        mode = opts.weapon_mode
        if mode != "bases" and not eligible:
            if mode == "require":
                warnings.append(f"{base['name']}: none of the selected affixes roll on it; showing bases only")
            mode = "bases"
        for w in wins:
            label = f"{p}{base['name']} {w.min}-{w.max}"
            common = dict(group="leveling", unique_ids=None, rarity=rarity, item_types=[t],
                          sub_types=[s["id"] for s in w.bases], char_level=(w.min, w.max))
            if mode in ("highlight", "require"):
                add(Rule(name=f"{label} build affix", spec=opts.spec("weapon_affix"),
                         affix_ids=[a["id"] for a in eligible], **common), eligible)
            if mode in ("highlight", "bases"):
                add(Rule(name=label, spec=opts.spec("weapon_base"), **common))

    for enabled, label, types in ((opts.armour, "Armour", ARMOUR_TYPES), (opts.jewelry, "Jewelry", JEWELRY_TYPES)):
        if not enabled:
            continue
        ids = {bases[t]["id"] for t in types}
        eligible = [a for a in everything if ids & set(a["rolls_on"])]
        if not eligible:
            warnings.append(f"{label}: no selected affix rolls on it; no rule generated")
            continue
        n = opts.gear_min_affixes
        common = dict(group="leveling", unique_ids=None, rarity=rarity, item_types=list(types),
                      affix_ids=[a["id"] for a in eligible])
        add(Rule(name=f"{p}{label} {n}+ build affixes 0-{opts.cap - 1}", spec=opts.spec("gear"), affix_min=n,
                 char_level=(0, opts.cap - 1), **common), eligible)
        until = min(opts.single_affix_until, opts.cap)
        if n > 1 and until > 0:
            add(Rule(name=f"{p}{label} 1 build affix 0-{until - 1}", spec=opts.spec("gear_single"), affix_min=1,
                     char_level=(0, until - 1), **common), eligible)

    if rules and opts.header:
        rules.insert(0, Rule(name=f"{p}{opts.header}", group="leveling", spec=RuleSpec(action="hide", enabled=False),
                             unique_ids=None, rarity=None))
    return LevelingPlan(rules=rules, picked=picked, windows=windows, rule_affixes=rule_affixes, warnings=warnings)
