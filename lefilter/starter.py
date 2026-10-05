"""Starter filters (the editor's New button) and refreshing the generated [A] rules of a filter.

A starter filter is built from parts, top to bottom: the [[affix_rule]]s, the shatter section (above
the class hide rules, so its rules for other classes' affixes can fire), the [class_hide] rules (the
chosen class's one enabled: it keeps other classes' items out of every rule below), the BiS section
(generic per-slot rules, switched off, which the editor's Best in slot tab replaces), generic [[exalted_rule]]s
(T8 first), a show-all-corrupted, a show-all-legendary, a show-all-cocooned and a 4xT5 rares rule under one
header, the unique / set groups, optionally the leveling section, and a bottom rule hiding everything else. That last one never hides shards, runes, glyphs
or keys: the game only applies rules made of non-equipment conditions to those
(Rule.MatchNonEquipment). Exalted, legendary and hide-everything rules get no rule prefix:
they belong to the filter from then on, like rules kept from a base filter.

Ordering convention: index 0 is the TOP of the in-game list.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime

from pathlib import Path

from . import __version__, bis, idols
from .filterdoc import encode_rule, node_to_xml, parse_filter, parse_rule_blocks, render_filter
from .filterxml import BaseFilter, FilterHeader, merge, render_rule, rule_infos, write_filter
from .gamedata import (ARMOUR_TYPES, CLASS_FILTER_ICONS, CLASSES, JEWELRY_TYPES, OFFHAND_TYPES, RARITIES, TYPE_IDS,
                       WEAPON_TYPES)
from .leveling import (CLASS_CATEGORIES, SECTION_OF, build_affixes, gear_affixes, parse_options as parse_leveling,
                       plan_leveling, rolling_on)
from .rules import (RULE_KEYS, ConfigError, Rule, RuleSpec, _check_keys, class_hide_name, plan_affix_rules, plan_class_hide, renamed_rules,
                    plan_rules, released_defaults, separator)
from .sections import (IDOL_PLACEMENT, class_hide_index, doc_infos, insert_position, place, place_class_hide,
                       place_leveling, place_shatter)

PARTS = {
    "personal": "Always show personal affixes ([[affix_rule]])",
    "shatter": "Shatter section: magic / rare gear with rare-roll affixes + class affixes ([shatter])",
    "class_hide": "Class item hide rules (the chosen class's one enabled)",
    "bis": "BiS section: generic per-slot rules, switched off - the Best in slot tab fills them ([bis])",
    "exalted": "Generic exalted rules, T8 first ([[exalted_rule]]), show all corrupted items ([starter] corrupted) "
               "and, below the legendary part, rares with four T5+ affixes ([starter] rares_4xt5)",
    "legendary": "Show all legendary items, then all cocooned items ([starter] cocooned)",
    "uniques": "Unique & set rules (the [[group]]s)",
    "leveling": "Leveling section (the Leveling tab's settings)",
    "hide_rest": "Hide everything else at the bottom",
}
LOOK_KEYS = RULE_KEYS - {"label", "lp_min", "lp_max", "ww_min", "ww_max"}
EXALTED_KEYS = LOOK_KEYS | {"name", "min", "tier", "total", "uncorrupted", "corrupted"}
STARTER_KEYS = {"header", "legendary", "corrupted", "cocooned", "rares_4xt5", "hide_rest"}
CORRUPTED_DEFAULT = {"name": "SHOW ALL CORRUPTED ITEMS", "color": 11}   # configs from before v0.3.0 have no [starter] corrupted
COCOONED_DEFAULT = {"name": "SHOW ALL COCOONED ITEMS", "color": 1}      # configs from before v0.3.3 have no [starter] cocooned
RARES_4XT5_DEFAULT = {"name": "SHOW 4xT5 RARES", "color": 4}            # configs from before v0.4.3 have no [starter] rares_4xt5
OLD_COCOONED = "COCOONED - all"   # before v0.3.3 an [A] rule among the uniques showed them (rule_prefix aside)
GEAR_TYPES = WEAPON_TYPES + OFFHAND_TYPES + ARMOUR_TYPES + JEWELRY_TYPES
GEAR_TYPE_IDS = {TYPE_IDS[t] for t in GEAR_TYPES}
# "altar" is obsolete (idol altars moved to the idol section) but still accepted: the packaged app
# keeps the config.toml copied on its first run, so v0.1.0 users' configs still have it.
BIS_KEYS = LOOK_KEYS | {"header", "tier", "min", "altar"}
SHATTER_KEYS = LOOK_KEYS | {"header", "max_weight", "include", "general_tier", "class_tier", "rarity"}


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
        uncorrupted, corrupted = options.pop("uncorrupted", False), options.pop("corrupted", False)
        if not name:
            raise ConfigError(f"{where}: needs a name")
        if uncorrupted and corrupted:
            raise ConfigError(f"{where}: corrupted and uncorrupted exclude each other")
        if not 1 <= n <= 6 or (tier is not None and not 1 <= tier <= 8):
            raise ConfigError(f"{where}: min must be 1-6 and tier 1-8")
        rules.append(Rule(name=name, group="exalted", spec=RuleSpec(**options), unique_ids=None, rarity=None,
                          affix_ids=ids, affix_min=n, affix_tier=tier, affix_total=total,
                          corruption="OnlyUncorrupted" if uncorrupted else "OnlyCorrupted" if corrupted else None))
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
    bases for a single type). Idol altars belong to the idol section."""
    cfg = config.get("bis", {})
    spec = _look(cfg, BIS_KEYS, "[bis]")
    tier, n = cfg.get("tier", 7), cfg.get("min", 1)
    opts = parse_leveling({k: v for k, v in build.items() if k != "enabled"}, data["bases"])
    if character_class:
        opts.character_class = character_class
    pools = build_affixes(opts, data["affixes"])   # each kind of gear's own picks
    names = {b["type"]: b["name"] for b in data["bases"]}

    def rule(name: str, types: list[str], pool: list[dict] | list[int], enabled: bool = True) -> Rule:
        ids = [a if isinstance(a, int) else a["id"] for a in pool]
        rs = RuleSpec(**{**spec.__dict__, "enabled": spec.enabled and enabled and bool(ids)})
        return Rule(name=name, group="bis", spec=rs, unique_ids=None, rarity=None, item_types=types,
                    affix_ids=ids, affix_min=n, affix_tier=_tier(tier))

    rules = [separator(cfg.get("header", "------ BIS ITEMS (pick the bases) ------"))]
    hands = list(dict.fromkeys(opts.weapons + opts.offhands))
    for t in hands:
        rules.append(rule(f"BIS - {names[t]} (pick bases)", [t], rolling_on(pools[SECTION_OF[t]], (t,))))
    if not hands:   # nothing to go on: a disabled rule to fill in (no item type matches nothing)
        rules.append(rule("BIS - Weapon (pick type & bases)", [], pools["weapons"], enabled=False))
    for t in ARMOUR_TYPES + JEWELRY_TYPES:
        rules.append(rule(f"BIS - {names[t]} (pick bases)", [t], rolling_on(pools[SECTION_OF[t]], (t,))))
    return rules


