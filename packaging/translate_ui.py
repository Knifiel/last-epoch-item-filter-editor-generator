"""Developer tool: the editor's own texts in the game's languages (lefilter/web/i18n/<code>.json).

    python packaging/translate_ui.py keys                 # the English texts the editor shows, counted
    python packaging/translate_ui.py terms [--snapshot D] # which of them are the game's own loot-filter words
    python packaging/translate_ui.py translate [--lang de ...] [--dry-run]
    python packaging/translate_ui.py check [--lang de ...]   # placeholders, plural forms, missing texts

The catalog keys are the English texts themselves: every literal passed to tx() / tk() / txn() in app.js,
index.html's data-t / data-t-title / data-t-placeholder texts, the labels the server sends (toggles, BiS
slots, enum names as the editor spells them) and the server messages listed in SERVER_TEXTS.

"terms" matches those texts against the game's English UI table (from the extracted snapshot) and prints
the mapping for lefilter/i18n.py UI_GAME_TERMS: at extraction the user's own install then supplies the
game's wording for them, in every language. Nothing of the game's text goes into this repository.

Those texts are left out of the catalogs (the install supplies them). "translate" fills each catalog with what
it lacks through DeepL (key file: ~/.config/leifeg/deepl-key,
never printed): the game's terms in that language (from the user's install) are its glossary, so the
sentences use the game's words; {placeholders} are kept out of the translation. A count-dependent text
("{n} rule|{n} rules") is translated once per plural form of the language, with a sample number in
place of {n}. Entries already in a catalog (reviewed or fixed by hand) are kept; texts no longer used
are dropped.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "lefilter" / "web"
CATALOGS = WEB / "i18n"
sys.path.insert(0, str(ROOT))

# game language code -> DeepL target language, glossary language, formality (as the game's own texts address the
# player), Intl plural forms with a sample number each (the forms the language has for whole numbers; "other" is
# the fallback the editor uses for a missing form). Sample 1: the form is for 1 alone, so its text may spell the
# number out ("Eine Regel"); None: the form also covers other numbers (French and Portuguese 0 and 1) but takes no
# sample DeepL would keep, so the English singular goes with {n} kept as it is.
LANGUAGES = {
    "de": ("DE", "de", "prefer_less", {"one": 1, "other": 25}),
    "fr": ("FR", "fr", "prefer_more", {"one": None, "other": 25}),
    "es-es": ("ES", "es", "prefer_less", {"one": 1, "other": 25}),
    "pt": ("PT-BR", "pt", None, {"one": None, "other": 25}),
    "pl": ("PL", "pl", "prefer_less", {"one": 1, "few": 23, "many": 25}),
    "ru": ("RU", "ru", "prefer_more", {"one": 21, "few": 23, "many": 25}),
    "jp": ("JA", "ja", "prefer_more", {"other": 25}),
    "ko": ("KO", "ko", None, {"other": 25}),
    "zh": ("ZH-HANS", "zh", None, {"other": 25}),
}
CONTEXT = ("Texts of the user interface of a loot filter editor for the video game Last Epoch: buttons, labels, hints, "
           "search box placeholders and messages; the player is addressed directly. A filter is a list of rules that show, "
           "hide or recolour dropped items. 'Build' means the player's character build; 'base' an item base type; 'picks' "
           "the user's selections; 'every other X' means all the remaining X; 'roll' how an affix or value rolled on an "
           "item; 'BiS' best in slot; 'Filter X…' in a search box means: narrow the list of X down by typing.")

# Messages the server sends in English (warnings, errors) that the editor shows: translated word for word
# or, with {placeholders}, as templates matched against the message (txServer in app.js).
SERVER_TEXTS = [
    # generators (bis.py, leveling.py, idols.py)
    "{slot}: pick the item types (and bases) the affixes are for",
    "{slot}: {n} picked affixes don't exist in this game version; left out",
    "{slot}: {n} picked affixes are for another class; left out",
    "{slot}: {n} picked affixes are for a class; left out",
    "{type}: {n} picked bases aren't in this game version; left out",
    "{type}: none of the picked bases is for {class}; no rule",
    "{type}: no {class} bases; no rule",
    "{type}: none of the picked affixes roll on it; no rule",
    "exclude: no affix named {names}",
    "{type}: no droppable bases below level {n}",
    "{type}: none of the selected affixes roll on it; showing bases only",
    "Armour: no selected affix rolls on it; no rule generated",
    "Jewelry & belts: no selected affix rolls on them; no rule generated",
    "good_bases: {type} has no bases named {names}",
    "{type} good bases: none of the build's affixes roll on it; no rule generated",
    "endgame_bases: {type} has no bases named {names}",
    "{type} endgame rares: none of the build's affixes roll on it; no rule generated",
    "{toggle}: only defensive affixes here, which weapons leave out "
    "(tick Include defensive affixes - weapon_affixes.defensive - to count them)",
    "{what}: rolls only on {where}, none of which is picked",
    "{kind}: {n} picked affixes can't roll on it; left out",
    "{kind}: ruleset {n} makes no rule of its own: ruleset {m} already shows everything it would",
    "Idol altar: some picked altars or affixes don't exist in this game version; left out",
    "unknown idol kind {key} skipped",
    # the item tester's checks (matcher.py)
    "{n} of the listed affixes on the item, needs {need}",
    "combined tier {total} is not {op} {value}",
    "has {affixes}",
    "(any)",
    "{condition}: not evaluated (unrecognised layout)",
    "{condition}: not evaluated",
    "rarity {rarity}",
    "rarity {rarity} not in {rarities}",
    "no item type selected",
    "{type} is not {types}",
    "base {base} not selected",
    "item type matches",
    "character level {n} in {min}-{max}",
    "character level {n} outside {min}-{max}",
    "no class selected",
    "item is not class-specific",
    "item class {classes}",
    "unique listed (roll ranges not checked)",
    "unique not listed (roll ranges not checked)",
    "corrupted",
    "not corrupted",
    "faction {faction}",
    "{pre} prefixes, {suf} suffixes",
    "only matches non-equipment items",
    "{n} WW",
    "{n} LP",
    "{n} WT",
    "{n} FP",
    "no WW",
    "no LP",
    "no WT",
    "no FP",
    "no potential range set",
    "item level {n} (approximate)",
    "rule layout not recognised; not evaluated",
]

# Game terms too plain to force into every sentence (verbs, small words, sizes): still the game's wording where
# the editor shows them alone, but not in the glossary.
GLOSSARY_SKIP = {"to", "at least", "Any", "Add", "Copy", "Delete", "Save", "Cancel", "Close", "Replace", "Sort", "Other",
                 "Type", "Class", "Show", "Hide", "None", "Smallest", "Very small", "Small", "Medium", "Large", "Very large",
                 "Largest", "Description", "Tier", "Normal"}

# More of the game's words for the sentences (not editor texts of their own): English -> (game UI key, a noun?).
# A lowercase English entry takes the game's word lowercased, except German nouns.
GLOSSARY_GAME = {
    "Idol altar": ("ItemContainer_123_Name", True), "idol altar": ("ItemContainer_123_Name", True),
    "idols": ("ItemContainer_29_Name", True), "Loot filter": ("LootFilter_Header_Label", True),
    "loot filter": ("LootFilter_Header_Label", True), "forging potential": ("ItemTooltipV2_Potential_ForgingPotential", True),
    "legendary potential": ("LootFilter_RarityCondition_LegendaryPotential", True),
    "condition": ("LootFilter_RuleEditor_Condition_Label", True), "Condition": ("LootFilter_RuleEditor_Condition_Label", True),
    "set item": ("GamblingNotification_SetItem_Label", True), "Set item": ("GamblingNotification_SetItem_Label", True),
    "character level": ("Rule_Holder_Character Level", True), "Character level": ("Rule_Holder_Character Level", True),
    "level": ("Rule_Holder_Level", True), "item": ("GamblingNotification_Item_Label", True), "items": ("ReportType_Items", True),
    "tier": ("OmenWindow_Tier", True), "affix": ("Rule_Holder_Affix", True), "affixes": ("AffixCondition_Affixes", True),
    "implicits": ("ItemTooltipV2_Implicits_Heading", True), "exalted": ("RarityCondition_Exalted", False),
    "legendary": ("RarityCondition_Legendary", False), "corrupted": ("Bazaar_Filter_Corrupted", False),
}
# By hand where the game has no single word (an item base - the game: "Item Base") or its word misleads
GLOSSARY_HAND = {
    "de": {"base": "Basis", "bases": "Basen", "Base": "Basis", "Bases": "Basen", "Forging potential": "Schmiedepotenzial",
           "Leveling": "Leveling", "leveling": "Leveling"},   # the tab, not "Stufe" (level)
    "fr": {"base": "base", "bases": "bases", "Base": "Base", "Bases": "Bases"},
    "es-es": {"base": "base", "bases": "bases", "Base": "Base", "Bases": "Bases"},
    "pt": {"base": "base", "bases": "bases", "Base": "Base", "Bases": "Bases"},
    "pl": {"base": "baza", "bases": "bazy", "Base": "Baza", "Bases": "Bazy", "Forging potential": "Potencjał wykucia",
           "forging potential": "potencjał wykucia", "affixes": "afiksy", "Affixes": "Afiksy", "exalted": "podniosły"},
    "ru": {"base": "база", "bases": "базы", "Base": "База", "Bases": "Базы", "Forging potential": "Потенциал ковки",
           "forging potential": "потенциал ковки"},
    "jp": {"base": "ベース", "bases": "ベース", "Base": "ベース", "Bases": "ベース"},
    "ko": {"base": "기본 유형", "bases": "기본 유형", "Base": "기본 유형", "Bases": "기본 유형"},
    "zh": {"base": "基底", "bases": "基底", "Base": "基底", "Bases": "基底"},
}


def glossary(code: str, terms: dict[str, str], ui: dict[str, str]) -> dict[str, str]:
    """The glossary DeepL gets for one language: the game's terms (bar the plain words), its words for core nouns,
    the hand-picked ones."""
    out = {k: v for k, v in terms.items() if k not in GLOSSARY_SKIP}
    for en, (key, noun) in GLOSSARY_GAME.items():
        word = (ui.get(key) or "").strip()
        if not word or re.search(r"[(:{.]", word):
            continue
        if en[:1].islower() and code not in ("jp", "ko", "zh") and not (code == "de" and noun):
            word = word[:1].lower() + word[1:]
        out.setdefault(en, word)
    out.update(GLOSSARY_HAND.get(code, {}))
    return out


STRING = r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\$]|\\.)*`'


def _unquote(lit: str) -> str:
    body = lit[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def _string_expr(src: str, i: int) -> tuple[str | None, int]:
    """A string literal, or literals joined with +, starting at src[i] (after spaces): (text, end)."""
    parts = []
    while True:
        m = re.compile(r"\s*(" + STRING + r")").match(src, i)
        if not m:
            return ("".join(parts) if parts else None), i
        parts.append(_unquote(m.group(1)))
        i = m.end()
        plus = re.compile(r"\s*\+").match(src, i)
        if not plus:
            return "".join(parts), i
        i = plus.end()


def _skip_arg(src: str, i: int) -> int:
    """Index after one call argument (up to its top-level comma or the closing paren)."""
    depth = 0
    while i < len(src):
        c = src[i]
        if c in "\"'`":
            m = re.compile(STRING).match(src, i)
            if m:
                i = m.end()
                continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif c == "," and depth == 0:
            return i
        i += 1
    return i


def js_keys(src: str) -> tuple[set[str], set[tuple[str, str]]]:
    plain, plural = set(), set()
    for m in re.finditer(r"\b(tx|tk|txn)\(", src):
        i = m.end()
        if m.group(1) == "txn":
            i = _skip_arg(src, i) + 1
            one, i = _string_expr(src, i)
            comma = re.compile(r"\s*,").match(src, i)
            other = _string_expr(src, comma.end())[0] if comma else None
            if one is not None and other is not None:
                plural.add((one, other))
            continue
        text, _ = _string_expr(src, i)
        if text is not None:
            plain.add(text)
        else:   # a computed text: the ternary's literal branches (tx(x ? "Shown" : "Hidden"))
            arg = src[i:_skip_arg(src, i)]
            plain.update(_unquote(x) for x in re.findall(r"[?:]\s*(" + STRING + r")", arg))
    return plain, plural


def html_keys(src: str) -> set[str]:
    out = set()
    for m in re.finditer(r"<(\w+)\b([^>]*)>", src):
        tag, attrs = m.group(1), m.group(2)
        if re.search(r"\sdata-t[\s>]|\sdata-t$", attrs + ">"):
            close = src.find(f"</{tag}>", m.end())
            out.add(html.unescape(src[m.end():close]).strip())
        for kind in ("title", "placeholder"):
            if f"data-t-{kind}" in attrs:
                out.add(html.unescape(re.search(rf'\s{kind}="([^"]*)"', attrs).group(1)))
    return out


def spaced(name: str) -> str:
    """CommonShards -> Common Shards, WovenEchoesRank10 -> Woven Echoes Rank 10 (flagLabel in app.js)."""
    return re.sub(r"([a-z])([A-Z0-9])", r"\1 \2", name).replace(" Of ", " of ")


def server_labels() -> set[str]:
    from lefilter import bis, gamedata
    from lefilter.leveling import TOGGLES
    cap = lambda s: s[:1] + s[1:].lower()
    out = {t.label for t in TOGGLES} | {label for _, label, _ in bis.SLOTS}
    out |= {cap(x) for x in (*gamedata.RARITIES, "SHOW", "HIDE")} | {cap(re.sub("^VERY", "VERY ", x)) for x in gamedata.BEAM_SIZES}
    out |= set(gamedata.CLASSES) | set(gamedata.FACTION_LABELS.values())
    out |= {re.sub(r"([a-z])([A-Z])", r"\1 \2", x) for x in (*gamedata.CORRUPTION, *gamedata.SEALED_TYPES)}
    out |= {cap(x.replace("_", " ")) for x in gamedata.LEVEL_CONDITION_TYPES}
    out |= {spaced(f) for _, flags in gamedata.FLAG_CONDITIONS.values() for f in flags}
    return out


def collect() -> dict[str, tuple[str, str] | None]:
    """Catalog key -> None (a plain text) or (one, other) for a count-dependent one ("one|other")."""
    plain, plural = js_keys((WEB / "app.js").read_text(encoding="utf-8"))
    plain |= html_keys((WEB / "index.html").read_text(encoding="utf-8")) | server_labels() | set(SERVER_TEXTS)
    keys = {k: None for k in sorted(plain) if re.search(r"[A-Za-z]", k)}
    for one, other in sorted(plural):
        keys[f"{one}|{other}"] = (one, other)
    return keys


# ---------- the game's words ----------

def snapshot_dir(given: str | None) -> Path:
    if given:
        return Path(given)
    snaps = sorted((ROOT / ".cache" / "game").glob("*/strings_shared.bundle"), key=lambda p: p.stat().st_mtime)
    if not snaps:
        sys.exit("no extracted game snapshot in .cache/game: run the editor once (it extracts the game data)")
    return snaps[-1].parent


def game_ui(snap: Path, code: str) -> dict[str, str]:
    """The game's UI table in one language: key -> text (as the language overlay cleans it)."""
    from lefilter.extract import read_string_tables
    from lefilter.i18n import clean
    bundle = snap / "strings_en.bundle" if code == "en" else \
        next(p for p in (snap / "locales").glob("*.bundle") if f"({code})" in p.name)
    return {k: clean(v) for k, v in read_string_tables(bundle, snap / "strings_shared.bundle", ("UI",))["UI"].items() if v}


