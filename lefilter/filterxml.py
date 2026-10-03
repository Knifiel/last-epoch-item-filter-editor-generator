"""Read and write Last Epoch loot filters (lootFilterVersion 9).

Output mirrors what the game itself writes: UTF-8 with BOM, CRLF line
endings, no trailing newline, same element order and indentation.

The XML stores rules bottom-up: the first <Rule> is the bottom of the in-game
list and <Order> 0 is the top. This module takes and returns rules in
in-game order (top first) and does the reversal internally.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from .gamedata import CLASSES, check_filter_version, flags_to_xml
from .rules import Rule

LOOT_FILTER_VERSION = 9
MAX_RULES = 200   # ItemFilter.MAX_RULES_PER_FILTER
NL = "\r\n"

_RULE_RE = re.compile(r"[ \t]*<Rule>.*?</Rule>", re.S)
_NAME_RE = re.compile(r"<nameOverride>(.*?)</nameOverride>", re.S)
_SEPARATOR_NAME_RE = re.compile(r"[-=]{3,}")

KEEP_KEYS = {"name", "rarity", "blanket", "section", "catch_all"}


def _nullable(tag: str, value: int | None, indent: str) -> str:
    if value is None:
        return f'{indent}<{tag} i:nil="true" />'
    return f"{indent}<{tag}>{value}</{tag}>"


def render_rule(rule: Rule, order: int = 0) -> str:
    """One <Rule> block. unique_ids None: no Uniques condition (matches every item of
    its rarity); []: an empty Uniques condition to fill in-game. A rule without any
    condition is a section separator."""
    s = rule.spec
    i4, i6, i8, i10, i12 = (" " * n for n in (4, 6, 8, 10, 12))
    conditions = []
    if rule.classes is not None:
        conditions += [f'{i8}<Condition i:type="ClassCondition">',
                       f"{i10}<req>{flags_to_xml(rule.classes, CLASSES, none='None', everything='Any')}</req>",
                       f"{i8}</Condition>"]
    if rule.item_types is not None:
        types = [f"{i12}<EquipmentType>{t}</EquipmentType>" for t in rule.item_types]
        subs = [f"{i12}<int>{s}</int>" for s in rule.sub_types]
        conditions += [f'{i8}<Condition i:type="SubTypeCondition">',
                       *([f"{i10}<type>", *types, f"{i10}</type>"] if types else [f"{i10}<type />"]),
                       *([f"{i10}<subTypes>", *subs, f"{i10}</subTypes>"] if subs else [f"{i10}<subTypes />"]),
                       f"{i8}</Condition>"]
    if rule.rarity:
        conditions += [f'{i8}<Condition i:type="RarityCondition">', f"{i10}<rarity>{rule.rarity}</rarity>",
                       f"{i8}</Condition>"]
    if rule.unique_ids == []:
        conditions.append(f'{i8}<Condition i:type="UniqueModifiersCondition" />')  # as the game writes it
    elif rule.unique_ids:
        conditions.append(f'{i8}<Condition i:type="UniqueModifiersCondition">')
        for uid in rule.unique_ids:
            # Empty <Rolls /> = no constraint on any modifier roll (the game writes this too).
            conditions += [f"{i10}<Uniques>", f"{i12}<UniqueId>{uid}</UniqueId>", f"{i12}<Rolls />", f"{i10}</Uniques>"]
        conditions.append(f"{i8}</Condition>")
    if rule.affix_ids is not None:
        # "At least affix_min of these affixes on the item" - same layout as the in-game editor; tier
        # limits use its advanced mode (each counted affix >= affix_tier, their tiers add up to >= affix_total).
        tier, total = rule.affix_tier, rule.affix_total
        conditions += [f'{i8}<Condition i:type="AffixCondition">', f"{i10}<affixes>",
                       *(f"{i12}<int>{a}</int>" for a in rule.affix_ids), f"{i10}</affixes>",
                       f"{i10}<comparsion>{'ANY' if tier is None else 'MORE_OR_EQUAL'}</comparsion>",
                       f"{i10}<comparsionValue>{tier or 0}</comparsionValue>",
                       f"{i10}<minOnTheSameItem>{rule.affix_min}</minOnTheSameItem>",
                       f"{i10}<combinedComparsion>{'ANY' if total is None else 'MORE_OR_EQUAL'}</combinedComparsion>",
                       f"{i10}<combinedComparsionValue>{total or 1}</combinedComparsionValue>",
                       f"{i10}<advanced>{'false' if tier is None and total is None else 'true'}</advanced>",
                       f"{i8}</Condition>"]
    potentials = (s.lp_min, s.lp_max, s.ww_min, s.ww_max)
    if any(v is not None for v in potentials):
        conditions.append(f'{i8}<Condition i:type="PotentialCondition">')
        for tag, value in zip(("MinLegendaryPotential", "MaxLegendaryPotential", "MinWeaversWill", "MaxWeaversWill"),
                              potentials):
            conditions.append(_nullable(tag, value, i10))
        for tag in ("MinWeaversTouch", "MaxWeaversTouch", "MinForgingPotential", "MaxForgingPotential"):
            conditions.append(_nullable(tag, None, i10))
        conditions.append(f"{i8}</Condition>")
    if rule.corruption is not None:
        conditions += [f'{i8}<Condition i:type="CorruptionCondition">', f"{i10}<Corruption>{rule.corruption}</Corruption>",
                       f"{i8}</Condition>"]
    if rule.char_level is not None:
        lo, hi = rule.char_level
        conditions += [f'{i8}<Condition i:type="CharacterLevelCondition">', f"{i10}<minimumLvl>{lo}</minimumLvl>",
                       f"{i10}<maximumLvl>{hi}</maximumLvl>", f"{i8}</Condition>"]
    lines = [f"{i4}<Rule>", f"{i6}<type>{s.action.upper()}</type>"]
    lines += [f"{i6}<conditions>", *conditions, f"{i6}</conditions>"] if conditions else [f"{i6}<conditions />"]
    lines += [
        f"{i6}<recolor>{'true' if s.color is not None else 'false'}</recolor>",
        f"{i6}<color>{s.color or 0}</color>",
        f"{i6}<isEnabled>{'true' if s.enabled else 'false'}</isEnabled>",
        f"{i6}<levelDependent_deprecated>false</levelDependent_deprecated>",
        f"{i6}<minLvl_deprecated>0</minLvl_deprecated>",
        f"{i6}<maxLvl_deprecated>0</maxLvl_deprecated>",
        f"{i6}<emphasized>{'true' if s.emphasized else 'false'}</emphasized>",
        f"{i6}<nameOverride>{escape(rule.name)}</nameOverride>",
        f"{i6}<SoundId>{s.sound}</SoundId>",
        f"{i6}<MapIconId>{s.map_icon}</MapIconId>",
        f"{i6}<BeamOverride>{'true' if s.beam_size else 'false'}</BeamOverride>",
        f"{i6}<BeamSizeOverride>{(s.beam_size or 'NONE').upper()}</BeamSizeOverride>",
        f"{i6}<BeamColorOverride>{s.beam_color}</BeamColorOverride>",
        f"{i6}<Order>{order}</Order>",
        f"{i4}</Rule>",
    ]
    return NL.join(lines)


@dataclass
class FilterHeader:
    name: str
    icon: int = 0
    icon_color: int = 0
    description: str = ""
    version: str = "1.0"

    def render(self, rule_blocks_xml_order: list[str]) -> str:
        desc = f"  <description>{escape(self.description)}</description>" if self.description else "  <description />"
        rules = (["  <rules>", *rule_blocks_xml_order, "  </rules>"] if rule_blocks_xml_order else ["  <rules />"])
        return NL.join([
            '<ItemFilter xmlns:i="http://www.w3.org/2001/XMLSchema-instance">',
            f"  <name>{escape(self.name)}</name>",
            f"  <filterIcon>{self.icon}</filterIcon>",
            f"  <filterIconColor>{self.icon_color}</filterIconColor>",
            desc,
            f"  <lastModifiedInVersion>{escape(self.version)}</lastModifiedInVersion>",
            f"  <lootFilterVersion>{LOOT_FILTER_VERSION}</lootFilterVersion>",
            *rules,
            "</ItemFilter>",
        ])


def _set_order(block: str, order: int) -> str:
    return re.sub(r"<Order>-?\d+</Order>", f"<Order>{order}</Order>", block, count=1)


def assemble(header: FilterHeader, blocks_top_first: list[str]) -> str:
    """Number rules (Order 0 = top) and emit them bottom-first as the game expects."""
    if len(blocks_top_first) > MAX_RULES:
        raise ValueError(f"{len(blocks_top_first)} rules - the game allows at most {MAX_RULES} per filter")
    numbered = [_set_order(b, i) for i, b in enumerate(blocks_top_first)]
    return header.render(list(reversed(numbered)))


def write_filter(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("﻿" + text).encode("utf-8"))


# --- reading / merging -----------------------------------------------------------

def _tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m[1] if m else None


@dataclass
class BaseFilter:
    header: FilterHeader
    blocks: list[str]          # in-game order, top first

    @staticmethod
    def rule_name(block: str) -> str:
        m = _NAME_RE.search(block)
        return _unescape(m[1]) if m else ""


def _unescape(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def read_filter(path: Path) -> BaseFilter:
    text = path.read_bytes().decode("utf-8-sig")
    version = _tag(text, "lootFilterVersion")
    check_filter_version(int(version) if version and version.strip().isdigit() else None, text, LOOT_FILTER_VERSION, f"{path.name}: ")
    rules_xml = _tag(text, "rules") or ""
    blocks = [b.replace("\r\n", "\n").replace("\n", NL) for b in _RULE_RE.findall(rules_xml)]
    header = FilterHeader(
        name=_unescape(_tag(text, "name") or path.stem),
        icon=int(_tag(text, "filterIcon") or 0),
        icon_color=int(_tag(text, "filterIconColor") or 0),
        description=_unescape(_tag(text, "description") or ""),
        version=_tag(text, "lastModifiedInVersion") or "",
    )
    return BaseFilter(header=header, blocks=list(reversed(blocks)))


@dataclass
class RuleInfo:
    """What the keep matchers look at for one base-filter rule."""
    name: str
    enabled: bool
    conditions: list[str]   # Condition i:type values
    rarities: set[str]      # flags of its RarityCondition, if any
    section: str = ""       # name of the separator heading the rule's section

    @property
    def is_separator(self) -> bool:
        """Condition-less rule named like '------ EXALTED ITEMS ------': a visual section header."""
        return not self.conditions and bool(_SEPARATOR_NAME_RE.search(self.name))


def rule_infos(blocks: list[str]) -> list[RuleInfo]:
    infos, section = [], ""
    for block in blocks:
        rarity = re.search(r"<rarity>(.*?)</rarity>", block)
        info = RuleInfo(
            name=BaseFilter.rule_name(block),
            enabled=re.search(r"<isEnabled>true</isEnabled>", block) is not None,
            conditions=re.findall(r'<Condition i:type="(\w+)"', block),
            rarities=set(rarity[1].split()) if rarity else set(),
        )
        if info.is_separator:
            section = info.name
        info.section = section
        infos.append(info)
    return infos


def keep_matcher(spec: dict):
    """Build a predicate from one `keep` entry; every given field must match."""
    unknown = set(spec) - KEEP_KEYS
    if unknown:
        raise ValueError(f"keep entry {spec}: unknown key(s) {sorted(unknown)}; allowed: {sorted(KEEP_KEYS)}")
    name = re.compile(spec["name"]) if "name" in spec else None
    section = re.compile(spec["section"]) if "section" in spec else None

    def match(r: RuleInfo) -> bool:
        return ((name is None or name.search(r.name) is not None)
                and ("rarity" not in spec or spec["rarity"].upper() in r.rarities)
                and ("blanket" not in spec or spec["blanket"] == ("SubTypeCondition" not in r.conditions))
                and (section is None or (r.section and section.search(r.section) is not None))
                and ("catch_all" not in spec or spec["catch_all"] == (r.enabled and not r.conditions)))
    return match


def _keep_flags(infos: list[RuleInfo], keep: list[dict] | None) -> list[bool]:
    """Which rules survive `keep`; a separator survives if anything in its section does."""
    if keep is None:
        return [True] * len(infos)
    matchers = [keep_matcher(k) for k in keep]
    flags = [any(m(i) for m in matchers) for i in infos]
    for idx, info in enumerate(infos):
        if info.is_separator and not flags[idx]:
            nxt = next((j for j in range(idx + 1, len(infos)) if infos[j].is_separator), len(infos))
            flags[idx] = any(flags[idx + 1:nxt])
    return flags


@dataclass
class MergeResult:
    blocks: list[str]
    removed: list[str]
    moved_above: list[str]
    left_out: list[str]
    insert_at: int


def merge(base: BaseFilter, generated: list[str], prefix: str, drop: list[str], after: str = "",
          keep_above: list[str] = (), keep: list[dict] | None = None, top: list[str] = (),
          elsewhere: list[str] = (), elsewhere_names=()) -> MergeResult:
    """Replace previously generated rules (by name prefix) and rules matching `drop`.

    With `keep`, only base rules matched by one of its entries (plus the
    separators of their sections) are carried over; everything else is left out.
    The new block goes where the first removed rule was; if nothing was removed,
    directly below the first rule whose name contains `after`, else at the top.
    Rules matching `keep_above` are moved directly above the block so they keep
    priority over it (e.g. build picks made in-game). `top` blocks go to the very
    top of the filter; their previous copies, like those of `elsewhere` blocks (which
    the caller places itself) and rules named in `elsewhere_names` (e.g. what earlier
    versions called them), never decide where the main block goes.
    """
    top_names = {BaseFilter.rule_name(b) for b in [*top, *elsewhere]} | set(elsewhere_names)
    drop_patterns = [re.compile(p) for p in drop]
    above_patterns = [re.compile(p) for p in keep_above]
    flags = _keep_flags(rule_infos(base.blocks), keep)
    kept, removed, above, left_out, insert_at = [], [], [], [], None
    for block, keep_it in zip(base.blocks, flags):
        name = BaseFilter.rule_name(block)
        if (prefix and name.startswith(prefix)) or any(p.search(name) for p in drop_patterns):
            removed.append(name)
            if insert_at is None and name not in top_names:
                insert_at = len(kept)
        elif not keep_it:
            left_out.append(name)
        elif any(p.search(name) for p in above_patterns):
            above.append(block)
        else:
            kept.append(block)
    if insert_at is None:
        insert_at = 0
        if after:
            hits = [i for i, b in enumerate(kept) if after in BaseFilter.rule_name(b)]
            if not hits:
                raise ValueError(f"no rule named like {after!r} in base filter")
            insert_at = hits[0] + 1
    return MergeResult(blocks=list(top) + kept[:insert_at] + above + generated + kept[insert_at:], removed=removed,
                       moved_above=[BaseFilter.rule_name(b) for b in above], left_out=left_out,
                       insert_at=len(top) + insert_at + len(above))