def plan_shatter(config: dict, data: dict, character_class: str = "") -> list[Rule]:
    """[shatter]: magic / rare gear (idols can't be shattered; exalted items have the exalted
    rules) with affixes worth shattering - one rule for non-class affixes that rarely roll
    (weighting <= max_weight, e.g. Hybrid Health, X and minion X penetration) and one per class
    for its class-specific affixes (the chosen class's one enabled)."""
    cfg = config.get("shatter", {})
    spec = _look(cfg, SHATTER_KEYS, "[shatter]")
    max_weight = cfg.get("max_weight", 0.15)
    include = {n.lower() for n in cfg.get("include", [])}
    pool = gear_affixes(data["affixes"])
    rare = [a["id"] for a in pool if a["category"] not in CLASS_CATEGORIES
            and (a.get("weight", 1) <= max_weight or {a["name"].lower(), (a.get("internal_name") or "").lower()} & include)]
    rarity = cfg.get("rarity", ["MAGIC", "RARE"])
    if not rarity or set(rarity) - set(RARITIES):
        raise ConfigError(f"[shatter] rarity: pick from {', '.join(RARITIES)}")
    common = dict(group="shatter", unique_ids=None, rarity=" ".join(r for r in RARITIES if r in rarity),
                  item_types=list(GEAR_TYPES))
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


def plan_cocooned(config: dict, data: dict) -> Rule | None:
    """[starter] cocooned: one rule showing every cocooned item - a box holding a random unique of its
    item type - below the legendary rule. None when switched off (cocooned = false) or the game has none."""
    table = config.get("starter", {}).get("cocooned", COCOONED_DEFAULT)
    if table is False:
        return None
    table = {"name": COCOONED_DEFAULT["name"], **table} if isinstance(table, dict) else COCOONED_DEFAULT
    _check_keys(table, LOOK_KEYS | {"name"}, "[starter] cocooned")
    ids = [u["id"] for u in sorted(data["uniques"], key=lambda u: (u["lpl"], u["name"]))
           if u.get("is_cocooned") and not u.get("hidden")]
    if not ids:
        return None
    options = dict(table)
    return Rule(name=options.pop("name"), group="starter", spec=RuleSpec(**options), unique_ids=ids, rarity="UNIQUE")


