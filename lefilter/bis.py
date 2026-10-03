"""Best-in-slot generator: rules for the gear a build wants to keep, slot by slot.

Per slot (weapons, off-hand, helmet, body armour, belt, boots, gloves, amulet, ring, relic) the
user picks concrete bases - weapons and off-hands across several item types, since a build may
change weapons; a rule takes the bases of one type, so each type gets its own rule - and
concrete affixes, plus two tiers of what an item needs: the strict BiS one (default: 2+ of the
picked affixes at T7+, with a beam) and a looser "good" one below it (default: 1+ at T6+), each
with an optional minimum forging potential. The rules replace the filter's "BIS - " rules in its
BiS section (the first time, the template's generic placeholders).

Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .filterdoc import new_rule
from .gamedata import CLASS_BITS, CLASSES, OFFHAND_TYPES, RARITIES, TYPE_IDS, WEAPON_TYPES
from .leveling import _class_ok, gear_affixes
from .rules import ConfigError, _check_keys
from .sections import doc_infos, insert_position, place

PREFIX = "BIS - "
HEADER = "------ BIS ITEMS ------"
SLOTS = (("weapons", "Weapons", WEAPON_TYPES), ("offhand", "Off-hand", OFFHAND_TYPES),
         ("helmet", "Helmet", ("HELMET",)), ("body", "Body armour", ("BODY_ARMOR",)), ("belt", "Belt", ("BELT",)),
         ("boots", "Boots", ("BOOTS",)), ("gloves", "Gloves", ("GLOVES",)), ("amulet", "Amulet", ("AMULET",)),
         ("ring", "Ring", ("RING",)), ("relic", "Relic", ("RELIC",)))
SLOT_TYPES = {key: types for key, _, types in SLOTS}
SLOT_OF = {t: key for key, _, types in SLOTS for t in types}
TIERS = ("bis", "good")
TIER_DEFAULTS = {"bis": {"enabled": True, "min": 2, "tier": 7, "fp": None},
                 "good": {"enabled": True, "min": 1, "tier": 6, "fp": None}}
STYLE_DEFAULTS = {"bis": {"color": 9, "emphasized": True, "beam_size": "LARGEST", "beam_color": 12},
                  "good": {"color": 9}}
STYLE_KEYS = {"color", "emphasized", "beam_size", "beam_color", "sound", "map_icon"}
OPTION_KEYS = {"slots", "character_class", "rarity", "style", "header"}


@dataclass
class BisOptions:
    # slot key -> {"bases": {item type: [base ids]} (none listed = every base of the type),
    #              "affixes": [ids], "bis": tier, "good": tier}; tier = {enabled, min, tier, fp}
    slots: dict = field(default_factory=dict)
    character_class: str = ""        # filters class bases and offers that class's affixes
    rarity: list = field(default_factory=lambda: ["MAGIC", "RARE", "EXALTED"])
    style: dict = field(default_factory=dict)
    header: str = HEADER             # separator put above the rules when the filter has no BiS section

    def look(self, tier: str) -> dict:
        """new_rule fields for a tier's look."""
        st = {**STYLE_DEFAULTS[tier], **self.style.get(tier, {})}
        beam = st.get("beam_size", "NONE")
        return {"recolor": st.get("color") is not None, "color": st.get("color") or 0,
                "emphasized": bool(st.get("emphasized")), "sound": st.get("sound", 0), "map_icon": st.get("map_icon", 0),
                "beam_override": beam != "NONE", "beam_size": beam, "beam_color": st.get("beam_color", 0)}


