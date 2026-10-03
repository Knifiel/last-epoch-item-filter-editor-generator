"""Decode unique items, base items, affixes, colours and English names from a game snapshot.

UniqueList and MasterPropertyList live in resources.assets, which ships without Unity type
trees, so they are decoded with a schema that `regenerate_schema` builds from the game's own
IL2CPP metadata via Cpp2IL (once per game build, cached in .cache/schema/<build>/; no schema
ships with this program). Every read is checked to consume the object's bytes exactly.
Everything else comes from bundles that embed their own type trees.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

try:   # UnityPy's audio export imports FMOD, which the packaged app leaves out (audio is never read here)
    import fmod_toolkit  # noqa: F401
except Exception:
    sys.modules.setdefault("fmod_toolkit", types.ModuleType("fmod_toolkit"))

import UnityPy

from . import affixtext, odin, tools
from .game import Game, locale_bundles, prune_cache, snapshot
from .i18n import TEXT_TABLES, write_languages
from .gamedata import (ARMOUR_TYPES, EQUIPMENT_TYPES, JEWELRY_TYPES, OFFHAND_TYPES, RARITY_COLOR_IDS, TYPE_IDS,
                       WEAPON_TYPES)

from .paths import SCHEMA_DIR           # optional hand-made type trees (checked after the cached ones)

WEAVERS_WILL = 1  # UniqueList.LegendaryType.WeaversWill
DATA_VERSION = 19  # bump when data/uniques.json gains fields, so `build` re-extracts


class ExtractError(Exception):
    pass


def _find_monobehaviours(env, *names: str) -> list:
    hits: dict[str, list] = {n: [] for n in names}
    for o in env.objects:
        if o.type.name == "MonoBehaviour":
            name = o.peek_name()
            if name in hits:
                hits[name].append(o)
    for name, found in hits.items():
        if len(found) != 1:
            raise ExtractError(f"expected one '{name}' asset, found {len(found)}")
    return [hits[n][0] for n in names]


def _find_monobehaviour(env, name: str):
    return _find_monobehaviours(env, name)[0]


# --- UniqueList -------------------------------------------------------------

def _schema_candidates(cache_root: Path, game: Game, cls: str = "UniqueList") -> list[Path]:
    regenerated = cache_root / "schema" / game.short_hash / f"{cls}.json"
    return [p for p in (regenerated, SCHEMA_DIR / f"{cls}.json") if p.is_file()]


def _read_or_regenerate(read, game: Game, cache_root: Path, cls: str):
    """read(schemas) with the known schemas, rebuilding the class's schema when none fits."""
    schemas = _schema_candidates(cache_root, game, cls)
    if schemas:
        try:
            return read(schemas)
        except ExtractError as e:
            print(f"{e}\nRebuilding the {cls} layout for this game build ...")
    else:
        print(f"Reading the {cls} layout from the game (once per game build) ...")
    return read([regenerate_schema(game, cache_root, cls)])


def _read_with_schemas(obj, schemas: list[Path], cls: str, validate=lambda d: None) -> dict:
    errors = []
    for schema in schemas:
        try:
            data = obj.read_typetree(nodes=json.loads(schema.read_text(encoding="utf-8")), check_read=True)
            validate(data)
            return data
        except Exception as e:  # layout mismatch shows up as EOF/size errors
            errors.append(f"{schema}: {e}")
    raise ExtractError(f"{cls} schema does not match this game build:\n  " + "\n  ".join(errors))


def _validate_uniques(entries: list[dict]) -> None:
    ids = [e["uniqueID"] for e in entries]
    if not entries or len(set(ids)) != len(ids) or any(not e["name"] for e in entries):
        raise ExtractError("UniqueList decoded but contents look wrong (empty, duplicate IDs or blank names)")