def plan_rares_4xt5(config: dict, affixes: list[dict]) -> Rule | None:
    """[starter] rares_4xt5: rare and exalted items with four gear affixes at T5+, whatever they are - at
    the bottom of the show-all rules. None when switched off (rares_4xt5 = false)."""
    table = config.get("starter", {}).get("rares_4xt5", RARES_4XT5_DEFAULT)
    if table is False:
        return None
    table = {"name": RARES_4XT5_DEFAULT["name"], **table} if isinstance(table, dict) else RARES_4XT5_DEFAULT
    return _named_rule(table, "[starter] rares_4xt5", rarity="RARE EXALTED", affix_ids=gear_affix_ids(affixes),
                       affix_min=4, affix_tier=5)


def legendary_name(config: dict) -> str:
    return config.get("starter", {}).get("legendary", {}).get("name", "SHOW ALL LEGENDARY ITEMS")


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
    if "shatter" in parts:   # above the class hide rules: other classes' affixes make their class's items
        rules += plan_shatter(config, data, cls)
    if "class_hide" in parts:   # right below them, where refreshing puts them too
        table = {**config.get("class_hide", {}), "add": True, "enabled_for": [cls] if cls else []}
        rules += plan_class_hide({**config, "class_hide": table})
    if "bis" in parts:
        rules += plan_bis(config, data, build, cls)
    exalted = plan_exalted(config, data["affixes"]) if "exalted" in parts else []
    corrupted = scfg.get("corrupted", CORRUPTED_DEFAULT)
    corrupted = {"name": CORRUPTED_DEFAULT["name"], **corrupted} if isinstance(corrupted, dict) else \
        CORRUPTED_DEFAULT if corrupted is True else corrupted
    if exalted and corrupted is not False:   # items that dropped corrupted, whatever their affixes (not uniques & co.)
        exalted.append(_named_rule(corrupted, "[starter] corrupted", rarity="NORMAL MAGIC RARE EXALTED",
                                   corruption="OnlyCorrupted"))
    legendary = (_named_rule(scfg.get("legendary", {"name": "SHOW ALL LEGENDARY ITEMS"}), "[starter] legendary",
                             rarity="LEGENDARY") if "legendary" in parts else None)
    cocooned = plan_cocooned(config, data) if "legendary" in parts else None
    rares = plan_rares_4xt5(config, data["affixes"]) if "exalted" in parts else None   # below the show-all rules
    if exalted or legendary or cocooned or rares:
        rules.append(separator(scfg.get("header", "------ EXALTED & LEGENDARY ------")))
        rules += exalted + [r for r in (legendary, cocooned, rares) if r]
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
        doc_rules, _, _ = place_leveling(doc_rules, doc_infos,
                                         None if lev_opts.endgame_only else parse_rule_blocks([render_rule(r) for r in lev.rules]),
                                         parse_rule_blocks([render_rule(r) for r in lev.endgame]), lev_opts.rule_prefix,
                                         lev_opts.endgame_prefix)
    header = {"name": options.get("name") or "New filter", "icon": fcfg.get("icon", 0),
              "icon_color": fcfg.get("icon_color", 0), "description": "", "version": data.get("game_version") or ""}
    return {"header": header, "rules": doc_rules, "warnings": warnings}


def apply_renames(config: dict, rules: list[dict], generated: set[str]) -> list[dict]:
    """rules with the generated ones a version renamed (renamed_rules) under their new names - only where
    this config generates the new name (generated) and not the old one, and the filter has no rule by the
    new name yet: a config keeping the old names keeps them."""
    names = {a: b for a, b in renamed_rules(config).items() if b in generated and a not in generated}
    have = {r.get("name") for r in rules}
    return [{**r, "name": names[r["name"]]} if "raw" not in r and r.get("name") in names and names[r["name"]] not in have else r
            for r in rules]


