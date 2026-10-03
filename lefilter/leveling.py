"""Leveling section generator: show rules for campaign gear that fits a rough build profile.

Toggles pick affixes by name: a damage type takes every ordinary gear affix whose name
contains "<type> damage" / "<type> penetration", a build focus its keyword ("minion",
"throwing", ...), an attribute its own affix (All Attributes, two-handers only, is its own
toggle), a defence toggle its picker category. Each kind of gear - weapons, off-hands, armour, jewelry
and belts - has its own toggles (SECTIONS), and its rules list the picks that can roll on
it: Strength on armour, rings and relics. Weapons leave out
defensive affixes (health on kill, leech, dodge ...) unless asked. With a class chosen, its
class-specific affixes (helmets, body armours, relics) can also be picked one by one; they
count wherever they roll. No set, corrupted, experimental, personal or idol affixes;
class-specific ones only for the chosen class.

Weapons (and off-hands) are the core: for every selected type the droppable bases below
the level cap are grouped into batches of `step` levels by level requirement. Each batch
gets a rule active from the character level its batch starts at until the next batch
takes over (so exactly one batch of a type is shown at any level, and nothing after the
cap). Armour gets one rule for items with enough build affixes. For jewelry and belts the
base matters little (their best bases come early), so every one with a build affix is
shown until the cap. On top of all that, each slot's good bases (picked per build; by
default the jewelry and belt bases with resistance implicits) get their own rule: still
needing a build affix, but on from level 0 until the cap, where the BiS rules take over.

Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gamedata import (AFFIX_CLASS_BITS, AFFIX_NONSPECIFIC, ARMOUR_TYPES, CLASS_BITS, CLASSES, JEWELRY_TYPES,
                       OFFHAND_TYPES, RARITIES, TYPE_IDS, WEAPON_TYPES)
from .rules import RULE_KEYS, ConfigError, Rule, RuleSpec, _check_keys


@dataclass(frozen=True)
class Toggle:
    key: str
    label: str
    group: str                          # damage | focus | attributes | defence
    phrases: tuple[str, ...] = ()       # lower-case substrings of the affix name
    categories: tuple[str, ...] = ()    # affix-picker categories taken whole
    exclude: tuple[str, ...] = ()       # lower-case substrings that disqualify


ATTRIBUTES = ("strength", "dexterity", "intelligence", "attunement", "vitality")


def _damage(key: str, label: str, also: tuple[str, ...] = ()) -> Toggle:
    words = (key, *also)
    return Toggle(key, label, "damage", tuple(p for w in words for p in (f"{w} damage", f"{w} penetration")))


def _attribute(key: str) -> Toggle:
    return Toggle(key, key.capitalize(), "attributes", (key,))


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
    *(_attribute(a) for a in ATTRIBUTES),
    Toggle("all_attributes", "All Attributes - two-handers only", "attributes", ("all attributes",)),
    Toggle("health", "Health", "defence", categories=("Health",)),
    Toggle("resistances", "Resistances", "defence", ("resistance",), categories=(), exclude=("minion",)),
    Toggle("armour", "Armour", "defence", ("armor",), exclude=("minion", "shred")),
    Toggle("endurance", "Endurance", "defence", ("endurance",), exclude=("minion",)),   # its own defence layer
    Toggle("dodge", "Dodge", "defence", categories=("Dodge",)),
    Toggle("block", "Block", "defence", categories=("Block",)),
    Toggle("ward", "Ward", "defence", categories=("Ward",)),
    Toggle("mana", "Mana", "defence", categories=("Mana",)),
    Toggle("movement", "Movement speed", "defence", categories=("Movement",)),
    Toggle("sustain", "Health regen / leech", "defence", categories=("Health Recovery", "Leech")),
    Toggle("cooldown", "Cooldown recovery", "defence", categories=("Cooldown",)),
)
TOGGLE_BY_KEY = {t.key: t for t in TOGGLES}
GROUPS = ("damage", "focus", "attributes", "defence")
DELIVERY = ("melee", "spell", "bow", "throwing")   # how a hit is dealt; narrows damage-type picks
CLASS_CATEGORIES = set(CLASSES)                    # picker categories holding class-specific affixes
WEAPON_MODES = ("highlight", "require", "bases")
GEAR_ARMOUR = tuple(t for t in ARMOUR_TYPES if t != "BELT")
GEAR_JEWELRY = ("BELT", *JEWELRY_TYPES)            # belts behave like jewelry: few bases worth picking
GEAR_TYPES = (*WEAPON_TYPES, *OFFHAND_TYPES, *GEAR_ARMOUR, *GEAR_JEWELRY)
GEAR_TYPE_IDS = {TYPE_IDS[t] for t in GEAR_TYPES}
# Kinds of gear with their own affix toggles: section -> (option key, item types).
SECTIONS = {
    "weapons": ("weapon_affixes", WEAPON_TYPES),
    "offhands": ("offhand_affixes", OFFHAND_TYPES),
    "armour": ("armour_affixes", GEAR_ARMOUR),
    "jewelry": ("jewelry_affixes", GEAR_JEWELRY),
}
SECTION_OF = {t: s for s, (_, types) in SECTIONS.items() for t in types}
SECTION_LABELS = {"weapons": "Weapons", "offhands": "Off-hands", "armour": "Armour", "jewelry": "Jewelry & belts"}
# Default good bases (any gear type can have some): the jewelry and belt bases Raxxanterax's
# S5 filter picks for the campaign, mostly resistance implicits. Class bases (relics,
# class weapons) count only for the chosen class.
GOOD_BASES = {
    "BELT": ["Spidersilk Sash"],
    "AMULET": ["Bone Amulet", "Gold Amulet"],
    "RING": ["Gold Ring"],
    "RELIC": ["Spirit Catcher", "Scrying Eye", "Rune Quill", "Argent Crest", "Putrid Souls", "Ancient Coins",
              "Ruby Dice", "Antidote Vial"],
}

STYLE_DEFAULTS = {
    "weapon_affix": {"color": 14, "emphasized": True},   # batch base with a build affix
    "weapon_base": {},                                   # batch base without one (rarity colour)
    "gear": {"color": 13, "emphasized": True},           # armour with enough build affixes
    "gear_single": {},                                   # ... with one build affix, early levels only
    "jewelry": {"color": 13},                            # jewelry / belt with a build affix
    "good_base": {"color": 15, "emphasized": True},      # any slot's good base, until the cap
}
OPTION_KEYS = {"enabled", "damage", "focus", "attributes", "defence", "weapons", "offhands", "armour", "jewelry",
               *(key for key, _ in SECTIONS.values()), "character_class", "class_affixes", "step", "cap", "weapon_mode", "rarity", "gear_min_affixes",
               "single_affix_until", "good_bases", "rule_prefix", "header", "style"}


@dataclass
class LevelingOptions:
    # Toggles shared by every kind of gear (v0.2.0 and older): a section left out of the
    # config starts from them (weapons without the defence ones).
    damage: list[str] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    defence: list[str] = field(default_factory=list)
    # Each section's toggles: {damage, focus, attributes, defence: [keys]}; weapons also
    # {defensive: bool} - include defensive affixes on weapons.
    weapon_affixes: dict = field(default_factory=dict)
    offhand_affixes: dict = field(default_factory=dict)
    armour_affixes: dict = field(default_factory=dict)
    jewelry_affixes: dict = field(default_factory=dict)
    weapons: list[str] = field(default_factory=list)      # EquipmentType names (weapons and off-hands)
    offhands: list[str] = field(default_factory=list)
    armour: bool = False
    jewelry: bool = False
    character_class: str = ""                              # "" = no class-specific affixes
    class_affixes: list = field(default_factory=list)      # the class's class-specific affixes: ids or names
    step: int = 10
    cap: int = 60                                          # every rule is off from this character level on
    weapon_mode: str = "highlight"   # highlight: affix rule + plain base rule; require: affix rule only; bases: base only
    rarity: list[str] = field(default_factory=lambda: ["MAGIC", "RARE", "EXALTED"])
    gear_min_affixes: int = 2
    single_affix_until: int = 30     # armour with 1 build affix is shown below this level (0 = never)
    good_bases: dict = field(default_factory=lambda: {t: list(b) for t, b in GOOD_BASES.items()})
    rule_prefix: str = "[L] "
    header: str = "------- LEVELING (auto) -------"
    style: dict = field(default_factory=dict)

    def spec(self, kind: str) -> RuleSpec:
        options = {**STYLE_DEFAULTS[kind], **self.style.get(kind, {})}
        if options.get("color") in (None, -1):   # -1: no recolour (config.toml can't write null)
            options.pop("color", None)
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


def _good_bases(table: dict, bases: list[dict], aliases: dict[str, str]) -> dict[str, list[str]]:
    """good_bases (item type -> base names) over the defaults, names spelled as the game does.
    Unknown names are kept: planning warns about them (a patch may rename a default)."""
    if not isinstance(table, dict) or not all(isinstance(v, list) for v in table.values()):
        raise ConfigError("[leveling] good_bases must be a table of item type -> list of base names")
    by_type = {b["type"]: b for b in bases}
    out = {t: list(b) for t, b in GOOD_BASES.items()}
    for key, names in table.items():
        t = key if key in GEAR_TYPES else aliases.get(_norm(key))
        if t not in GEAR_TYPES:
            raise ConfigError(f"[leveling] good_bases: {key!r} isn't a weapon, off-hand, armour or jewelry type")
        known = {_norm(s["name"]): s["name"] for s in by_type[t]["subtypes"]} if t in by_type else {}
        out[t] = list(dict.fromkeys(known.get(_norm(n), n) for n in names))
    return out


def _toggle_picks(table, where: str, extra: tuple[str, ...] = (), legacy: bool = False) -> dict:
    """{damage, focus, attributes, defence: [toggle keys]} checked; v0.1.0's all-attributes
    defence toggle becomes every attribute. legacy: the shared toggles of v0.2.0 and older,
    whose armour toggle also took the endurance affixes (endurance is its own toggle since)."""
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table of toggle lists ({', '.join(GROUPS)})")
    _check_keys(table, {*GROUPS, *extra}, where)
    picks = {g: list(table.get(g, [])) for g in GROUPS}
    if "attributes" in picks["defence"]:
        picks["defence"].remove("attributes")
        picks["attributes"] = list(ATTRIBUTES)
    if legacy and "armour" in picks["defence"] and "endurance" not in picks["defence"]:
        picks["defence"].insert(picks["defence"].index("armour") + 1, "endurance")
    for group in GROUPS:
        known = [t.key for t in TOGGLES if t.group == group]
        bad = [k for k in picks[group] if k not in known]
        if bad:
            raise ConfigError(f"{where} {group}: unknown {bad}; known: {', '.join(known)}")
    return picks


def parse_options(table: dict, bases: list[dict]) -> LevelingOptions:
    """A [leveling] config table (or the editor's JSON) -> validated options."""
    _check_keys(table, OPTION_KEYS, "[leveling]")
    opts = LevelingOptions(**{k: v for k, v in table.items() if k != "enabled"})
    shared = _toggle_picks({g: getattr(opts, g) for g in GROUPS}, "[leveling]", legacy=True)
    for group in GROUPS:
        setattr(opts, group, shared[group])
    for section, (key, _) in SECTIONS.items():
        extra = ("defensive", "exclude") if section == "weapons" else ("exclude",)
        if key in table:
            picks = _toggle_picks(getattr(opts, key), f"[leveling] {key}", extra)
        else:   # a config from before the sections: the shared toggles (weapons: not the defence ones)
            picks = {g: list(shared[g]) if section != "weapons" or g != "defence" else [] for g in GROUPS}
        if section == "weapons" and key not in table and set(picks["attributes"]) & set(ATTRIBUTES):
            # v0.2.0's shared attribute toggles meant All Attributes on weapons (single ones don't roll there)
            picks["attributes"] = ["all_attributes"]
        if section == "weapons":
            picks["defensive"] = bool(getattr(opts, key).get("defensive", False))
        exclude = getattr(opts, key).get("exclude", []) if key in table else []
        if not isinstance(exclude, list) or not all(isinstance(a, (int, str)) for a in exclude):
            raise ConfigError(f"[leveling] {key} exclude must be a list of affix ids or names")
        picks["exclude"] = list(dict.fromkeys(exclude))   # affixes its toggles take that this gear doesn't want
        setattr(opts, key, picks)
    aliases = _type_aliases(bases)
    for attr, allowed in (("weapons", WEAPON_TYPES + OFFHAND_TYPES), ("offhands", OFFHAND_TYPES)):
        resolved = []
        for name in getattr(opts, attr):
            t = aliases.get(_norm(name))
            if t not in allowed:
                raise ConfigError(f"[leveling] {attr}: unknown item type {name!r}; known: {', '.join(allowed)}")
            resolved.append(t)
        setattr(opts, attr, list(dict.fromkeys(resolved)))
    opts.good_bases = _good_bases(opts.good_bases, bases, aliases)
    if not isinstance(opts.class_affixes, list) or not all(isinstance(a, (int, str)) for a in opts.class_affixes):
        raise ConfigError("[leveling] class_affixes must be a list of affix ids or names")
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


def _phrase_name(a: dict) -> str:
    """The name toggles look for phrases in: the affix asset's own (stable across the game's renames)."""
    return (a.get("internal_name") or a["name"]).lower()


def _names(a: dict) -> set[str]:
    """Every name an affix goes by in a config (exclude, class_affixes): the game's and its own."""
    return {_norm(a["name"]), _norm(a.get("internal_name") or a["name"])}


def _matches(t: Toggle, a: dict) -> bool:
    name = _phrase_name(a)
    hit = any(p in name for p in t.phrases) or a["category"] in t.categories
    return hit and not any(x in name for x in t.exclude)


def toggle_affixes(picks: dict, affixes: list[dict], character_class: str = "", keys=None) -> dict[str, list[dict]]:
    """Toggle key -> affixes it picks (ordinary gear affixes only) for the toggles in `picks`
    ({damage, focus, attributes, defence: [keys]}) or `keys`."""
    pool = gear_affixes(affixes, character_class)
    delivery = [d for d in DELIVERY if d in picks.get("focus", [])]
    picked = {}
    for key in keys or [k for g in GROUPS for k in picks.get(g, [])]:
        t = TOGGLE_BY_KEY[key]
        chosen = [a for a in pool if _matches(t, a)]
        if delivery and key not in DELIVERY and key != "minion":
            # "Added Melee Physical Damage" only counts for a physical build that also hits in melee.
            chosen = [a for a in chosen
                      if not (mentioned := [d for d in DELIVERY if d in _phrase_name(a)])
                      or any(d in delivery for d in mentioned)]
        picked[key] = chosen
    return picked


def class_affix_choices(affixes: list[dict], character_class: str) -> list[dict]:
    """The class's class-specific gear affixes (its affix-picker category): what class_affixes picks from."""
    return [a for a in affixes if character_class and a["category"] == character_class
            and not a["special"] and not a["idol"] and set(a["rolls_on"]) & GEAR_TYPE_IDS]


def class_affixes(opts: LevelingOptions, affixes: list[dict]) -> tuple[list[dict], list[str]]:
    """(the picked class affixes, warnings about picks that aren't the chosen class's)."""
    if not opts.class_affixes:
        return [], []
    if not opts.character_class:
        return [], ["class_affixes: no class chosen; class affixes left out"]
    choices = class_affix_choices(affixes, opts.character_class)
    by_id, by_name = {a["id"]: a for a in choices}, {n: a for a in choices for n in _names(a)}
    picked, unknown = {}, []
    for entry in opts.class_affixes:
        a = by_id.get(entry) if isinstance(entry, int) else by_name.get(_norm(entry))
        if a:
            picked[a["id"]] = a
        else:
            unknown.append(str(entry))
    warnings = [f"class_affixes: not {opts.character_class} affixes, left out: {', '.join(unknown)}"] if unknown else []
    return list(picked.values()), warnings


def _union(groups: list[list[dict]]) -> list[dict]:
    return sorted({a["id"]: a for g in groups for a in g}.values(), key=lambda a: a["id"])


def rolling_on(pool: list[dict], types) -> list[dict]:
    """The affixes of `pool` that can roll on any of the item types."""
    ids = {TYPE_IDS[t] for t in types}
    return [a for a in pool if ids & set(a["rolls_on"])]


def section_candidates(opts: LevelingOptions, affixes: list[dict], keys=None) -> dict[str, dict[str, list[dict]]]:
    """Section -> its toggle key -> the affixes the toggle takes that roll on the section's gear."""
    return {s: {k: rolling_on(v, types)
                for k, v in toggle_affixes(getattr(opts, key), affixes, opts.character_class, keys).items()}
            for s, (key, types) in SECTIONS.items()}


def excluded_ids(opts: LevelingOptions, affixes: list[dict], unknown: list[str] | None = None) -> dict[str, set[int]]:
    """Section -> the ids of the affixes its exclude list names (by id, or by name: every affix of
    it). Names that match no affix are appended to `unknown` as "<option key>: <name>"."""
    by_name: dict[str, set[int]] = {}
    for a in affixes:
        for n in _names(a):
            by_name.setdefault(n, set()).add(a["id"])
    out = {}
    for s, (key, _) in SECTIONS.items():
        ids = set()
        for entry in getattr(opts, key).get("exclude", []):
            found = {entry} if isinstance(entry, int) else by_name.get(_norm(entry), set())
            if not found and unknown is not None:
                unknown.append(f"{key}: {entry}")
            ids |= found
        out[s] = ids
    return out


def section_picks(opts: LevelingOptions, affixes: list[dict], keys=None) -> dict[str, dict[str, list[dict]]]:
    """section_candidates without the affixes each section excludes."""
    out = excluded_ids(opts, affixes)
    return {s: {k: [a for a in v if a["id"] not in out[s]] for k, v in toggles.items()}
            for s, toggles in section_candidates(opts, affixes, keys).items()}


def defensive_on_weapon(a: dict, groups: set[str]) -> bool:
    """Whether weapons leave the affix out without weapon_affixes.defensive: the game files it
    under Defensive (Health On Kill, Melee Health Leech, Dodge ...) or only defence toggles
    picked it (Mana and Mana Regen). `groups` = the toggle groups that picked it; damage-type
    picks stay (Lightning Damage And Leech hits too)."""
    return "damage" not in groups and (a["header"] == "Defensive" or groups == {"defence"})


def section_pools(opts: LevelingOptions, picked: dict[str, dict[str, list[dict]]],
                  class_picks: list[dict], excluded: dict[str, set[int]] | None = None) -> dict[str, list[dict]]:
    """Section -> the build affixes its gear takes: its toggles' picks plus the class affixes
    that roll on it, less what the section excludes (weapons without the defensive ones unless asked)."""
    pools = {}
    for s, (key, types) in SECTIONS.items():
        out = (excluded or {}).get(s, set())
        pool = _union([*picked[s].values(), [a for a in rolling_on(class_picks, types) if a["id"] not in out]])
        if s == "weapons" and not opts.weapon_affixes.get("defensive"):
            groups: dict[int, set[str]] = {}
            for k, v in picked[s].items():
                for a in v:
                    groups.setdefault(a["id"], set()).add(TOGGLE_BY_KEY[k].group)
            chosen = {a["id"] for a in class_picks}
            pool = [a for a in pool if a["id"] in chosen or not defensive_on_weapon(a, groups[a["id"]])]
        pools[s] = pool
    return pools


def build_affixes(opts: LevelingOptions, affixes: list[dict]) -> dict[str, list[dict]]:
    """Section -> the build affixes its gear takes (toggles and class affixes)."""
    return section_pools(opts, section_picks(opts, affixes), class_affixes(opts, affixes)[0], excluded_ids(opts, affixes))


# --- rules ------------------------------------------------------------------------

@dataclass
class Window:
    min: int            # character level the rule switches on
    max: int            # ... and the last level it is on
    bases: list[dict]   # subtypes (id, name, level)


@dataclass
class LevelingPlan:
    rules: list[Rule]
    picked: dict[str, dict[str, list[dict]]]   # section -> toggle -> affixes its gear takes
    candidates: dict[str, dict[str, list[dict]]]   # ... every affix the toggle could give it (before exclusions)
    excluded: dict[str, set[int]]           # section -> affix ids its exclude list takes out
    class_affixes: list[dict]               # picked class-specific affixes
    windows: dict[str, list[Window]]        # item type -> level windows
    rule_affixes: dict[str, list[dict]]     # rule name -> affixes its Affix condition lists
    warnings: list[str]


def _class_ok(sub: dict, character_class: str) -> bool:
    bit = CLASS_BITS.get(character_class, 0)
    return not sub["class"] or bool(bit and sub["class"] & bit)


def good_subtypes(base: dict, names: list[str], character_class: str = "") -> tuple[list[int], list[str]]:
    """(ids of the named bases of an item type, names it doesn't have); class bases only for the
    chosen class (all of them without one)."""
    wanted = {_norm(n) for n in names}
    ids = [s["id"] for s in base["subtypes"]
           if _norm(s["name"]) in wanted and (not character_class or _class_ok(s, character_class))]
    found = {_norm(s["name"]) for s in base["subtypes"]}
    return ids, [n for n in names if _norm(n) not in found]


def level_windows(subtypes: list[dict], step: int, cap: int, character_class: str = "") -> list[Window]:
    """Droppable bases below `cap`, batched by level requirement; each batch is shown from the
    level its batch starts at (0 for the first) until the next non-empty batch starts."""
    usable = [s for s in subtypes if s["drops"] and s["level"] < cap and _class_ok(s, character_class)]
    batches: dict[int, list[dict]] = {}
    for s in sorted(usable, key=lambda s: (s["level"], s["id"])):
        batches.setdefault(s["level"] // step * step, []).append(s)
    starts = sorted(batches)
    return [Window(min=0 if i == 0 else start, max=(starts[i + 1] if i + 1 < len(starts) else cap) - 1,
                   bases=batches[start])
            for i, start in enumerate(starts)]


def plan_leveling(opts: LevelingOptions, data: dict) -> LevelingPlan:
    bases = {b["type"]: b for b in data["bases"]}
    candidates = section_candidates(opts, data["affixes"])
    unknown_excludes: list[str] = []
    excluded = excluded_ids(opts, data["affixes"], unknown_excludes)
    raw = {s: {k: [a for a in v if a["id"] not in excluded[s]] for k, v in toggles.items()}
           for s, toggles in candidates.items()}   # = section_picks()
    class_picks, warnings = class_affixes(opts, data["affixes"])
    pools = section_pools(opts, raw, class_picks, excluded)   # = build_affixes()
    if unknown_excludes:
        warnings.append(f"exclude: no affix named {'; '.join(unknown_excludes)}")
    used = {s: {a["id"] for a in pool} for s, pool in pools.items()}
    picked = {s: {k: [a for a in v if a["id"] in used[s]] for k, v in toggles.items()} for s, toggles in raw.items()}
    rarity = " ".join(r for r in RARITIES if r in opts.rarity) or None
    p = opts.rule_prefix
    rules: list[Rule] = []
    windows: dict[str, list[Window]] = {}
    rule_affixes: dict[str, list[dict]] = {}
    slots: dict[str, list[dict] | None] = {}   # item type in use -> build affixes its items need (None: any)

    def add(rule: Rule, affixes: list[dict] | None = None) -> None:
        rules.append(rule)
        if affixes is not None:
            rule_affixes[rule.name] = affixes

    for t in dict.fromkeys(opts.weapons + opts.offhands):
        base = bases[t]
        eligible = rolling_on(pools[SECTION_OF[t]], (t,))
        wins = windows[t] = level_windows(base["subtypes"], opts.step, opts.cap, opts.character_class)
        if not wins:
            warnings.append(f"{base['name']}: no droppable bases below level {opts.cap}")
        mode = opts.weapon_mode
        if mode != "bases" and not eligible:
            if mode == "require":
                warnings.append(f"{base['name']}: none of the selected affixes roll on it; showing bases only")
            mode = "bases"
        slots[t] = eligible if mode != "bases" else None
        for w in wins:
            label = f"{p}{base['name']} {w.min}-{w.max}"
            common = dict(group="leveling", unique_ids=None, rarity=rarity, item_types=[t],
                          sub_types=[s["id"] for s in w.bases], char_level=(w.min, w.max))
            if mode in ("highlight", "require"):
                add(Rule(name=f"{label} build affix", spec=opts.spec("weapon_affix"),
                         affix_ids=[a["id"] for a in eligible], **common), eligible)
            if mode in ("highlight", "bases"):
                add(Rule(name=label, spec=opts.spec("weapon_base"), **common))

    last = opts.cap - 1
    if opts.armour:
        slots.update({t: rolling_on(pools["armour"], (t,)) for t in GEAR_ARMOUR})
        eligible = pools["armour"]
        if not eligible:
            warnings.append("Armour: no selected affix rolls on it; no rule generated")
        else:
            n = opts.gear_min_affixes
            common = dict(group="leveling", unique_ids=None, rarity=rarity, item_types=list(GEAR_ARMOUR),
                          affix_ids=[a["id"] for a in eligible])
            add(Rule(name=f"{p}Armour {n}+ build affixes 0-{last}", spec=opts.spec("gear"), affix_min=n,
                     char_level=(0, last), **common), eligible)
            until = min(opts.single_affix_until, opts.cap)
            if n > 1 and until > 0:
                add(Rule(name=f"{p}Armour 1 build affix 0-{until - 1}", spec=opts.spec("gear_single"), affix_min=1,
                         char_level=(0, until - 1), **common), eligible)

    if opts.jewelry:
        slots.update({t: rolling_on(pools["jewelry"], (t,)) for t in GEAR_JEWELRY})
        eligible = pools["jewelry"]
        if not eligible:
            warnings.append("Jewelry & belts: no selected affix rolls on them; no rule generated")
        else:
            add(Rule(name=f"{p}Jewelry & belts build affix 0-{last}", group="leveling", spec=opts.spec("jewelry"),
                     unique_ids=None, rarity=rarity, item_types=list(GEAR_JEWELRY),
                     affix_ids=[a["id"] for a in eligible], affix_min=1, char_level=(0, last)), eligible)

    # Good bases on top, so they win over the windows and affix counts below: one rule per item
    # type (a rule only takes bases for a single type), on from level 0 until the cap. Like the
    # rest they need a build affix (only weapons in `bases` mode ignore affixes); after the cap
    # the BiS rules take over.
    good_rules = []
    for t, need in slots.items():
        good, unknown = good_subtypes(bases[t], opts.good_bases.get(t, []), opts.character_class)
        if unknown:
            warnings.append(f"good_bases: {bases[t]['name']} has no bases named {', '.join(unknown)}")
        if good and need == []:
            warnings.append(f"{bases[t]['name']} good bases: none of the build's affixes roll on it; no rule generated")
        elif good:
            good_rules.append(Rule(name=f"{p}{bases[t]['name']} good bases{' build affix' if need else ''} 0-{last}",
                                   group="leveling", spec=opts.spec("good_base"), unique_ids=None, rarity=rarity,
                                   item_types=[t], sub_types=good, affix_ids=[a["id"] for a in need] if need else None,
                                   char_level=(0, last)))
            if need:
                rule_affixes[good_rules[-1].name] = need
    rules[:0] = good_rules

    # Picks that do nothing for the gear in use: say why. A toggle none of whose affixes can roll
    # on its kind of gear at all is skipped (the editor doesn't offer it there).
    names = {b["id"]: b["name"] for b in data["bases"]}

    def where(affixes: list[dict], types) -> str:
        ids = {i for a in affixes for i in a["rolls_on"]} & {TYPE_IDS[t] for t in types}
        return ", ".join(names.get(i, str(i)) for i in sorted(ids))
    for s, (_, types) in SECTIONS.items():
        in_use = [t for t in slots if SECTION_OF[t] == s]
        for k, affixes in raw[s].items() if in_use else ():
            label = f"{SECTION_LABELS[s]}: {TOGGLE_BY_KEY[k].label}"
            if not affixes or picked[s][k] and rolling_on(picked[s][k], in_use):
                continue
            if rolling_on(affixes, in_use):
                warnings.append(f"{label}: only defensive affixes here, which weapons leave out "
                                "(tick Include defensive affixes - weapon_affixes.defensive - to count them)")
            else:
                warnings.append(f"{label}: rolls only on {where(affixes, types)}, none of which is picked")
    if slots:
        for a in class_picks:
            if not rolling_on([a], slots):
                warnings.append(f"{a['name']}: rolls only on {where([a], GEAR_TYPES)}, none of which is picked")

    if rules and opts.header:
        rules.insert(0, Rule(name=f"{p}{opts.header}", group="leveling", spec=RuleSpec(action="hide", enabled=False),
                             unique_ids=None, rarity=None))
    return LevelingPlan(rules=rules, picked=picked, candidates=candidates, excluded=excluded, class_affixes=class_picks,
                        windows=windows, rule_affixes=rule_affixes, warnings=warnings)