def read_unique_list(snap: Path, schemas: list[Path]) -> tuple[list[dict], str]:
    env = UnityPy.load(str(snap / "resources.assets"))
    obj = _find_monobehaviour(env, "UniqueList")
    data = _read_with_schemas(obj, schemas, "UniqueList", lambda d: _validate_uniques(d["uniques"]))
    return data["uniques"], obj.assets_file.unity_version


def read_property_list(snap: Path, schemas: list[Path], name: str = "MasterPropertyList", cls: str = "PropertyList",
                       key: str = "propertyInfoList") -> dict:
    """A stat display-rule list from resources.assets (percentage, rounding, plus sign ... per
    stat, as ModFormatting uses them): MasterPropertyList, AbilityPropertyList or PlayerPropertyList."""
    env = UnityPy.load(str(snap / "resources.assets"))
    obj = _find_monobehaviour(env, name)

    def validate(d):
        if not d[key]:
            raise ExtractError(f"{name} decoded but empty")
    return _read_with_schemas(obj, schemas, cls, validate)


# resources.assets classes read with generated schemas: (object name, class, list field).
PROPERTY_LISTS = {"PropertyList": ("MasterPropertyList", "propertyInfoList"),
                  "AbilityPropertyList": ("AbilityPropertyList", "list"),
                  "PlayerPropertyList": ("PlayerPropertyList", "list")}
SCHEMA_CLASSES = ("UniqueList", *PROPERTY_LISTS, "IdolsContainerGridDataList")
AFFIX_KINDS = {0: "prefix", 1: "suffix", 2: "special"}
ALTAR_BLOCKED, ALTAR_REFRACTED = 99, 100   # IdolsContainerGridData.CellBlockedId / RefractedSlotIdJump


def read_altar_grids(snap: Path, schemas: list[Path]) -> dict[int, list[list[int]]]:
    """Idol altar subtype -> its idol grid as rows, top first: 0 = no slot, 1 = idol slot,
    2 = refracted slot. IdolsContainerGridDataList keeps one int[,] per altar subtype (list index =
    subtype, GetSubtypeData) in Odin's binary format, indexed [x, y] (BlockedCellsPositions)."""
    env = UnityPy.load(str(snap / "resources.assets"))
    obj = _find_monobehaviour(env, "IdolsContainerGridDataList")
    raw = _read_with_schemas(obj, schemas, "IdolsContainerGridDataList")["serializationData"]["SerializedBytes"]
    try:
        top = odin.read(bytes(raw))
        layouts = top.get("data")[0][1]
        grids = {}
        for subtype, (_, node) in enumerate(layouts):
            m = odin.int_matrix(node.get("unlockMatrix"))   # m[x][y]
            grids[subtype] = [[0 if m[x][y] == ALTAR_BLOCKED else 2 if m[x][y] >= ALTAR_REFRACTED else 1
                               for x in range(len(m))] for y in range(len(m[0]))]
    except (odin.OdinError, TypeError, IndexError, AttributeError) as e:
        raise ExtractError(f"idol altar layouts not readable: {e}") from e
    return grids