def refresh_generated(config: dict, data: dict, rules: list[dict]) -> dict:
    """Regenerate a filter's [A] rules (unique/set groups, [[affix_rule]]s, class hide rules) from
    config.toml and the current game data, the way `build` does with a base filter. Rules
    keep their on/off state by name, and filled build slots stay as they are."""
    prefix = config.get("filter", {}).get("rule_prefix", "")
    if not prefix:
        raise ConfigError("[filter] rule_prefix is empty: generated rules can't be told apart")
    plan = plan_rules(config, data["uniques"])
    rules = apply_renames(config, rules, {r.name for r in plan.rules})   # their state and filled slots carry over
    affix_rules, _, affix_warnings = plan_affix_rules(config, data["affixes"])
    generated = [render_rule(r) for r in plan.rules]
    top = [render_rule(r) for r in affix_rules]
    class_blocks = [render_rule(r) for r in plan_class_hide(config)]

    blocks = [node_to_xml(encode_rule(r, 0), 2) for r in rules]
    had_block = any(r.get("name", "").startswith(prefix) for r in rules)
    result = merge(BaseFilter(header=FilterHeader(name=""), blocks=blocks), generated, prefix, drop=[],
                   top=top, elsewhere=class_blocks, elsewhere_names=old_class_hide_names(config))
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
    at = class_hide_index([(i.name, not i.conditions) for i in rule_infos(out)], {BaseFilter.rule_name(b) for b in top})
    out = out[:at] + class_blocks + out[at:]   # right below the always-show rules and the shatter section
    new_rules = parse_rule_blocks(out)

    old = {r["name"]: r for r in rules if "raw" not in r and r.get("name", "").startswith(prefix)}
    kept = 0
    hide_name, old_hide = class_hide_name(config), old_class_hide_names(config)
    for i, r in enumerate(new_rules):
        if r.get("name") == hide_name and "raw" not in r:
            # the classes it hides are the user's pick: from this rule, else from what earlier
            # versions' per-class rules that are on hide
            prev = [old[hide_name]] if hide_name in old else [old[n] for n in old_hide if n in old and old[n]["enabled"]]
            picked = [set(c["classes"]) for x in prev for c in x["conditions"] if c["type"] == "ClassCondition" and "raw" not in c]
            cond = next((c for c in r["conditions"] if c["type"] == "ClassCondition"), None)
            if prev and cond is not None and picked:
                cond["classes"] = [c for c in CLASSES if c in set().union(*picked)]
                r["enabled"] = hide_name not in old or old[hide_name]["enabled"]
                kept += 1
            continue
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
    # The [A] rule that showed cocooned items before v0.3.3: the [starter] cocooned rule takes over, below the
    # legendary rule (else right above the uniques), on or off as the old one was.
    was = old.get(prefix + OLD_COCOONED)
    coc = plan_cocooned(config, data) if was is not None and was["name"] not in {r.name for r in plan.rules} else None
    if coc is not None:
        names = [r.get("name") for r in new_rules]
        if coc.name not in names:
            plan_names = {r.name for r in plan.rules}
            at = (names.index(legendary_name(config)) + 1 if legendary_name(config) in names
                  else next((i for i, n in enumerate(names) if n in plan_names), len(names)))
            new_rules.insert(at, parse_rule_blocks([render_rule(coc)])[0])
            names.insert(at, coc.name)
        new_rules[names.index(coc.name)]["enabled"] = was["enabled"]
        kept += 1
    added = sum(1 for r in new_rules if r.get("name", "").startswith(prefix))
    return {"rules": new_rules, "removed": len(old), "added": added, "kept": kept,
            "warnings": plan.warnings + affix_warnings}


def _old_class_hide(config: dict) -> list[Rule]:
    """The class hide rules earlier versions made, one per class, all off (as their template had them)."""
    old = released_defaults(config)
    return plan_class_hide({**old, "class_hide": {**old["class_hide"], "add": True, "enabled_for": []}}, per_class=True)


def old_class_hide_names(config: dict) -> dict[str, str]:
    """The per-class hide rule names of earlier versions (rule_prefix included) -> their class."""
    return {r.name: c for r, c in zip(_old_class_hide(config), CLASSES)}


def preset_class_hide(rule: dict, character_class: str) -> None:
    """The class hide rule set up for a class: on, ticking every other class."""
    cond = next((c for c in rule["conditions"] if c["type"] == "ClassCondition" and "raw" not in c), None)
    if cond is not None:
        cond["classes"] = [c for c in CLASSES if c != character_class]
        rule["enabled"] = True


def class_hide_spot(config: dict, data: dict) -> dict:
    """Names for sections.place_class_hide: {"top_names": the always-show rules, "hide_names": the
    class hide rule, and earlier versions' per-class ones}."""
    return {"top_names": [r.name for r in plan_affix_rules(config, data["affixes"])[0]],
            "hide_names": [class_hide_name(config), *old_class_hide_names(config)]}


def _catch_all(rule: dict) -> bool:
    return "raw" not in rule and rule.get("type") == "HIDE" and rule.get("enabled", True) and not rule.get("conditions")