def cmd_terms(args) -> None:
    from lefilter.i18n import UI_GAME_TERMS
    en = game_ui(snapshot_dir(args.snapshot), "en")
    by_text: dict[str, list[str]] = {}
    for k, v in en.items():
        by_text.setdefault(v.strip(), []).append(k)
    keys = [k for k, plural in collect().items() if plural is None]
    print("# English text -> game UI key (exact matches; check each one fits the editor's use)")
    for k in keys:
        if k in UI_GAME_TERMS:
            ok = en.get(UI_GAME_TERMS[k], "").strip() == k
            print(f"  {k!r}: {UI_GAME_TERMS[k]!r},{'' if ok else '   # ! the game text is now ' + repr(en.get(UI_GAME_TERMS[k]))}")
        elif k in by_text:
            cands = sorted(by_text[k], key=lambda x: (not x.startswith(("LootFilter", "RarityCondition")), len(x)))
            print(f"  NEW {k!r}: {cands[0]!r},   # also: {cands[1:4]}" if len(cands) > 1 else f"  NEW {k!r}: {cands[0]!r},")


# ---------- DeepL ----------

def deepl_key() -> str:
    path = Path.home() / ".config" / "leifeg" / "deepl-key"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        sys.exit(f"no DeepL key: put it in {path}")


