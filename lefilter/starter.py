"""Starter filters (the editor's New button) and refreshing the generated [A] rules of a filter.

A starter filter is built from parts, top to bottom: the [[affix_rule]]s, the BiS section
(per slot the build's affixes at a high tier; bases left to pick), generic [[exalted_rule]]s
(T8 first) and a show-all-legendary rule under one header, the [class_hide] rules (the
chosen class's one enabled), the shatter section, the unique / set groups, optionally the
leveling section, and a bottom rule hiding everything else. That last one never hides shards, runes, glyphs
or keys: the game only applies rules made of non-equipment conditions to those
(Rule.MatchNonEquipment). Exalted, legendary and hide-everything rules get no rule prefix:
they belong to the filter from then on, like rules kept from a base filter.

Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

import re

from pathlib import Path

from . import idols
from .filterdoc import encode_rule, node_to_xml, parse_filter, parse_rule_blocks, render_filter
from .filterxml import BaseFilter, FilterHeader, insert_above_section, merge, render_rule, rule_infos, write_filter
from .gamedata import ARMOUR_TYPES, CLASS_FILTER_ICONS, CLASSES, JEWELRY_TYPES, OFFHAND_TYPES, TYPE_IDS, WEAPON_TYPES
from .leveling import CLASS_CATEGORIES, build_affixes, gear_affixes, parse_options as parse_leveling, plan_leveling
from .rules import (RULE_KEYS, ConfigError, Rule, RuleSpec, _check_keys, plan_affix_rules, plan_class_hide,
                    plan_rules, separator)
from .sections import doc_infos, place

PARTS = {
    "personal": "Always show personal & variant affixes ([[affix_rule]])",
    "bis": "BiS section: build affixes per slot + idol altars - pick the bases yourself ([bis])",
    "exalted": "Generic exalted rules, T8 first ([[exalted_rule]])",
    "legendary": "Show all legendary items",
    "class_hide": "Class item hide rules (the chosen class's one enabled)",
    "shatter": "Shatter section: rare-roll affixes + class affixes ([shatter])",
    "uniques": "Unique & set rules (the [[group]]s)",
    "leveling": "Leveling section (the Leveling tab's settings)",
    "hide_rest": "Hide everything else at the bottom",
}
LOOK_KEYS = RULE_KEYS - {"label", "lp_min", "lp_max", "ww_min", "ww_max"}
EXALTED_KEYS = LOOK_KEYS | {"name", "min", "tier", "total", "uncorrupted"}
STARTER_KEYS = {"header", "legendary", "hide_rest"}
GEAR_TYPES = WEAPON_TYPES + OFFHAND_TYPES + ARMOUR_TYPES + JEWELRY_TYPES
GEAR_TYPE_IDS = {TYPE_IDS[t] for t in GEAR_TYPES}
BIS_KEYS = LOOK_KEYS | {"header", "tier", "min", "altar"}
SHATTER_KEYS = LOOK_KEYS | {"header", "max_weight", "include", "general_tier", "class_tier"}


def gear_affix_ids(affixes: list[dict]) -> list[int]:
    """Ordinary affixes of weapons, off-hands, armour and jewelry (what the exalted rules count)."""
    return [a["id"] for a in affixes
            if not a["special"] and not a["idol"] and set(a["rolls_on"]) & GEAR_TYPE_IDS]


def plan_exalted(config: dict, affixes: list[dict]) -> list[Rule]:
    """[[exalted_rule]]: items with `min` gear affixes of tier >= `tier` (tiers adding up to >= `total`)."""
    ids = gear_affix_ids(affixes)
    rules = []
    for i, entry in enumerate(config.get("exalted_rule", [])):
        where = f"[[exalted_rule]] #{i + 1} ({entry.get('name', '?')})"
        _check_keys(entry, EXALTED_KEYS, where)
        options = dict(entry)
        name = options.pop("name", None)
        n, tier, total = options.pop("min", 1), options.pop("tier", None), options.pop("total", None)
        uncorrupted = options.pop("uncorrupted", False)
        if not name:
            raise ConfigError(f"{where}: needs a name")
        if not 1 <= n <= 6 or (tier is not None and not 1 <= tier <= 8):
            raise ConfigError(f"{where}: min must be 1-6 and tier 1-8")
        rules.append(Rule(name=name, group="exalted", spec=RuleSpec(**options), unique_ids=None, rarity=None,
                          affix_ids=ids, affix_min=n, affix_tier=tier, affix_total=total,
                          corruption="OnlyUncorrupted" if uncorrupted else None))
    return rules


def _look(table: dict, keys: set, where: str) -> RuleSpec:
    _check_keys(table, keys, where)
    return RuleSpec(**{k: v for k, v in table.items() if k in LOOK_KEYS})


def _tier(t: int) -> int | None:
    return t if t and t > 1 else None   # tier 1+ is any tier: no advanced comparison needed


def plan_bis(config: dict, data: dict, build: dict, character_class: str = "") -> list[Rule]:
    """[bis]: per slot a rule for its item type with the build's affixes at `tier`+ (`min` of
    them). Bases stay unpicked (every base matches) - choose the right ones in the editor or
    in-game. Weapons / off-hands get one rule per type the build uses (a rule can only list
    bases for a single type), plus an idol altar rule with every altar affix."""
    cfg = config.get("bis", {})
    spec = _look(cfg, BIS_KEYS, "[bis]")
    tier, n = cfg.get("tier", 7), cfg.get("min", 1)
    opts = parse_leveling({k: v for k, v in build.items() if k != "enabled"}, data["bases"])
    if character_class:
        opts.character_class = character_class
    offense, everything = build_affixes(opts, data["affixes"])
    names = {b["type"]: b["name"] for b in data["bases"]}

    def rule(name: str, types: list[str], pool: list[dict] | list[int], enabled: bool = True) -> Rule:
        ids = [a if isinstance(a, int) else a["id"] for a in pool]
        rs = RuleSpec(**{**spec.__dict__, "enabled": spec.enabled and enabled and bool(ids)})
        return Rule(name=name, group="bis", spec=rs, unique_ids=None, rarity=None, item_types=types,
                    affix_ids=ids, affix_min=n, affix_tier=_tier(tier))

    rules = [separator(cfg.get("header", "------ BIS ITEMS (pick the bases) ------"))]
    hands = list(dict.fromkeys(opts.weapons + opts.offhands))
    for t in hands:
        pool = offense if t in WEAPON_TYPES else everything
        rules.append(rule(f"BIS - {names[t]} (pick bases)", [t], [a for a in pool if TYPE_IDS[t] in a["rolls_on"]]))
    if not hands:   # nothing to go on: a disabled rule to fill in (no item type matches nothing)
        rules.append(rule("BIS - Weapon (pick type & bases)", [], offense, enabled=False))
    for t in ARMOUR_TYPES + JEWELRY_TYPES:
        rules.append(rule(f"BIS - {names[t]} (pick bases)", [t], [a for a in everything if TYPE_IDS[t] in a["rolls_on"]]))
    if cfg.get("altar", True):
        altar = [a["id"] for a in data["affixes"] if a["category"] == "Idol Altars" and not a["special"]]
        rules.append(rule("BIS - Idol Altar (pick bases & affixes)", ["IDOL_ALTAR"], altar))
    return rules


def plan_shatter(config: dict, data: dict, character_class: str = "") -> list[Rule]:
    """[shatter]: gear (idols can't be shattered) with affixes worth shattering - one rule for
    non-class affixes that rarely roll (weighting <= max_weight, e.g. Hybrid Health, X and
    minion X penetration) and one per class for its class-specific affixes (the chosen
    class's one enabled)."""
    cfg = config.get("shatter", {})
    spec = _look(cfg, SHATTER_KEYS, "[shatter]")
    max_weight = cfg.get("max_weight", 0.15)
    include = {n.lower() for n in cfg.get("include", [])}
    pool = gear_affixes(data["affixes"])
    rare = [a["id"] for a in pool if a["category"] not in CLASS_CATEGORIES
            and (a.get("weight", 1) <= max_weight or a["name"].lower() in include)]
    common = dict(group="shatter", unique_ids=None, rarity="MAGIC RARE EXALTED", item_types=list(GEAR_TYPES))
    rules = [separator(cfg.get("header", "------ SHATTER AFFIXES ------")),
             Rule(name="SHATTER - RARE-ROLL AFFIXES", spec=spec, affix_ids=rare,
                  affix_tier=_tier(cfg.get("general_tier", 1)), **common)]
    for cls in CLASSES:
        ids = [a["id"] for a in data["affixes"] if a["category"] == cls and not a["special"] and not a["idol"]
               and set(a["rolls_on"]) & GEAR_TYPE_IDS]
        rs = RuleSpec(**{**spec.__dict__, "enabled": spec.enabled and cls == character_class})
        rules.append(Rule(name=f"SHATTER - {cls.upper()} AFFIXES", spec=rs, affix_ids=ids,
                          affix_tier=_tier(cfg.get("class_tier", 3)), **common))
    return rules


def _named_rule(table: dict, where: str, **conditions) -> Rule:
    _check_keys(table, LOOK_KEYS | {"name"}, where)
    options = dict(table)
    return Rule(name=options.pop("name"), group="starter", spec=RuleSpec(**options), unique_ids=None, **conditions)


def build_starter(config: dict, data: dict, options: dict) -> dict:
    """The editor's New filter: {"header", "rules"} plus "warnings"."""
    parts = set(options.get("parts", PARTS))
    unknown = parts - set(PARTS)
    if unknown:
        raise ConfigError(f"unknown starter parts {sorted(unknown)}")
    cls = options.get("character_class", "")
    scfg = config.get("starter", {})
    _check_keys(scfg, STARTER_KEYS, "[starter]")
    fcfg = config.get("filter", {})
    warnings = []
    rules: list[Rule] = []
    build = options.get("leveling", config.get("leveling", {}))
    if "personal" in parts:
        affix_rules, _, affix_warnings = plan_affix_rules(config, data["affixes"])
        rules += affix_rules
        warnings += affix_warnings
    if "bis" in parts:
        rules += plan_bis(config, data, build, cls)
    exalted = plan_exalted(config, data["affixes"]) if "exalted" in parts else []
    legendary = (_named_rule(scfg.get("legendary", {"name": "SHOW ALL LEGENDARY ITEMS"}), "[starter] legendary",
                             rarity="LEGENDARY") if "legendary" in parts else None)
    if exalted or legendary:
        rules.append(separator(scfg.get("header", "------ EXALTED & LEGENDARY ------")))
        rules += exalted + ([legendary] if legendary else [])
    if "class_hide" in parts:   # closes the section before the shatter one, where refreshing puts them too
        table = {**config.get("class_hide", {}), "add": True, "enabled_for": [cls] if cls else []}
        rules += plan_class_hide({**config, "class_hide": table})
    if "shatter" in parts:
        rules += plan_shatter(config, data, cls)
    if "uniques" in parts:
        plan = plan_rules(config, data["uniques"])
        rules += plan.rules
        warnings += plan.warnings
    if "hide_rest" in parts:   # enabled and condition-less: the catch-all (a separator is disabled)
        table = scfg.get("hide_rest", {"name": "HIDE EVERYTHING ELSE"})
        _check_keys(table, {"name"}, "[starter] hide_rest")
        rules.append(Rule(name=table.get("name", "HIDE EVERYTHING ELSE"), group="starter", spec=RuleSpec(action="hide"),
                          unique_ids=None, rarity=None))
    doc_rules = parse_rule_blocks([render_rule(r) for r in rules])
    if "leveling" in parts:
        lev_table = {k: v for k, v in build.items() if k != "enabled"}
        if cls:
            lev_table["character_class"] = cls
        lev_opts = parse_leveling(lev_table, data["bases"])
        lev = plan_leveling(lev_opts, data)
        warnings += [f"leveling: {w}" for w in lev.warnings]
        doc_rules, _, _ = place(doc_rules, doc_infos(doc_rules), parse_rule_blocks([render_rule(r) for r in lev.rules]),
                                lev_opts.rule_prefix)
    header = {"name": options.get("name") or "New filter", "icon": fcfg.get("icon", 0),
              "icon_color": fcfg.get("icon_color", 0), "description": "", "version": data.get("game_version") or ""}
    return {"header": header, "rules": doc_rules, "warnings": warnings}


def refresh_generated(config: dict, data: dict, rules: list[dict]) -> dict:
    """Regenerate a filter's [A] rules (unique/set groups, [[affix_rule]]s, class hide rules) from
    config.toml and the current game data, the way `build` does with a base filter. Rules
    keep their on/off state by name, and filled build slots stay as they are."""
    prefix = config.get("filter", {}).get("rule_prefix", "")
    if not prefix:
        raise ConfigError("[filter] rule_prefix is empty: generated rules can't be told apart")
    plan = plan_rules(config, data["uniques"])
    affix_rules, _, affix_warnings = plan_affix_rules(config, data["affixes"])
    generated = [render_rule(r) for r in plan.rules]
    top = [render_rule(r) for r in affix_rules]
    class_blocks = [render_rule(r) for r in plan_class_hide(config)]

    blocks = [node_to_xml(encode_rule(r, 0), 2) for r in rules]
    had_block = any(r.get("name", "").startswith(prefix) for r in rules)
    result = merge(BaseFilter(header=FilterHeader(name=""), blocks=blocks), generated, prefix, drop=[],
                   top=top, elsewhere=class_blocks)
    out, at = result.blocks, result.insert_at
    if not had_block:   # first time: under a separator named like UNIQUE, else above a bottom hide rule
        rest = out[:at] + out[at + len(generated):]
        infos = rule_infos(rest)
        seps = [i for i, info in enumerate(infos) if info.is_separator and re.search("UNIQUE", info.name, re.I)]
        if seps:
            at = seps[0] + 1
        elif infos and infos[-1].enabled and not infos[-1].conditions:
            at = len(rest) - 1
        else:
            at = len(rest)
        out = rest[:at] + generated + rest[at:]
    out, _ = insert_above_section(out, at, class_blocks)
    new_rules = parse_rule_blocks(out)

    old = {r["name"]: r for r in rules if "raw" not in r and r.get("name", "").startswith(prefix)}
    kept = 0
    for i, r in enumerate(new_rules):
        prev = old.get(r.get("name"))
        if not prev or "raw" in r:
            continue
        slot = [c for c in r["conditions"] if c["type"] == "UniqueModifiersCondition" and not c.get("uniques")]
        prev_filled = any(c["type"] == "UniqueModifiersCondition" and c.get("uniques") for c in prev["conditions"])
        if slot and prev_filled:      # a build slot filled in-game or in the editor: keep it whole
            new_rules[i] = prev
            kept += 1
        elif r["enabled"] != prev["enabled"]:
            r["enabled"] = prev["enabled"]
            kept += 1
    added = sum(1 for r in new_rules if r.get("name", "").startswith(prefix))
    return {"rules": new_rules, "removed": len(old), "added": added, "kept": kept,
            "warnings": plan.warnings + affix_warnings}


# --- the saved new-filter template ---------------------------------------------------

TEMPLATE_PARTS = [p for p in PARTS if p != "leveling"]


def make_template(config: dict, data: dict) -> dict:
    """The non-class-specific template: every part but leveling, no class, BiS without build
    affixes (its rules start disabled; New fills them in for a build)."""
    return build_starter(config, data, {"name": "New filter", "parts": TEMPLATE_PARTS, "leveling": {}})


def ensure_template(path: Path, config: dict, data: dict) -> bool:
    """Write the template to `path` unless it exists. Returns True when it was created."""
    if path.is_file():
        return False
    doc = make_template(config, data)
    write_filter(path, render_filter(doc))
    return True


def load_template(path: Path, config: dict, data: dict) -> dict:
    ensure_template(path, config, data)
    return parse_filter(path.read_bytes().decode("utf-8-sig"))


def new_from_template(config: dict, data: dict, template: dict, options: dict) -> dict:
    """A new filter from the saved template: [A] rules regenerated for the current game data,
    the class's hide and shatter rules switched on and its filter icon set, BiS rules filled with the build's affixes,
    and optionally the leveling / idol sections added. options: name, character_class,
    fill_bis, leveling (the Leveling tab's options, needed for BiS / leveling), add_leveling,
    idols (the Idol tab's options), icon / icon_color (the filter's icon; default: the class's)."""
    refreshed = refresh_generated(config, data, template["rules"])
    rules, warnings = refreshed["rules"], list(refreshed["warnings"])
    cls = options.get("character_class", "")
    prefix = config.get("filter", {}).get("rule_prefix", "")
    hide_name = config.get("class_hide", {}).get("name", "Hide non-{class} class non-legendary items")
    by_class = {f"{prefix}{hide_name.replace('{class}', c)}": c for c in CLASSES}
    by_class.update({f"SHATTER - {c.upper()} AFFIXES": c for c in CLASSES})
    if cls:
        for r in rules:
            if r.get("name") in by_class and "raw" not in r:
                r["enabled"] = by_class[r["name"]] == cls
    build = options.get("leveling")
    if options.get("fill_bis") and build is not None:
        bis = plan_bis(config, data, build, cls)[1:]   # the template keeps its own header
        rules, _, _ = place(rules, doc_infos(rules), parse_rule_blocks([render_rule(r) for r in bis]), "BIS - ",
                            section="BIS", fallback="top")
    if options.get("add_leveling") and build is not None:
        table = {k: v for k, v in build.items() if k != "enabled"}
        if cls:
            table["character_class"] = cls
        lev_opts = parse_leveling(table, data["bases"])
        lev = plan_leveling(lev_opts, data)
        warnings += [f"leveling: {w}" for w in lev.warnings]
        rules, _, _ = place(rules, doc_infos(rules), parse_rule_blocks([render_rule(r) for r in lev.rules]),
                            lev_opts.rule_prefix)
    if options.get("idols"):
        idol_opts = idols.parse_options(options["idols"])
        plan = idols.plan_idols(idol_opts, idols.idol_kinds(data))
        warnings += plan.warnings
        if plan.rules:
            rules, _, _ = place(rules, doc_infos(rules), parse_rule_blocks([render_rule(r) for r in plan.rules]),
                                idol_opts.rule_prefix, section="IDOL", fallback="top")
    header = {**template["header"], "name": options.get("name") or "New filter",
              "version": data.get("game_version") or template["header"].get("version", "")}
    if cls:   # the filter list shows the class's icon...
        header["icon"] = CLASS_FILTER_ICONS[cls]
    for key in ("icon", "icon_color"):   # ...unless one was picked
        if options.get(key) is not None:
            header[key] = int(options[key])
    return {"header": header, "rules": rules, "warnings": warnings}