def add_missing_sections(config: dict, data: dict, template: dict, rules: list[dict], options: dict) -> dict:
    """A filter that didn't start from New (e.g. `build --standalone`'s uniques-only one) completed
    with the template's parts: its [A] rules refreshed (which adds the always-show affix rules
    and the class hide rules), then each template section (a separator and the rules under it)
    the filter has none of - BiS (the template's generic rules), exalted & legendary, shatter -
    set up for the class as New sets them up and put where the template has it. A section the
    filter has any rule of stays as it is; the hide-everything catch-all is added at the very
    bottom (below a leveling section) unless the filter has one. options: character_class.
    Returns {"rules", "added": [names], "warnings"}."""
    prefix = config.get("filter", {}).get("rule_prefix", "")
    before = {r.get("name") for r in rules if r.get("name")}
    refreshed = refresh_generated(config, data, rules)
    full = new_from_template(config, data, template, {"character_class": options.get("character_class", "")})
    out = refreshed["rules"]
    if options.get("character_class"):   # the class hide rule, if this adds it: set up for the class, as New does
        for r in out:
            if r.get("name") not in before and r.get("name") == class_hide_name(config) and "raw" not in r:
                preset_class_hide(r, options["character_class"])
    sections: list[list[dict]] = []
    for r in full["rules"]:
        if not r.get("name") or "raw" in r:
            continue
        if not sections or (not r.get("conditions") and not r.get("enabled", True)):   # a separator starts one
            sections.append([])
        sections[-1].append(r)
    ours = (lambda r: prefix and r["name"].startswith(prefix)) if prefix else (lambda r: False)
    at, bottom = -1, []
    for section in sections:
        names = {x.get("name") for x in out}
        has_it = any(r["name"] in names for r in section if not ours(r) and not _catch_all(r))
        for r in section:
            index = next((i for i, x in enumerate(out) if x.get("name") == r["name"]), None)
            if index is not None:
                at = index
            elif _catch_all(r):
                if not any(_catch_all(x) for x in out):
                    bottom.append(r)
            elif not ours(r) and not has_it:   # generated rules the refresh doesn't make any more are left out
                at += 1
                out.insert(at, r)
    out += bottom
    added = [r["name"] for r in out if r.get("name") and r["name"] not in before]
    return {"rules": out, "added": added, "warnings": refreshed["warnings"] + full["warnings"]}


def _condition_less(rule: dict) -> bool:
    return "raw" not in rule and not rule.get("conditions")


def _section_end(rules: list[dict], start: int) -> int:
    """The end of the section a separator at `start` heads: the next condition-less rule."""
    j = start + 1
    while j < len(rules) and not _condition_less(rules[j]):
        j += 1
    return j


def restore_section(rules: list[dict], template: dict, header: str) -> dict:
    """The template's section headed by the separator `header` (it and the rules under it) put back
    into a filter, two ways: "add" adds the rules the filter has none of (by name), each after the
    rule it follows in the template; "replace" swaps the filter's section for the template's (its
    rules found elsewhere go too). A filter without that header gets the whole section after its
    BiS section, else before the uniques, else at the top. Returns {"found": the filter has the
    header, "matches": its section is the template's, "add" / "replace": {"rules", "added", "removed"}}."""
    ts = next((i for i, r in enumerate(template["rules"]) if r.get("name") == header and _condition_less(r)), None)
    if ts is None:
        raise ConfigError(f"the new-filter template has no {header!r} section")
    section = template["rules"][ts:_section_end(template["rules"], ts)]
    names = {r["name"] for r in section}
    fs = next((i for i, r in enumerate(rules) if r.get("name") == header and _condition_less(r)), None)
    fe = _section_end(rules, fs) if fs is not None else None

    def spot(rest: list[dict]) -> int:
        return insert_position(doc_infos(rest), "\0", section="\0", after="BIS", before="UNIQUE", fallback="top")[1]

    # replace: the template's section where the filter's was
    inside = set(range(fs, fe)) if fs is not None else set()
    gone = [i for i, r in enumerate(rules) if i in inside or ("raw" not in r and r.get("name") in names)]
    rest = [r for i, r in enumerate(rules) if i not in set(gone)]
    at = fs - sum(1 for i in gone if i < fs) if fs is not None else spot(rest)
    replace = {"rules": rest[:at] + copy.deepcopy(section) + rest[at:], "added": [r["name"] for r in section],
               "removed": [rules[i].get("name") or "" for i in gone]}
    # add: only what's missing
    present = {r.get("name") for r in rules if "raw" not in r}
    if fs is None:
        missing = [copy.deepcopy(r) for r in section if r["name"] not in present]
        at = spot(rules)
        out = rules[:at] + missing + rules[at:]
    else:
        out, at, end = list(rules), fs, fe
        for r in section[1:]:
            index = next((i for i, x in enumerate(out) if "raw" not in x and x.get("name") == r["name"]), None)
            if index is None:
                at += 1
                out.insert(at, copy.deepcopy(r))
                end += 1
            elif fs <= index < end:   # one moved out of the section doesn't decide where the next goes
                at = index
    add = {"rules": out, "added": [r["name"] for r in out if "raw" not in r and r.get("name") not in present], "removed": []}
    return {"found": fs is not None, "matches": fs is not None and rules[fs:fe] == section, "add": add, "replace": replace}


