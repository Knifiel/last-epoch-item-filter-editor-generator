"""Human-readable summary of what the generated filter contains."""
from __future__ import annotations

from .leveling import SECTION_LABELS, TOGGLE_BY_KEY, LevelingPlan
from .rules import CATEGORIES, Plan, categorize, lpl_histogram


def _rule_style(rule) -> str:
    if rule.is_separator:
        return "section separator"
    if rule.unique_ids == []:
        return "empty build slot - add items in-game and enable"
    spec = rule.spec
    bits = [spec.action.upper()]
    if spec.color is not None:
        bits.append(f"color {spec.color}")
    if spec.emphasized:
        bits.append("emphasized")
    if spec.beam_size:
        bits.append(f"beam {spec.beam_size}")
    if not spec.enabled:
        bits.append("DISABLED")
    return ", ".join(bits)


def histogram_markdown(uniques: list[dict], thresholds: dict) -> str:
    labels, table = lpl_histogram(uniques, thresholds)
    lines = ["| category | " + " | ".join(f"LPL {lab}" for lab in labels) + " | total |",
             "|---|" + "---:|" * (len(labels) + 1)]
    for c in CATEGORIES:
        row = table[c]
        if sum(row):
            lines.append(f"| {c} | " + " | ".join(str(n) for n in row) + f" | {sum(row)} |")
    return "\n".join(lines)


def _condition_bits(rule) -> str:
    bits = []
    if rule.item_types:
        bits.append(", ".join(rule.item_types) + (f" (bases {', '.join(map(str, rule.sub_types))})" if rule.sub_types else ""))
    if rule.rarity:
        bits.append(rule.rarity)
    if rule.affix_ids:
        bits.append(f"{rule.affix_min}+ of {len(rule.affix_ids)} affixes" + (f" T{rule.affix_tier}+" if rule.affix_tier else "")
                    + (f", tiers adding up to {rule.affix_sum}+" if rule.affix_sum else ""))
    if rule.char_level:
        bits.append(f"character level {rule.char_level[0]}-{rule.char_level[1]}")
    return "; ".join(bits)


def leveling_markdown(lev: LevelingPlan, data: dict) -> str:
    names = {b["type"]: b["name"] for b in data["bases"]}
    out = ["## Leveling section", ""]
    out += [f"- warning: {w}" for w in lev.warnings]
    out += ["| rule | conditions | look |", "|---|---|---|"]
    out += [f"| {r.name} | {_condition_bits(r) or '-'} | {_rule_style(r)} |" for r in lev.rules]
    if lev.endgame:
        out += ["", "### Endgame rares (their own section, right below the exalted rules)", "",
                "| rule | conditions | look |", "|---|---|---|"]
        out += [f"| {r.name} | {_condition_bits(r) or '-'} | {_rule_style(r)} |" for r in lev.endgame]
    if lev.windows:
        out += ["", "### Weapon / off-hand bases by character level", ""]
        for t, windows in lev.windows.items():
            out.append(f"- **{names.get(t, t)}**: " + "; ".join(
                f"{w.min}-{w.max}: " + ", ".join(f"{s['name']} ({s['level']})" for s in w.bases) for w in windows))
    out += ["", "### Affixes per toggle (as each kind of gear takes them)", ""]
    for section, toggles in lev.picked.items():
        for key, affixes in toggles.items():
            out.append(f"- {SECTION_LABELS[section]} · **{TOGGLE_BY_KEY[key].label}** ({len(affixes)}): "
                       + (", ".join(a["name"] for a in affixes) or "none"))
    if lev.class_affixes:
        out.append(f"- **Class affixes** ({len(lev.class_affixes)}): " + ", ".join(a["name"] for a in lev.class_affixes))
    return "\n".join(out)


def build_report(data: dict, config: dict, plan: Plan, filter_name: str, total_rules: int,
                 merge_info: str | None, affix_rules=(), affix_members=None, leveling: LevelingPlan | None = None,
                 class_rules=()) -> str:
    thresholds = {k: float(v) for k, v in config["rarity"].items()}
    out = [
        f"# {filter_name}",
        "",
        f"Game version {data.get('game_version')} (build {data['build_hash'][:12]}, Steam build {data.get('steam_build')}), "
        f"data extracted {data['extracted_at']}.",
        f"{len(plan.rules)} generated rules, {total_rules} rules in the filter (limit 200).",
    ]
    if merge_info:
        out += ["", merge_info]
    if plan.warnings:
        out += ["", "## Warnings", ""] + [f"- {w}" for w in plan.warnings]
    out += ["", "## Effective LPL distribution", "",
            "LPL = effective level for legendary potential; higher means LP rolls are rarer.", "",
            histogram_markdown(data["uniques"], thresholds)]

    if affix_rules:
        out += ["", "## Always-show affix rules (top of the filter)"]
        for r in affix_rules:
            out += ["", f"### {r.name} ({len(r.affix_ids)} affixes) - {_rule_style(r)}", "",
                    "| affix | category | id |", "|---|---|---:|"]
            out += [f"| {a['name']} | {a['category']} | {a['id']} |" for a in affix_members[r.name]]

    if class_rules:
        out += ["", "## Class item hide rules", "",
                "Hide class-specific items only the other classes can use; enable the one for the build's class.", ""]
        out += [f"- `{r.name}` - {r.rarity}; classes {', '.join(r.classes)} - {_rule_style(r)}" for r in class_rules]

    out += ["", "## Groups (top of the in-game list first)"]
    rules_by_group: dict[str, list] = {}
    for r in plan.rules:
        rules_by_group.setdefault(r.group, []).append(r)
    for group, members in plan.members.items():
        out += ["", f"### {group} ({len(members)} items)", ""]
        out += [f"- `{r.name}` - {_rule_style(r)}" for r in rules_by_group[group]]
        out += ["", "| unique | type | LPL | level | reroll | id |", "|---|---|---:|---:|---:|---:|"]
        for u in members:
            reroll = f"{u['reroll_chance']:.0%}" if u["can_drop_randomly"] else "-"
            out.append(f"| {u['name']} | {u['base_type_name']} | {u['lpl']} | {u['level']} | {reroll} | {u['id']} |")

    if leveling:
        out += ["", leveling_markdown(leveling, data)]

    if plan.uncovered:
        by_cat: dict[str, list] = {}
        for u in plan.uncovered:
            by_cat.setdefault(categorize(u, thresholds), []).append(u["name"])
        out += ["", "## Not handled by any generated rule", ""]
        out += [f"- **{c}** ({len(names)}): {', '.join(sorted(names))}" for c, names in by_cat.items()]
    return "\n".join(out) + "\n"