def _int(v, what: str, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ConfigError(f"{what} must be a number") from None
    if not lo <= n <= hi:
        raise ConfigError(f"{what} must be {lo}-{hi}")
    return n


def parse_options(table: dict) -> BisOptions:
    _check_keys(table, OPTION_KEYS, "BiS options")
    opts = BisOptions(**table)
    slots = {}
    for key, s in (opts.slots or {}).items():
        if key not in SLOT_TYPES:
            raise ConfigError(f"unknown BiS slot {key!r}; known: {', '.join(SLOT_TYPES)}")
        _check_keys(s, {"bases", "affixes", *TIERS}, f"BiS slot {key}")
        bases = s.get("bases") or {}
        if not isinstance(bases, dict) or any(t not in SLOT_TYPES[key] for t in bases):
            raise ConfigError(f"BiS slot {key}: bases must map its item types ({', '.join(SLOT_TYPES[key])}) to base ids")
        tiers = {}
        for t in TIERS:
            tier = {**TIER_DEFAULTS[t], **(s.get(t) or {})}
            _check_keys(tier, set(TIER_DEFAULTS[t]), f"BiS slot {key} {t}")
            fp = tier["fp"]
            tiers[t] = {"enabled": bool(tier["enabled"]), "min": _int(tier["min"], f"BiS {key} {t} min", 1, 6),
                        "tier": _int(tier["tier"], f"BiS {key} {t} tier", 1, 8),
                        "fp": None if fp in (None, "") else _int(fp, f"BiS {key} {t} forging potential", 0, 255)}
        slots[key] = {"bases": {t: [int(i) for i in ids] for t, ids in bases.items()},
                      "affixes": list(dict.fromkeys(int(a) for a in s.get("affixes") or [])), **tiers}
    opts.slots = slots
    if opts.character_class and opts.character_class not in CLASSES:
        raise ConfigError(f"BiS class must be one of {', '.join(CLASSES)} (or empty)")
    if any(r not in RARITIES for r in opts.rarity):
        raise ConfigError(f"BiS rarity: known rarities are {', '.join(RARITIES)}")
    bad = set(opts.style) - set(STYLE_DEFAULTS)
    if bad or any(set(st) - STYLE_KEYS for st in opts.style.values()):
        raise ConfigError(f"BiS style: kinds {', '.join(STYLE_DEFAULTS)} with {', '.join(sorted(STYLE_KEYS))}")
    return opts


def slot_pool(affixes: list[dict], slot: str, character_class: str = "") -> list[dict]:
    """What a slot's affix picker offers: ordinary gear affixes (the class's own with a class)
    that roll on any of its item types."""
    ids = {TYPE_IDS[t] for t in SLOT_TYPES[slot]}
    return [a for a in gear_affixes(affixes, character_class) if ids & set(a["rolls_on"])]


def rule_name(type_name: str, tier: str, need: dict | None, fp: int | None) -> str:
    """"BIS - Helmet: 2+ T7", "BIS - Helmet (good): 1+ T6, FP 20+", "BIS - Shield: bases"."""
    body = f"{need['min']}+ T{need['tier']}" if need else "bases"
    return f"{PREFIX}{type_name}{' (good)' if tier == 'good' else ''}: {body}" + (f", FP {fp}+" if fp else "")


@dataclass
class BisPlan:
    rules: list[dict]        # editor rule dicts, top first
    warnings: list[str]


def plan_bis(opts: BisOptions, data: dict) -> BisPlan:
    bases = {b["type"]: b for b in data["bases"]}
    by_id = {a["id"]: a for a in data["affixes"]}
    rarity = [r for r in RARITIES if r in opts.rarity]
    rules, warnings = [], []
    for key, label, types in SLOTS:
        s = opts.slots.get(key)
        if not s:
            continue
        chosen = [t for t in types if t in s["bases"]] if len(types) > 1 else list(types)
        if not s["affixes"] and not any(s["bases"].get(t) for t in types) and len(types) == 1:
            continue                               # nothing picked for the slot
        if not chosen:
            if s["affixes"]:
                warnings.append(f"{label}: pick the item types (and bases) the affixes are for")
            continue
        unknown = [a for a in s["affixes"] if a not in by_id]
        if unknown:
            warnings.append(f"{label}: {len(unknown)} picked affixes don't exist in this game version; left out")
        allowed = {a["id"] for a in gear_affixes(data["affixes"], opts.character_class)}
        other = [a for a in s["affixes"] if a in by_id and a not in allowed]
        if other:   # picked for another class (or with one): items with them need that class
            warnings.append(f"{label}: {len(other)} picked affixes are for "
                            f"{'another class' if opts.character_class else 'a class'}; left out")
        picks = [a for a in s["affixes"] if a in by_id and a in allowed]
        per_type = []
        for t in chosen:
            base = bases.get(t)
            if not base:
                continue
            known = {x["id"] for x in base["subtypes"]}
            picked = [i for i in s["bases"].get(t, []) if i in known]
            if len(picked) < len(s["bases"].get(t, [])):
                warnings.append(f"{base['name']}: {len(s['bases'][t]) - len(picked)} picked bases aren't in this game version; left out")
                if not picked:   # not "every base" instead of the ones picked
                    continue
            fits = {x["id"] for x in base["subtypes"] if not opts.character_class or _class_ok(x, opts.character_class)}
            subs = [i for i in picked if i in fits]   # no class: every class's bases
            if not picked and len(fits) < len(base["subtypes"]):
                # "every base" with a class: no base condition would also match other classes' bases
                subs = sorted(fits)
            if picked and not subs:
                warnings.append(f"{base['name']}: none of the picked bases is for {opts.character_class}; no rule")
                continue
            if not fits:   # e.g. bows for a non-Rogue: an empty base list would mean every (other class's) base
                warnings.append(f"{base['name']}: no {opts.character_class} bases; no rule")
                continue
            ids = [a for a in picks if TYPE_IDS[t] in by_id[a]["rolls_on"]]
            if s["affixes"] and not ids:
                warnings.append(f"{base['name']}: none of the picked affixes roll on it; no rule")
                continue
            per_type.append((base["name"], t, subs, ids))
        for tier in TIERS:
            need = s[tier]
            if not need["enabled"]:
                continue
            for name, t, subs, ids in per_type:
                if not ids and tier == "good":   # bases only: one rule is enough
                    continue
                conds = [{"type": "SubTypeCondition", "types": [t], "subtypes": subs}]
                if rarity:
                    conds.append({"type": "RarityCondition", "rarity": rarity})
                if ids:
                    n, strict = min(need["min"], len(ids)), need["tier"] > 1
                    conds.append({"type": "AffixCondition", "affixes": ids, "comparsion": "MORE_OR_EQUAL" if strict else "ANY",
                                  "comparsion_value": need["tier"] if strict else 0, "min_on_same_item": n,
                                  "combined_comparsion": "ANY", "combined_value": 1, "advanced": strict})
                if need["fp"]:
                    conds.append({"type": "PotentialCondition", "lp_min": None, "lp_max": None, "ww_min": None,
                                  "ww_max": None, "wt_min": None, "wt_max": None, "fp_min": need["fp"], "fp_max": None})
                shown = {"min": min(need["min"], len(ids)), "tier": need["tier"]} if ids else None
                rules.append(new_rule(rule_name(name, tier, shown, need["fp"]), conditions=conds, **opts.look(tier)))
    return BisPlan(rules=rules, warnings=warnings)


def place_bis(current: list[dict], new: list[dict], header: str = HEADER) -> tuple[list[dict], int, int]:
    """The filter's "BIS - " rules replaced by `new` (in place); else under its BiS separator;
    else at the top under a new `header` separator. Returns (rules, removed, position)."""
    infos = doc_infos(current)
    old, _ = insert_position(infos, PREFIX, section="BIS", fallback="top")
    has_section = any(i.separator and not i.catch_all and "BIS" in i.name.upper() for i in infos)
    if not old and not has_section and header and new:
        new = [new_rule(header, enabled=False, type="HIDE")] + new
    return place(current, infos, new, PREFIX, section="BIS", fallback="top")


def _class_of(rules: list[dict], slots: dict, bases: dict[str, dict]) -> str:
    """The class a BiS section was made for: the one class every picked class base is for, else
    the class whose "Hide non-<class>" rule is on (the template's class hide rules), else ""."""
    bits = None
    for s in slots.values():
        for t, ids in s["bases"].items():
            for x in bases.get(t, {}).get("subtypes", []):
                if x["id"] in ids and x["class"]:
                    bits = x["class"] if bits is None else bits & x["class"]
    if bits:
        own = [c for c in CLASSES if bits & CLASS_BITS[c]]
        if len(own) == 1:
            return own[0]
    on = [c for c in CLASSES for r in rules if "raw" not in r and r.get("enabled")
          and re.search(rf"\bHide non-{c}\b", r.get("name") or "")]
    return on[0] if len(set(on)) == 1 else ""


def read_picks(rules: list[dict], data: dict | None = None) -> dict:
    """The options a previously generated BiS section (editor rule dicts) was made with:
    {"found", "slots", "rarity", "character_class"} (class only with `data`: from its class bases
    or the filter's class hide rule; a class's full base list then reads back as "every base").
    The template's placeholders ("BIS - Helmet (pick bases)") don't count."""
    slots: dict[str, dict] = {}
    seen: set[tuple[str, str]] = set()
    rarity = None
    for r in rules:
        name = r.get("name") or ""
        if "raw" in r or not name.startswith(PREFIX) or ": " not in name:
            continue
        sub = next((c for c in r["conditions"] if c["type"] == "SubTypeCondition" and "raw" not in c), None)
        if not sub or len(sub["types"]) != 1 or sub["types"][0] not in SLOT_OF:
            continue
        t = sub["types"][0]
        s = slots.setdefault(SLOT_OF[t], {"bases": {}, "affixes": [], **{k: {**TIER_DEFAULTS[k], "enabled": False}
                                                                           for k in TIERS}})
        s["bases"][t] = list(sub["subtypes"])
        tier = "good" if name.split(":", 1)[0].endswith(" (good)") else "bis"
        aff = next((c for c in r["conditions"] if c["type"] == "AffixCondition" and "raw" not in c), None)
        pot = next((c for c in r["conditions"] if c["type"] == "PotentialCondition" and "raw" not in c), None)
        rar = next((c for c in r["conditions"] if c["type"] == "RarityCondition" and "raw" not in c), None)
        if rar and rarity is None:
            rarity = rar["rarity"]
        if aff:
            s["affixes"] = list(dict.fromkeys(s["affixes"] + aff["affixes"]))
        n = aff["min_on_same_item"] if aff else TIER_DEFAULTS[tier]["min"]
        if (SLOT_OF[t], tier) in seen:   # several types: each was capped at what rolls on it, so the largest is the pick
            n = max(n, s[tier]["min"])
        seen.add((SLOT_OF[t], tier))
        s[tier] = {"enabled": True, "min": n,
                   "tier": aff["comparsion_value"] if aff and aff.get("advanced") and aff["comparsion"] == "MORE_OR_EQUAL" else (
                       1 if aff else TIER_DEFAULTS[tier]["tier"]),
                   "fp": pot.get("fp_min") if pot else None}
    character_class = ""
    if data is not None:
        bases = {b["type"]: b for b in data["bases"]}
        character_class = _class_of(rules, slots, bases)
        if character_class:   # a class's full base list was written for "every base"
            for s in slots.values():
                for t, ids in s["bases"].items():
                    subs = bases.get(t, {}).get("subtypes", [])
                    fits = sorted(x["id"] for x in subs if _class_ok(x, character_class))
                    if ids and sorted(ids) == fits and len(fits) < len(subs):
                        s["bases"][t] = []
    for key, s in slots.items():
        if not s["affixes"]:
            s["good"]["enabled"] = True   # a bases-only slot makes no good rule; keep the default for later picks
        if len(SLOT_TYPES[key]) == 1 and not s["bases"].get(SLOT_TYPES[key][0]):
            s["bases"] = {}
    return {"found": bool(slots), "slots": slots, "rarity": rarity, "character_class": character_class}