# --- the saved new-filter template ---------------------------------------------------
#
# The template is the user's to edit (in the editor). Next to it, .generated/<name> keeps the
# template as this program generated it; both carry a "generated by" stamp with the program
# version. When a different version starts, sync_template updates the user's template with a
# three-way merge (reconcile_template): the copy as generated is the reference that tells the
# user's edits apart from what the new version changed.

TEMPLATE_PARTS = [p for p in PARTS if p != "leveling"]
# Template rules earlier versions generated that this one doesn't (v0.1.0's BiS altar rule moved to the idol section).
LEGACY_TEMPLATE_RULES = {"BIS - Idol Altar (pick bases & affixes)"}
LAYOUT_VERSION = (0, 3, 1)   # templates from before it get the shatter section moved to the top
STAMP = re.compile(r"<!-- New-filter template generated by Last Epoch Item Filter Editor (\S+) -->")


def _version(text: str | None) -> tuple[int, ...]:
    """A version stamp as numbers ("0.3.0" -> (0, 3, 0)); no stamp = before any."""
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def make_template(config: dict, data: dict) -> dict:
    """The non-class-specific template: every part but leveling, no class, BiS without build
    affixes (its rules start disabled; New fills them in for a build)."""
    return build_starter(config, data, {"name": "New filter", "parts": TEMPLATE_PARTS, "leveling": {}})


def generated_copy(path: Path) -> Path:
    return path.parent / ".generated" / path.name


def template_stamp(path: Path) -> str | None:
    """The program version a template file says generated it (None: no stamp)."""
    if not path.is_file():
        return None
    m = STAMP.search(path.read_bytes()[:400].decode("utf-8-sig", errors="replace"))
    return m.group(1) if m else None


def write_template(path: Path, doc: dict, version: str | None = None) -> None:
    """A template file with the "generated by" stamp before the filter (an XML comment)."""
    stamp = f"<!-- New-filter template generated by Last Epoch Item Filter Editor {version or __version__} -->\n"
    write_filter(path, stamp + render_filter(doc))


def write_generated_template(path: Path, doc: dict) -> None:
    """The template and its copy as generated: from now on, edits to the template are the user's."""
    write_template(path, doc)
    write_template(generated_copy(path), doc)


def legacy_template_rules(config: dict, data: dict) -> dict[str, dict]:
    """LEGACY_TEMPLATE_RULES as their version generated them (rebuilt with this config and game
    data, the way v0.1.0's plan_bis did), and the per-class hide rules from before the single class
    hide rule: a user's copy that differs in any way was changed."""
    cfg = config.get("bis", {})
    spec = _look(cfg, BIS_KEYS, "[bis]")
    altar = [a["id"] for a in data["affixes"] if a["category"] == "Idol Altars" and not a["special"]]
    rule = Rule(name="BIS - Idol Altar (pick bases & affixes)", group="bis",
                spec=RuleSpec(**{**spec.__dict__, "enabled": spec.enabled and bool(altar)}), unique_ids=None,
                rarity=None, item_types=["IDOL_ALTAR"], affix_ids=altar, affix_min=cfg.get("min", 1),
                affix_tier=_tier(cfg.get("tier", 7)))
    return {r.name: parse_rule_blocks([render_rule(r)])[0] for r in [rule, *_old_class_hide(config)]}


def ensure_template(path: Path, config: dict, data: dict) -> bool:
    """Write the template to `path` unless it exists. Returns True when it was created."""
    if path.is_file():
        return False
    write_generated_template(path, make_template(config, data))
    return True


def _key(rule: dict) -> str:
    return rule.get("name") or json.dumps(rule, sort_keys=True)