class DeepL:
    def __init__(self, key: str):
        self.key = key
        self.base = "https://api-free.deepl.com" if key.endswith(":fx") else "https://api.deepl.com"
        self.chars = 0

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"DeepL-Auth-Key {self.key}", "Content-Type": "application/json",
                                              "User-Agent": "leifeg-translate-ui/1"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    text = res.read()
                    return json.loads(text) if text else {}
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 4:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise SystemExit(f"DeepL {method} {path}: HTTP {e.code} {e.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError) as e:   # the connection: try again
                if attempt < 4:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise SystemExit(f"DeepL {method} {path}: {e}") from None
        raise SystemExit("DeepL: too many retries")

    def glossary(self, name: str, lang: str, pairs: dict[str, str]) -> str | None:
        rows = [f"{s}\t{t}" for s, t in pairs.items() if s and t and "\t" not in s + t and "\n" not in s + t]
        if not rows:
            return None
        got = self.call("POST", "/v3/glossaries", {"name": name, "dictionaries": [
            {"source_lang": "en", "target_lang": lang, "entries": "\n".join(rows), "entries_format": "tsv"}]})
        return got["glossary_id"]

    def drop_glossary(self, gid: str) -> None:
        self.call("DELETE", f"/v3/glossaries/{gid}")

    def translate(self, texts: list[str], target: str, glossary: str | None, formality: str | None) -> list[str]:
        out = []
        for i in range(0, len(texts), 40):
            chunk = texts[i:i + 40]
            body = {"text": chunk, "source_lang": "EN", "target_lang": target, "tag_handling": "xml",
                    "ignore_tags": ["x"], "context": CONTEXT, "preserve_formatting": True}
            if glossary:
                body["glossary_id"] = glossary
            if formality:
                body["formality"] = formality
            self.chars += sum(map(len, chunk))
            out += [t["text"] for t in self.call("POST", "/v2/translate", body)["translations"]]
        return out


def to_xml(text: str) -> str:
    """{placeholders} -> <x>name</x>, which DeepL leaves as they are (ignore_tags); the rest escaped."""
    parts = re.split(r"(\{\w+\})", text)
    return "".join(f"<x>{p[1:-1]}</x>" if re.fullmatch(r"\{\w+\}", p) else html.escape(p, quote=False) for p in parts)


def from_xml(text: str) -> str:
    return html.unescape(re.sub(r"<x>(\w+)</x>", r"{\1}", text))


def check(en: str, out: str) -> list[str]:
    problems = []
    if sorted(re.findall(r"\{\w+\}", en)) != sorted(re.findall(r"\{\w+\}", out)):
        problems.append("placeholders differ")
    if "<" in out and "<" not in en:
        problems.append("markup left")
    return problems


def cmd_translate(args) -> None:
    from lefilter.i18n import ui_terms
    keys = collect()
    snap = snapshot_dir(args.snapshot)
    en_ui = game_ui(snap, "en")
    dl = None if args.dry_run else DeepL(deepl_key())
    CATALOGS.mkdir(exist_ok=True)
    report = []
    for code in args.lang or LANGUAGES:
        target, gl_lang, formality, forms = LANGUAGES[code]
        path = CATALOGS / f"{code}.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        # a text that is one of the game's words isn't in the catalog: the user's install supplies it
        needed = catalog_keys(code, keys)
        cat = {k: v for k, v in old.items() if k in needed}
        dropped = sorted(set(old) - set(cat))
        todo_plain = [k for k, p in needed.items() if p is None and k not in cat]
        todo_plural = [k for k, p in needed.items() if p is not None and k not in cat]
        # the game's own words: the glossary for the sentences
        ui = game_ui(snap, code)
        terms = ui_terms(en_ui, ui, code)
        sent = []   # (key, form or None, xml text)
        for k in todo_plain:
            sent.append((k, None, to_xml(k)))
        for k in todo_plural:
            one, other = keys[k]
            for form, sample in forms.items():
                text = one if form == "one" else other
                sent.append((k, form, to_xml(text if sample is None else text.replace("{n}", str(sample)))))
        print(f"{code}: {len(todo_plain)} texts, {len(todo_plural)} counted texts to translate"
              f" ({sum(len(t) for *_, t in sent)} chars), {len(dropped)} dropped, {len(terms)} game terms,"
              f" glossary {len(glossary(code, terms, ui))} entries")
        if args.dry_run or not sent:
            continue
        gid = dl.glossary(f"leifeg-{code}", gl_lang, glossary(code, terms, ui))
        try:
            done = list(zip(sent, dl.translate([t for *_, t in sent], target, gid, formality)))
        finally:
            if gid:
                dl.drop_glossary(gid)
        for (k, form, _), out in done:
            text = from_xml(out)
            if form is None:
                cat[k] = text
                problems = check(k, text)
            else:
                sample = forms[form]
                en = keys[k][0 if form == "one" else 1]
                problems = []
                if sample is not None and "{n}" in en:
                    hits = re.findall(rf"(?<![\d.,]){sample}(?![\d.,])", text)
                    if len(hits) == 1:
                        text = re.sub(rf"(?<![\d.,]){sample}(?![\d.,])", "{n}", text, count=1)
                    elif not (sample == 1 and not hits):   # 1 spelled out is fine; anything else is a mistake
                        problems.append(f"sample {sample} found {len(hits)}x")
                entry = cat.setdefault(k, {})
                entry[form] = text
                if form == "many":
                    entry.setdefault("other", text)
                spelled = sample == 1 and "{n}" not in text
                problems += check(en.replace("{n}", "") if spelled else en, text)
            if problems:
                report.append(f"{code}: {k!r}{' [' + form + ']' if form else ''} -> {text!r}: {', '.join(problems)}")
        ordered = {k: cat[k] for k in keys if k in cat}
        path.write_text(json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if dl:
        print(f"DeepL characters sent: {dl.chars}")
    for line in report:
        print("CHECK", line)


def catalog_keys(code: str, keys: dict) -> dict:
    """The texts a language's catalog holds: all but the game's own words (lefilter/i18n.py UI_GAME_TERMS), which
    come from the user's install at run time - no game text ships - unless that language skips one of them."""
    from lefilter.i18n import UI_GAME_TERMS, UI_TERM_SKIP
    return {k: p for k, p in keys.items() if k not in UI_GAME_TERMS or k in UI_TERM_SKIP.get(code, ())}


def catalog_problems(code: str, cat: dict, keys: dict) -> list[str]:
    """What's wrong with a catalog: texts it lacks or no longer used (or a game word, which the install supplies),
    emptied or lost {placeholders}, missing plural forms. (A form for 1 alone may leave {n} out: "Eine Regel".)"""
    forms = LANGUAGES[code][3]
    terms = set(keys) - set(catalog_keys(code, keys))
    keys = catalog_keys(code, keys)
    out = [f"missing: {k!r}" for k in keys if k not in cat] + \
        [f"the game's word, from the install: {k!r}" if k in terms else f"not used: {k!r}" for k in cat if k not in keys]
    for k, v in cat.items():
        if k not in keys:
            continue
        if keys[k] is None:
            if not isinstance(v, str) or not v.strip():
                out.append(f"empty: {k!r}")
            elif check(k, v):
                out.append(f"{', '.join(check(k, v))}: {k!r} -> {v!r}")
            continue
        if not isinstance(v, dict):
            out.append(f"not plural forms: {k!r}")
            continue
        for form in [*forms, "other"]:
            en = keys[k][0 if form == "one" else 1]
            text = v.get(form)
            if not isinstance(text, str) or not text.strip():
                out.append(f"no {form} form: {k!r}")
                continue
            want = en.replace("{n}", "") if forms.get(form) == 1 and "{n}" not in text else en
            if check(want, text):
                out.append(f"{', '.join(check(want, text))} [{form}]: {k!r} -> {text!r}")
    return out


def cmd_check(args) -> None:
    keys = collect()
    bad = 0
    for code in args.lang or LANGUAGES:
        path = CATALOGS / f"{code}.json"
        problems = catalog_problems(code, json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}, keys)
        bad += len(problems)
        for line in problems:
            print(f"{code}: {line}")
    print(f"{bad} problems")
    sys.exit(1 if bad else 0)


def cmd_keys(args) -> None:
    keys = collect()
    for k in keys:
        if args.verbose:
            print(repr(k))
    print(f"{len(keys)} texts ({sum(1 for p in keys.values() if p)} counted), {sum(len(k) for k in keys)} chars")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keys")
    k.add_argument("-v", "--verbose", action="store_true")
    t = sub.add_parser("terms")
    t.add_argument("--snapshot")
    tr = sub.add_parser("translate")
    tr.add_argument("--lang", action="append", choices=list(LANGUAGES))
    tr.add_argument("--snapshot")
    tr.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--lang", action="append", choices=list(LANGUAGES))
    args = ap.parse_args()
    {"keys": cmd_keys, "terms": cmd_terms, "translate": cmd_translate, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    main()
