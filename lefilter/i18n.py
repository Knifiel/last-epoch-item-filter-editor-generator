"""Game-text translations for the editor's language selector, from the game's own string tables.

For every locale the game ships, data/lang/<code>.json maps ids to that locale's names: unique
items, item types and bases, affixes (the loot-filter picker's names), and each affix stat line,
resolved from the same table entries and prefix words as the English text (affixtext). The
editor overlays them on the English data; its own UI stays English. Rule names written into
filters stay English.

Language rules from the game's language models (DescriptorPreferences): Korean puts the value
after the text, leaves out the "to" / "of" words, puts stat modifier words last with the value
in front of them ("방어도 {0} 증가") and drops the value slot "{0}" from affix names.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import affixtext

TEXT_TABLES = ("Item_Affixes", "Descriptors", "Common")
TABLES = ("Item_Names", *TEXT_TABLES)
GRAMMAR_TAG = re.compile(r"(\[[MFNmfn]?[sp]\])")     # [ms] [fs] [ns] [p] ...: gender / number for the game's grammar
NAME_BRACES = re.compile(r"\{([^{}0-9][^{}]*)\}")    # Japanese {skill name} marks; {0} (value slot) stays
LANGUAGE_PREFS = {"ko": {"value_after": True, "omit_added_to": True, "omit_percent_of": True,
                         "modifiers_last": True, "values_prepend_modifiers": True, "strip_value_tag": True}}


def clean(text: str | None) -> str | None:
    """Displayable text: name braces removed, "{0}" kept as the value's place; of gendered
    variants ("[ms]Verfluchter[fs]Verfluchte...") the masculine singular, else the first."""
    if not text:
        return text
    parts = GRAMMAR_TAG.split(text)
    if len(parts) > 3:   # several variants: lead text + (marker, variant) pairs
        variants = list(zip(parts[1::2], parts[2::2]))
        chosen = next((v for m, v in variants if m.lower() == "[ms]" and v.strip()), None) \
            or next((v for _, v in variants if v.strip()), "")
        text = parts[0] + chosen
    else:
        text = "".join(parts[::2])
    return NAME_BRACES.sub(r"\1", text).strip()


def strip_value_tag(text: str) -> str:
    """Localization.StripValueTag: "{0}" out of a name, spaces collapsed."""
    return re.sub(r"\s+", " ", text.replace("{0}", "")).strip()


def build_language(tables: dict[str, dict[str, str]], data: dict, code: str = "") -> dict:
    tables = {t: {k: clean(v) for k, v in tables.get(t, {}).items()} for t in TABLES}
    names, affix_names = tables["Item_Names"], tables["Item_Affixes"]
    prefs = LANGUAGE_PREFS.get(code, {})
    words = {p: tables["Common"].get(k) for p, k in affixtext.WORD_KEYS.items()}
    out = {"uniques": {}, "base_types": {}, "subtypes": {}, "implicits": {}, "affixes": {}, "lines": {}, "categories": {},
           "value_after": bool(prefs.get("value_after"))}
    out["unique_tooltips"] = {}
    for u in data["uniques"]:
        if names.get(f"Unique_Name_{u['id']}"):
            out["uniques"][u["id"]] = names[f"Unique_Name_{u['id']}"]
        lines = [names.get(f"Unique_Tooltip_{line['desc']}_{u['id']}") if "desc" in line
                 else affixtext.resolve(line.get("source"), tables, words, prefs) for line in u.get("tooltip") or []]
        rolls = [affixtext.resolve(line.get("source"), tables, words, prefs) for line in u.get("rolls") or []]
        lore = names.get(f"Unique_Lore_{u['id']}")
        if any(lines) or any(rolls) or lore:   # None: the English text stays
            out["unique_tooltips"][u["id"]] = {"lines": lines, "rolls": rolls, "lore": lore}
    out["set_bonuses"] = {}   # set id -> its bonus lines (None: the English text stays; written ones have no translation)
    for st in data.get("sets", []):
        texts = [None if "desc" in line else affixtext.resolve(line.get("source"), tables, words, prefs) for line in st["bonuses"]]
        if any(texts):
            out["set_bonuses"][st["id"]] = texts
    for b in data["bases"]:
        if names.get(f"Item_BaseType_Name_{b['id']}"):
            out["base_types"][b["id"]] = names[f"Item_BaseType_Name_{b['id']}"]
        for s in b["subtypes"]:
            text = names.get(f"Item_SubType_Name_{b['id']}_{s['id']}")
            if text:
                out["subtypes"][f"{b['id']}/{s['id']}"] = text
            texts = [affixtext.resolve(line.get("source"), tables, words, prefs) for line in s.get("implicits") or []]
            if any(texts):
                out["implicits"][f"{b['id']}/{s['id']}"] = texts   # None: the English text stays
    out["categories"] = {}   # affix picker headers / categories (English name -> this language's)
    for c in sorted({a.get(k) for a in data["affixes"] for k in ("header", "category")} - {None, ""}):
        text = affix_names.get(f"Affix_Category_{c}") or tables["Common"].get(f"Affix_Category_{c}")
        if text:
            out["categories"][c] = text
    for a in data["affixes"]:
        name = (a.get("filter_name") and affix_names.get(f"Item_Affix_{a['id']}_FilterOverride")) \
            or affix_names.get(f"Item_Affix_{a['id']}_DisplayName")
        if name:
            out["affixes"][a["id"]] = strip_value_tag(name)
        texts = [affixtext.resolve(line.get("source"), tables, words, prefs) for line in a.get("lines", [])]
        if any(texts):
            out["lines"][a["id"]] = texts   # None: no entry - the English text stays
    return out


def write_languages(locales: list[tuple[str, str, Path]], shared: Path, data: dict, out_dir: Path,
                    warnings: list[str] | None = None) -> list[dict]:
    """Write data/lang/<code>.json for each locale; returns [{code, label}] (English first). A
    locale that can't be read is left out (with a warning)."""
    from .extract import read_string_tables   # extract imports this module
    out_dir.mkdir(parents=True, exist_ok=True)
    languages = []
    for code, label, bundle in locales:
        if code == "en":
            languages.insert(0, {"code": code, "label": label})
            continue
        try:
            lang = build_language(read_string_tables(bundle, shared, TABLES), data, code)
        except Exception as e:
            if warnings is not None:
                warnings.append(f"language {label} not extracted: {e}")
            continue
        (out_dir / f"{code}.json").write_text(json.dumps({"code": code, "label": label, **lang}, ensure_ascii=False),
                                              encoding="utf-8")
        languages.append({"code": code, "label": label})
    return languages