def reconcile_template(base: list[dict] | None, mine: list[dict], fresh: list[dict]) -> tuple[list[dict], dict]:
    """Rules of the user's template (mine) updated from what the previous version generated
    (base) to what this one generates (fresh), rules matched by name:
    - a rule mine has as base had it takes fresh's version; one the user changed stays theirs;
    - a rule the user removed (in base, not in mine) stays removed;
    - a rule new in fresh goes right after the rule it follows there (at the top if none);
    - a rule fresh no longer makes goes, unless the user changed it; the user's own rules stay.
    Without a base (a template from before the stamp) mine's rules are kept as they are and the
    fresh rules mine lacks are added. Returns (rules, {"added", "updated", "kept", "dropped": [names]})."""
    by_base = {_key(r): r for r in base} if base is not None else None
    by_fresh = {_key(r): r for r in fresh}
    report = {"added": [], "updated": [], "kept": [], "dropped": []}
    out = []
    for r in mine:
        k = _key(r)
        untouched = by_base is not None and k in by_base and by_base[k] == r
        if k in by_fresh:
            if untouched:
                out.append(by_fresh[k])
                if by_fresh[k] != r:
                    report["updated"].append(k)
            else:
                out.append(r)
                if by_base is not None and k in by_base and by_fresh[k] != by_base[k]:
                    report["kept"].append(k)   # changed by both: the user's version wins
        elif untouched:
            report["dropped"].append(k)
        else:
            out.append(r)
    at = -1
    for r in fresh:
        k = _key(r)
        index = next((i for i, x in enumerate(out) if _key(x) == k), None)
        if index is not None:
            at = index
        elif by_base is None or k not in by_base:   # new in this version (removed by the user: stays removed)
            at += 1
            out.insert(at, r)
            report["added"].append(k)
    return out, report