def regenerate_schema(game: Game, cache_root: Path, cls: str = "UniqueList") -> Path:
    """Rebuild the type trees (LE.dll) of the classes in SCHEMA_CLASSES from GameAssembly.dll +
    global-metadata.dat; returns the one for `cls`. Only a failure for `cls` itself is an error."""
    try:
        TypeTreeGenerator = tools.type_tree_generator(cache_root / "tools")
    except tools.ToolError as e:
        raise ExtractError(str(e)) from e
    snap = snapshot(game, cache_root, include_il2cpp=True)
    unity_version = UnityPy.load(str(snap / "globalgamemanagers")).objects[0].assets_file.unity_version
    out_dir = cache_root / "cpp2il" / game.short_hash
    done = out_dir / ".complete"
    if not done.is_file():   # a run that was cut short leaves no marker and is redone
        try:
            exe = tools.ensure_cpp2il(cache_root / "tools")
        except tools.ToolError as e:
            raise ExtractError(str(e)) from e
        print("Running Cpp2IL on the game's code to recover class layouts (takes about a minute) ...")
        tmp = out_dir.with_name(out_dir.name + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        # dll_empty + attributeinjector keeps [SerializeField] on private fields,
        # which the type-tree generator needs to see e.g. levelRequirement.
        try:
            subprocess.run(
                [str(exe),
                 "--force-binary-path", str(snap / "GameAssembly.dll"),
                 "--force-metadata-path", str(snap / "global-metadata.dat"),
                 "--force-unity-version", unity_version,
                 "--output-as", "dll_empty", "--use-processor", "attributeinjector",
                 "--output-to", str(tmp)],
                check=True, stdout=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError) as e:
            raise ExtractError(f"Cpp2IL couldn't read the game's code ({e}); if an antivirus removed "
                               f"{exe.name}, allow it and start again") from e
        shutil.rmtree(out_dir, ignore_errors=True)
        tmp.replace(out_dir)
        done.write_text(tools.CPP2IL_VERSION, encoding="utf-8")
    try:
        gen = TypeTreeGenerator(unity_version, "AssetStudio")
        for dll in sorted(out_dir.glob("*.dll")):
            gen.load_dll(dll.read_bytes())
    except Exception as e:
        raise ExtractError(f"couldn't load the game's class layouts: {e}") from e
    folder = cache_root / "schema" / game.short_hash
    folder.mkdir(parents=True, exist_ok=True)
    for name in dict.fromkeys((cls, *SCHEMA_CLASSES)):
        try:
            nodes = json.loads(gen.get_nodes_as_json("LE.dll", name))
        except Exception as e:   # a class a later game build dropped: only `cls` is required here
            if name == cls:
                raise ExtractError(f"couldn't recover the {cls} layout from the game's code: {e}") from e
            continue
        (folder / f"{name}.json").write_text(json.dumps(nodes, indent=0), encoding="utf-8")
    return folder / f"{cls}.json"


# --- item, affix and colour lists, names, version ------------------------------

def read_master_lists(snap: Path) -> tuple[dict, dict, dict, dict | None, set[int]]:
    """MasterItemsList, MasterAffixesList, MasterColorList, the Idol Altar Property List and the
    ids of ailments whose increased effect adds penetration, from PermaLoad.bundle (the last two
    only shape affix texts: None / empty if missing)."""
    env = UnityPy.load(str(snap / "PermaLoad.bundle"))
    objs = _find_monobehaviours(env, "MasterItemsList", "MasterAffixesList", "MasterColorList")
    try:
        altar = _find_monobehaviour(env, "Idol Altar Property List").read_typetree()
    except ExtractError:
        altar = None
    return (*(o.read_typetree() for o in objs), altar, _penetration_ailments(env))


def _penetration_ailments(env) -> set[int]:
    """Ailment.effectOfIncreasedEffectiveness == AdditionalPenetration (1), by ailment id."""
    try:
        by_path = {o.path_id: o for o in env.objects}
        ailments = _find_monobehaviour(env, "AilmentList").read_typetree()["list"]
        rows = (by_path[r["m_PathID"]].read_typetree() for r in ailments if r["m_PathID"] in by_path)
        return {a["id"] for a in rows if a.get("effectOfIncreasedEffectiveness") == 1}
    except Exception:
        return set()


def base_item_levels(items: dict) -> dict[tuple[int, int], dict]:
    """(baseTypeID, subTypeID) -> {level, base_name}."""
    return {
        (base["baseTypeID"], sub["subTypeID"]): {"level": sub["levelRequirement"], "base_name": base["displayName"]}
        for base in items["EquippableItems"]
        for sub in base["subItems"]
    }


def build_bases(items: dict, names: dict[str, str], lists: affixtext.PropertyLists | None = None,
                tables: dict[str, dict[str, str]] | None = None, words: dict[int, str] | None = None) -> list[dict]:
    """Item types with their bases (sub types), as the loot filter's Item Type condition lists them,
    with what the editor's base tooltip shows: implicits (affixtext lines, empty without the stat
    display rules) and, for weapons, base attack rate and added weapon range."""
    category = {tid: cat["name"]
                for group in items["LootFilterVisualCategories"] for cat in group["categories"]
                for tid in cat["entries"]}
    bases = []
    for base in items["EquippableItems"]:
        tid = base["baseTypeID"]
        bases.append({
            "id": tid,
            "type": EQUIPMENT_TYPES.get(tid, f"TYPE_{tid}"),
            "name": names.get(f"Item_BaseType_Name_{tid}") or base["displayName"] or base["BaseTypeName"],
            "category": category.get(tid, ""),
            "weapon": bool(base["isWeapon"]),
            "affix_mod": round(base["affixEffectModifier"], 4),   # scales affix values on this type
            "subtypes": [{
                "id": sub["subTypeID"],
                "name": names.get(f"Item_SubType_Name_{tid}_{sub['subTypeID']}") or sub["displayName"] or sub["name"],
                "level": sub["levelRequirement"],
                "drops": not sub["cannotDrop"],
                "class": sub["classRequirement"],   # ClassRequirement bits, 0 = any class
                "omen": sub["affixEffectiveness"] == 1,   # AffixEffectiveness.OmenIdol
                # The enchanted versions of class idols (ItemList.IsHereticalIdol's table): crafted, never dropped.
                "heretical": sub["name"].startswith("Heretical "),
                # None: the stat display rules couldn't be read (the editor says "not extracted")
                "implicits": affixtext.implicit_lines(sub.get("implicits") or [], lists, tables or {}, words)
                if lists and lists.master else None,
                **({"attack_rate": round(sub["attackRate"], 4), "range": round(sub["addedWeaponRange"], 4)}
                   if base["isWeapon"] else {}),
            } for sub in base["subItems"]],
        })
    return bases


GEAR_IDS = {TYPE_IDS[t] for t in WEAPON_TYPES + OFFHAND_TYPES + ARMOUR_TYPES + JEWELRY_TYPES}
NON_GEAR_MAX_TIER = 7   # T8 only rolls on equipment: an idol / idol altar affix's 8th tier never rolls
FAKE_UNIQUE_MOD = 7     # AffixList.SpecialAffixType: the "Variant" mods of unique variants


def _tier_lines(a: dict, lists, tables, words) -> list[dict]:
    """affixtext.affix_lines, with the tiers an affix can't reach on what it rolls on left out."""
    lines = affixtext.affix_lines(a, lists, tables or {}, words) if lists and lists.master else []
    if not set(a["canRollOn"]) & GEAR_IDS:
        lines = [{**line, "tiers": line["tiers"][:NON_GEAR_MAX_TIER]} for line in lines]
    if a["specialAffixType"] == FAKE_UNIQUE_MOD and all(len({tuple(t) for t in line["tiers"]}) <= 1 for line in lines):
        lines = [{**line, "tiers": line["tiers"][:1]} for line in lines]   # a unique variant's fixed mod, no tiers
    return lines


def build_affixes(data: dict, lists: affixtext.PropertyLists | None = None,
                  tables: dict[str, dict[str, str]] | None = None, words: dict[int, str] | None = None) -> list[dict]:
    """Affixes with what the in-game affix picker and the leveling generator need.

    name = the loot-filter picker's name: its override where the game sets one, else the localized
    display name (AffixContentGenerator / Affix.getAffixDisplayName: Item_Affix_<id>_DisplayName; for
    the affixes whose name the game generates from the stat, that table holds the generated name),
    internal_name = the asset's own name (what the leveling toggles match phrases in), category = the
    picker's category (header = its group), class = ClassRequirement bits that may roll it
    (0 = any), special = AFFIX_SPECIAL key (0 = ordinary affix), idol = idol-only, rolls_on = base
    type ids it can roll on, prefix = prefix (else suffix), lines = how its stats read in-game
    with per-tier rolls (affixtext; empty without the stat display rules), std = its standard
    affix effect modifier, filter_name = whether name is the picker's override, order = [header,
    category] positions in the picker (it lists the headers and each one's categories in the game
    data's order, a category's affixes by name)."""
    categories = data["affixDisplayCategories"]
    header = {c: h["name"] for h in data["categoryHeaders"] for c in h["categories"]}
    order = {c: [i, j] for i, h in enumerate(data["categoryHeaders"]) for j, c in enumerate(h["categories"])}
    names = (tables or {}).get("Item_Affixes", {})

    def name(a):
        if a.get("affixLootFilterOverrideName"):
            return names.get(f"Item_Affix_{a['affixId']}_FilterOverride") or a["affixLootFilterOverrideName"]
        return names.get(f"Item_Affix_{a['affixId']}_DisplayName") or a["affixDisplayName"] or a["affixName"]
    return sorted(
        ({"id": a["affixId"],
          "name": name(a),
          "internal_name": a["affixDisplayName"] or a["affixName"],
          "filter_name": bool(a.get("affixLootFilterOverrideName")),
          "category": categories[a["displayCategory"]] if a["displayCategory"] < len(categories) else "",
          "header": header.get(a["displayCategory"], ""),
          "order": order.get(a["displayCategory"], [len(data["categoryHeaders"]), a["displayCategory"]]),
          "class": a["classSpecificity"],
          "special": a["specialAffixType"],
          "idol": a["rollsOn"] == 1,
          "prefix": a["type"] == 0,
          "kind": AFFIX_KINDS.get(a["type"], "special"),   # AffixList.AffixType
          "level": a["levelRequirement"],
          "weight": round(a["weighting"], 4),   # roll weighting: lower = rarer
          "rolls_on": sorted(a["canRollOn"]),
          "std": round(a["standardAffixEffectModifier"], 4),
          "lines": _tier_lines(a, lists, tables, words)}
         for a in data["singleAffixes"] + data["multiAffixes"]),
        key=lambda a: a["id"])


def _hex(c: dict) -> str:
    return "#%02X%02X%02X" % tuple(round(c[k] * 255) for k in "rgb")


def build_palette(colors: dict) -> dict:
    """Loot-filter colour presets (the rule colour number is the index), beam colour presets
    and each rarity's default label colour."""
    by_id = {c["id"]: c for c in colors["colors"]}
    return {
        "filter": [_hex(p["primary"]["color"]) for p in colors["lootFilterColorPresets"]],
        "beam": [_hex(p["primary"]["beamColor"]) for p in colors["lootFilterBeamColorPresets"]],
        "rarity": {r: _hex(by_id[cid]["color"]) for r, cid in RARITY_COLOR_IDS.items() if cid in by_id},
    }


def read_filter_icons(snap: Path, out_dir: Path) -> dict:
    """The loot-filter icon list (LootFilterSettingsPanelUI.icons: 0 = none) saved as white PNGs
    to tint in the editor, and the icon colour presets. Returns {"icons": [{id, name}], "colors": [hex]}."""
    env = UnityPy.load(str(snap / "PermaLoad.bundle"), str(snap / "monoscripts.bundle"))
    script_ids = {o.path_id for o in env.objects
                  if o.type.name == "MonoScript" and o.read().m_ClassName == "LootFilterSettingsPanelUI"}
    panel = next((o.read_typetree() for o in env.objects
                  if o.type.name == "MonoBehaviour" and o.read(check_read=False).m_Script.path_id in script_ids), None)
    if panel is None:
        raise ExtractError("LootFilterSettingsPanelUI not found")
    sprites = {o.path_id: o for o in env.objects if o.type.name == "Sprite"}
    out_dir.mkdir(parents=True, exist_ok=True)
    icons = []
    for i, ref in enumerate(panel["icons"]):
        sprite = sprites.get(ref["m_PathID"])
        if sprite is None:
            continue
        sprite.read().image.save(out_dir / f"{i}.png")
        icons.append({"id": i, "name": sprite.peek_name()})
    return {"icons": icons, "colors": [_hex(c) for c in panel["iconColors"]]}


def read_string_tables(bundle: Path, shared: Path, names: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Localization tables of one locale bundle: table name -> {key: text} (e.g. Unique_Name_42).
    Keys live in the shared bundle's table collections, texts in `<name>_<locale>` tables
    (Item_Names_en, Descriptors_es-ES ...)."""
    env = UnityPy.load(str(bundle), str(shared))
    rows, keys = {}, {}
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        obj_name = o.peek_name() or ""
        name = next((n for n in names if obj_name.startswith(n)), None)
        if name is None:
            continue
        data = o.read_typetree()
        if "m_TableData" in data and obj_name.startswith(f"{name}_"):
            rows[name] = data["m_TableData"]
        elif data.get("m_TableCollectionName") == name and "m_Entries" in data:
            keys[name] = {e["m_Id"]: e["m_Key"] for e in data["m_Entries"]}
    missing = [n for n in names if n not in rows or n not in keys]
    if missing:
        raise ExtractError(f"localization tables not found in {bundle.name}: {missing}")
    return {n: {keys[n][d["m_Id"]]: d["m_Localized"] for d in rows[n] if d["m_Id"] in keys[n]} for n in names}


def read_item_names(snap: Path) -> dict[str, str]:
    """Key -> English text from the Item_Names localization table (e.g. Unique_Name_42)."""
    return read_string_tables(snap / "strings_en.bundle", snap / "strings_shared.bundle", ("Item_Names",))["Item_Names"]


def read_game_version(snap: Path) -> str | None:
    env = UnityPy.load(str(snap / "globalgamemanagers"))
    for o in env.objects:
        if o.type.name == "PlayerSettings":
            try:
                return o.read_typetree(check_read=False).get("bundleVersion")
            except Exception:
                return None
    return None


# --- assembly -----------------------------------------------------------------

def build_records(uniques: list[dict], base_items: dict, names: dict[str, str]) -> tuple[list[dict], list[str]]:
    records, warnings = [], []
    for u in uniques:
        uid = u["uniqueID"]
        sub = u["subTypes"][0] if u["subTypes"] else 0
        base = base_items.get((u["baseType"], sub))
        if base is None:
            warnings.append(f"unique {uid} ({u['name']}): base item {u['baseType']}/{sub} not in item list")
        # Mirrors UniqueList.Entry.getLevelRequirement / getEffectiveLevelForLegendaryPotential.
        level = u["levelRequirement"] if u["overrideLevelRequirement"] else (base["level"] if base else 0)
        lpl = u["effectiveLevelForLegendaryPotential"] if u["overrideEffectiveLevelForLegendaryPotential"] else level
        records.append({
            "id": uid,
            "name": names.get(f"Unique_Name_{uid}") or u["displayName"] or u["name"],
            "internal_name": u["name"],
            "base_type": u["baseType"],
            "base_type_name": names.get(f"Item_BaseType_Name_{u['baseType']}") or (base["base_name"] if base else ""),
            "sub_type": sub,
            "level": level,
            "lpl": lpl,
            "weavers_will": u["legendaryType"] == WEAVERS_WILL,
            "can_drop_randomly": bool(u["canDropRandomly"]),
            "reroll_chance": round(u["rerollChance"], 4),
            "is_set": bool(u["isSetItem"]),
            "is_primordial": bool(u["isPrimordialItem"]),
            "is_cocooned": bool(u["isCocoonedItem"]),
            "hidden": bool(u["hideFromPlayers"]),
        })
    records.sort(key=lambda r: r["id"])
    return records, warnings


def extract(game: Game, cache_root: Path, out_path: Path, regen_schema: bool = False) -> dict:
    snap = snapshot(game, cache_root)
    if regen_schema:
        uniques, unity_version = read_unique_list(snap, [regenerate_schema(game, cache_root)])
    else:
        uniques, unity_version = _read_or_regenerate(lambda s: read_unique_list(snap, s), game, cache_root, "UniqueList")

    items, affix_list, colors, altar_list, penetration_ailments = read_master_lists(snap)
    tables = read_string_tables(snap / "strings_en.bundle", snap / "strings_shared.bundle", ("Item_Names",))
    names = tables["Item_Names"]
    records, warnings = build_records(uniques, base_item_levels(items), names)
    try:   # affix texts (the editor's value column); optional
        tables.update(read_string_tables(snap / "strings_en.bundle", snap / "strings_shared.bundle", TEXT_TABLES))
    except Exception as e:
        warnings.append(f"affix texts not extracted: {e}")
    common = tables.get("Common", {})
    words = {p: common.get(k) or affixtext.ENGLISH_WORDS[p] for p, k in affixtext.WORD_KEYS.items()}
    lists = {}
    for cls, (name, key) in PROPERTY_LISTS.items():
        try:
            lists[cls] = _read_or_regenerate(lambda s, n=name, c=cls, k=key: read_property_list(snap, s, n, c, k),
                                             game, cache_root, cls)
        except Exception as e:   # only the editor's affix value texts need them
            warnings.append(f"{name} not read (affix values may show wrong): {e}")
    property_lists = affixtext.PropertyLists.from_game(lists.get("PropertyList"), lists.get("AbilityPropertyList"),
                                                       lists.get("PlayerPropertyList"), altar_list,
                                                       penetration_ailments)
    by_id = {u["uniqueID"]: u for u in uniques}
    item_names = tables.get("Item_Names", {})
    for r in records:   # what the editor's unique tooltip shows
        u = by_id[r["id"]]
        r["tooltip"] = affixtext.unique_tooltip(u, property_lists, tables, words) if property_lists.master else None
        r["rolls"] = affixtext.unique_rolls(u, property_lists, tables, words)
        r["lore"] = (item_names.get(f"Unique_Lore_{r['id']}") or u.get("loreText") or "").strip()
    data = {
        "data_version": DATA_VERSION,
        "game_version": read_game_version(snap),
        "build_hash": game.build_hash,
        "steam_build": game.steam_build,
        "unity_version": unity_version,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "warnings": warnings,
        "uniques": records,
        "affixes": build_affixes(affix_list, property_lists, tables, words),
        "omen_affix_mod": round(items.get("omenIdolAffixEffectModifier", 0.0), 4),   # replaces the base's on omen idols
        "bases": build_bases(items, names, property_lists, tables, words),
        "palette": build_palette(colors),
    }
    try:   # the editor's altar tooltips: each altar's idol slots
        grids = _read_or_regenerate(lambda s: read_altar_grids(snap, s), game, cache_root, "IdolsContainerGridDataList")
        for b in data["bases"]:
            if b["type"] == "IDOL_ALTAR":
                for sub in b["subtypes"]:
                    if sub["id"] in grids:
                        sub["grid"] = grids[sub["id"]]
    except Exception as e:
        warnings.append(f"idol altar layouts not extracted: {e}")
    try:
        data["filter_icons"] = read_filter_icons(snap, out_path.parent / "filter_icons")
    except Exception as e:   # only the editor's icon picker needs them
        warnings.append(f"filter icons not extracted: {e}")
    try:   # the editor's language selector: game names / affix texts per game locale
        data["languages"] = write_languages(locale_bundles(snap), snap / "strings_shared.bundle", data,
                                            out_path.parent / "lang", warnings)
    except Exception as e:
        warnings.append(f"languages not extracted: {e}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    prune_cache(cache_root, game.build_hash)
    return data
