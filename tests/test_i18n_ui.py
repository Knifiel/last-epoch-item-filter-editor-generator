"""The editor's own texts in other languages: the game's terms (i18n.ui_terms), the catalog keys the dev tool
collects from app.js / index.html, and the shipped catalogs (lefilter/web/i18n)."""
import json
import re
import sys
from pathlib import Path

import pytest

from lefilter import i18n

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))
import translate_ui  # noqa: E402


@pytest.fixture
def terms(monkeypatch):
    def run(mapping, en, ui, code="de", skip=None):
        monkeypatch.setattr(i18n, "UI_GAME_TERMS", mapping)
        monkeypatch.setattr(i18n, "UI_TERM_SKIP", skip or {})
        return i18n.ui_terms(en, ui, code)
    return run


def test_game_terms_follow_the_editors_case_and_drop_stray_marks(terms):
    got = terms({"Large": ("BeamLarge", "LARGE"), "Duplicate": ("Dup", "duplicate"), "Unique": "RarUnique",
                 "Replace": "Repl", "Rarity": "Rar"},
                en={"BeamLarge": "LARGE", "Dup": "duplicate", "RarUnique": "Unique", "Repl": "Replace", "Rar": "Rarity"},
                ui={"BeamLarge": "SEHR GROß", "Dup": "duplizieren", "RarUnique": "(Unique)", "Repl": "Remplacer.", "Rar": "Seltenheit"})
    assert got == {"Large": "Sehr groß", "Duplicate": "Duplizieren", "Unique": "Unique", "Replace": "Remplacer",
                   "Rarity": "Seltenheit"}


def test_game_terms_take_the_editors_placeholders(terms):
    got = terms({"Requires Level {n}": ("Req", "Requires Level {0}")},
                en={"Req": "Requires Level {0}"}, ui={"Req": "Erfordert Stufe {0}"})
    assert got == {"Requires Level {n}": "Erfordert Stufe {n}"}


def test_a_game_term_the_game_now_words_differently_is_left_out(terms):
    mapping = {"Rarity": "Rar", "Keys": ("Res", "Resources"), "Exalted": "Ex"}
    en = {"Rar": "Rarity of items", "Res": "Resources", "Ex": "Exalted"}
    ui = {"Rar": "Seltenheit", "Res": "Ressourcen", "Ex": "Podniosłymi"}
    assert terms(mapping, en, ui, code="pl", skip={"pl": {"Exalted"}}) == {"Keys": "Ressourcen"}


def test_the_shipped_game_term_table_is_well_formed():
    for text, ref in i18n.UI_GAME_TERMS.items():
        key, game_en = ref if isinstance(ref, tuple) else (ref, text)
        assert key and game_en and text == text.strip()
        # the game's {0} {1} ... stand for the editor's placeholders in order
        assert len(re.findall(r"\{\d\}", game_en)) == len(re.findall(r"\{\w+\}", text)), text


def test_keys_from_the_scripts_calls():
    src = '''
      tx("Save"); tx('it\\'s'); tx(`Plain`); tx(`not ${x} this`);
      tx("A long " + "hint " +
         "joined");
      tk("Table label"); txn(rows.length, "{n} rule", "{n} rules", { at });
      txn(f(a, b), "one " + "{n}", "many {n}");
      tx(rule.type === "HIDE" ? "Hidden" : "Shown"); tx(label);
    '''
    plain, plural = translate_ui.js_keys(src)
    assert plain == {"Save", "it's", "Plain", "A long hint joined", "Table label", "Hidden", "Shown"}
    assert plural == {("{n} rule", "{n} rules"), ("one {n}", "many {n}")}


def test_keys_from_the_page():
    page = '''<title data-t>Editor</title><button id="b" data-t-title title="Save (Ctrl+S)" data-t>Save</button>
              <input data-t-placeholder placeholder="Filter rules by name…"><span data-t>Unique &amp; set</span>
              <button title="not marked">X</button>'''
    assert translate_ui.html_keys(page) == {"Editor", "Save (Ctrl+S)", "Save", "Filter rules by name…", "Unique & set"}


def test_placeholders_survive_the_trip_to_deepl():
    xml = translate_ui.to_xml("{n} rules & {what} <here>")
    assert xml == "<x>n</x> rules &amp; <x>what</x> &lt;here&gt;"
    assert translate_ui.from_xml("<x>what</x> : <x>n</x> règles &amp; &lt;ici&gt;") == "{what} : {n} règles & <ici>"


@pytest.mark.parametrize("code", sorted(translate_ui.LANGUAGES))
def test_every_catalog_is_complete_and_keeps_its_placeholders(code):
    path = translate_ui.CATALOGS / f"{code}.json"
    problems = translate_ui.catalog_problems(code, json.loads(path.read_text(encoding="utf-8")), translate_ui.collect())
    assert problems == []