def sync_template(path: Path, config: dict, data: dict, backup_dir: Path | None = None) -> dict | None:
    """Bring the template up to this program version (see reconcile_template), once per version:
    returns None when there was nothing to do, else {"from", "to", "created" or the report,
    "backup"}. The old template is copied to backup_dir first; each update is appended to
    .generated/updates.log next to the template."""
    if ensure_template(path, config, data):
        return {"from": None, "to": __version__, "created": True}
    stamp = template_stamp(path)
    base_path = generated_copy(path)
    if stamp == __version__:
        if template_stamp(base_path) != __version__:   # an update cut short after the template was written
            write_template(base_path, make_template(config, data))
        return None
    try:
        mine = parse_filter(path.read_bytes().decode("utf-8-sig"))
    except (ValueError, SyntaxError) as e:   # xml.etree's ParseError is a SyntaxError
        raise ConfigError(f"the new-filter template {path} can't be read ({e}); fix or delete it") from e
    fresh = make_template(config, data)
    had_copy = base_path.is_file()
    if had_copy:
        base = parse_filter(base_path.read_bytes().decode("utf-8-sig"))["rules"]
    else:
        # A template from before the stamp (v0.2.0 and older) has no copy as generated. Those
        # versions generated what this one does from the config with their defaults (released_defaults:
        # e.g. two Weaver's Will rules, no corrupted ones), plus rules since dropped: that is the
        # reference (a rule missing from the user's counts as removed), the dropped rules counting
        # as generated ones.
        legacy = legacy_template_rules(config, data)   # as generated: only an identical copy counts as untouched
        base = ([r for r in make_template(released_defaults(config), data)["rules"] if r["name"] != class_hide_name(config)]
                + [legacy[r["name"]] for r in mine["rules"] if r.get("name") in legacy])
    # rules this version renamed, under their new names on both sides: an untouched one updates, a changed one
    # (e.g. a filled build slot) stays the user's
    fresh_names = {r.get("name") for r in fresh["rules"]}
    base, mine_rules = apply_renames(config, base, fresh_names), apply_renames(config, mine["rules"], fresh_names)
    rules, report = reconcile_template(base, mine_rules, fresh["rules"])
    spot = class_hide_spot(config, data)
    top, hide = set(spot["top_names"]), set(spot["hide_names"])
    if _version(stamp) < LAYOUT_VERSION:   # once: the shatter section moved to the top
        rules = place_shatter(rules, top, hide)
    rules = place_class_hide(rules, top, hide)   # refreshing puts them there anyway
    # the [A] rules as New makes them (current game data; on/off, filled build slots, class picks kept):
    # New regenerates them anyway, so an obsolete one the user changed goes too
    if config.get("filter", {}).get("rule_prefix"):   # without a prefix there are no [A] rules to tell apart
        before = [r.get("name") for r in rules]
        rules = refresh_generated(config, data, rules)["rules"]
        after = {r.get("name") for r in rules}
        report["dropped"] += [n for n in before if n and n not in after and n not in report["dropped"]]
    backup = None
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{path.stem}-before-{__version__}-{datetime.now():%Y%m%d-%H%M%S}.xml"
        shutil.copyfile(path, backup)
    write_template(path, {**mine, "rules": rules})
    write_template(base_path, fresh)
    log = [f"{datetime.now():%Y-%m-%d %H:%M} {stamp or 'unstamped'} -> {__version__}"
           + ("" if had_copy else " (no copy as generated: compared with this version's template)")]
    log += [f"  {what}: {', '.join(names)}" for what, names in report.items() if names]
    with open(base_path.parent / "updates.log", "a", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    return {"from": stamp, "to": __version__, **report, "first": not had_copy, "backup": str(backup) if backup else None}


def describe_template_update(update: dict, path: Path) -> str:
    """sync_template's result in a sentence or two."""
    if update.get("created"):
        return f"Generated the new-filter template {path}"
    counts = ", ".join(f"{len(update[k])} {k}" for k in ("added", "updated", "dropped") if update.get(k)) or "no rule changes"
    text = (f"New-filter template updated from {update['from'] or 'an unstamped version'} to {update['to']}: {counts}"
            + (f"; your edits kept where this version changed the same rules ({len(update['kept'])})" if update.get("kept") else "")
            + ". Rules you removed stay removed.")
    return text + (f" The old one is in {update['backup']}." if update.get("backup") else "")


def load_template(path: Path, config: dict, data: dict) -> dict:
    ensure_template(path, config, data)
    return parse_filter(path.read_bytes().decode("utf-8-sig"))


def new_from_template(config: dict, data: dict, template: dict, options: dict) -> dict:
    """A new filter from the saved template: [A] rules regenerated for the current game data,
    the class's hide and shatter rules switched on and its filter icon set; nothing else unless
    asked: the BiS rules from the Best in slot tab's options (bis), the leveling section
    (add_leveling, with leveling = the Leveling tab's options), the idol section (idols = the
    Idol tab's options). options: name, character_class, bis, add_leveling, leveling, idols,
    icon / icon_color (the filter's icon; default: the class's)."""
    refreshed = refresh_generated(config, data, template["rules"])
    rules, warnings = refreshed["rules"], list(refreshed["warnings"])
    cls = options.get("character_class", "")
    by_class = {f"SHATTER - {c.upper()} AFFIXES": c for c in CLASSES}
    if cls:
        for r in rules:
            if "raw" in r:
                continue
            if r.get("name") in by_class:
                r["enabled"] = by_class[r["name"]] == cls
            elif r.get("name") == class_hide_name(config):
                preset_class_hide(r, cls)
    build = options.get("leveling")
    if options.get("bis"):   # the Best in slot tab's picks replace the template's generic BiS rules
        bis_opts = bis.parse_options(options["bis"])
        if cls:
            bis_opts.character_class = cls
        plan = bis.plan_bis(bis_opts, data)
        warnings += [f"BiS: {w}" for w in plan.warnings]
        if plan.rules:
            rules, _, _ = bis.place_bis(rules, plan.rules, bis_opts.header)
    if options.get("add_leveling") and build is not None:
        table = {k: v for k, v in build.items() if k != "enabled"}
        if cls:
            table["character_class"] = cls
        lev_opts = parse_leveling(table, data["bases"])
        lev = plan_leveling(lev_opts, data)
        warnings += [f"leveling: {w}" for w in lev.warnings]
        rules, _, _ = place_leveling(rules, doc_infos,
                                     None if lev_opts.endgame_only else parse_rule_blocks([render_rule(r) for r in lev.rules]),
                                     parse_rule_blocks([render_rule(r) for r in lev.endgame]), lev_opts.rule_prefix,
                                     lev_opts.endgame_prefix)
    if options.get("idols"):
        idol_opts = idols.parse_options(options["idols"])
        plan = idols.plan_idols(idol_opts, idols.idol_kinds(data), idols.altar_kind(data))
        warnings += plan.warnings
        if plan.rules:
            rules, _, _ = place(rules, doc_infos(rules), parse_rule_blocks([render_rule(r) for r in plan.rules]),
                                idol_opts.rule_prefix, **IDOL_PLACEMENT)
    header = {**template["header"], "name": options.get("name") or "New filter",
              "version": data.get("game_version") or template["header"].get("version", "")}
    if cls:   # the filter list shows the class's icon...
        header["icon"] = CLASS_FILTER_ICONS[cls]
    for key in ("icon", "icon_color"):   # ...unless one was picked
        if options.get(key) is not None:
            header[key] = int(options[key])
    return {"header": header, "rules": rules, "warnings": warnings}
