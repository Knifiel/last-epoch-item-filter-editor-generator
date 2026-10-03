"""Local web editor: browse, preview and edit loot filters, generate leveling sections.

`python -m lefilter ui` serves lefilter/web/ on 127.0.0.1 with a small JSON API. Filters are
read from and written to two places only: the game's Filters folder ("game") and out/
("out"). Overwriting a file backs the old one up to .cache/backups/ first.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import tomllib
import webbrowser
from dataclasses import asdict, replace
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import gamedata
from .filterdoc import parse_filter, parse_rule_blocks, render_filter
from .filterxml import MAX_RULES, render_rule, write_filter
from .game import find_filters_dir
from . import bis, cleanup, idols
from .leveling import (SECTIONS, TOGGLES, class_affix_choices, class_affixes, parse_options,
                       plan_leveling, toggle_affixes)
from .sections import IDOL_PLACEMENT, doc_infos, place, reorder_generated
from . import __version__
from .starter import (PARTS, TEMPLATE_PARTS, add_missing_sections, class_hide_spot, load_template, make_template,
                      new_from_template, refresh_generated, restore_section, sync_template, template_stamp,
                      write_generated_template, write_template)
from .matcher import Context, evaluate
from .rules import ConfigError, read_config

WEB_DIR = Path(__file__).resolve().parent / "web"
FILE_RE = re.compile(r"^[^/\\:*?\"<>|]+\.xml$", re.I)


class Api:
    def __init__(self, data: dict, config_path: Path, out_dir: Path, backup_dir: Path, template_file: Path,
                 icons_dir: Path, lang_dir: Path):
        self.data = data
        self.icons_dir = icons_dir
        self.lang_dir = lang_dir
        self.config_path = config_path
        self.template_file = template_file
        # a new program version brings the template up to date, keeping the user's edits (once per version)
        try:
            self.template_update = sync_template(template_file, self.config, data, backup_dir)
        except ConfigError as e:   # the editor still starts; the message says what to fix (New needs it)
            self.template_update = {"error": str(e)}
        self.ctx = Context(data)
        self.idol_kinds = idols.idol_kinds(data)
        self.altar = idols.altar_kind(data)
        self.backup_dir = backup_dir
        self.dirs = {"out": out_dir, "template": template_file.parent}
        game_dir = find_filters_dir()
        if game_dir:
            self.dirs["game"] = game_dir

    @property
    def config(self) -> dict:
        """config.toml, read fresh so edits apply without restarting the editor."""
        return read_config(self.config_path)

    # --- files ---------------------------------------------------------------------

    def _path(self, location: str, file: str) -> Path:
        if location not in self.dirs:
            raise ValueError(f"unknown location {location!r}")
        if not FILE_RE.match(file or ""):
            raise ValueError(f"bad file name {file!r}")
        return self.dirs[location] / file

    def filters(self) -> list[dict]:
        out = []
        for location, d in self.dirs.items():
            for p in sorted(d.glob("*.xml")):
                head = p.read_bytes()[:4096].decode("utf-8-sig", errors="replace")
                m = re.search(r"<name>(.*?)</name>", head, re.S)
                out.append({"location": location, "file": p.name, "name": m[1] if m else p.stem,
                            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                            "generated": "[auto-uniques" in head})
        return out

    def load(self, location: str, file: str) -> dict:
        doc = parse_filter(self._path(location, file).read_bytes().decode("utf-8-sig"))
        return {"location": location, "file": file, **doc}

    def save(self, body: dict) -> dict:
        path = self._path(body["location"], body["file"])
        doc = body["doc"]
        if len(doc["rules"]) > MAX_RULES:
            raise ValueError(f"{len(doc['rules'])} rules - the game allows at most {MAX_RULES} per filter")
        is_template = path.resolve() == self.template_file.resolve()
        stamp = template_stamp(path) if is_template else None
        backup = None
        if path.exists():
            if not body.get("overwrite"):
                raise FileExistsError(f"{path.name} already exists")
            backup = self._backup(path)
        if is_template:   # the user's edits; the stamp still says which version generated it
            write_template(path, doc, stamp)
        else:
            write_filter(path, render_filter(doc))
        return {"path": str(path), "backup": str(backup) if backup else None}

    def _backup(self, path: Path) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backup_dir / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}.xml"
        shutil.copyfile(path, backup)
        return backup

    def delete(self, body: dict) -> dict:
        """Delete a filter file; a copy goes to .cache/backups/ first."""
        if body["location"] == "template":
            raise ValueError("the new-filter template can't be deleted here (Rebuild template regenerates it)")
        path = self._path(body["location"], body["file"])
        if not path.is_file():
            raise FileNotFoundError(f"{path.name} doesn't exist")
        backup = self._backup(path)
        path.unlink()
        return {"path": str(path), "backup": str(backup)}

    # --- game data -------------------------------------------------------------------

    def meta(self) -> dict:
        d = self.data
        lcfg = {k: v for k, v in self.config.get("leveling", {}).items() if k != "enabled"}
        defaults = asdict(parse_options({}, d["bases"]))   # complete sections even when config.toml's [leveling] is broken
        try:
            opts = parse_options(lcfg, d["bases"])
            defaults.update(asdict(opts))
            # the editor keeps one list of class affix ids for every class (it sends the chosen class's)
            defaults["class_affixes"] = list(dict.fromkeys(
                a["id"] for c in gamedata.CLASSES for a in class_affixes(replace(opts, character_class=c), d["affixes"])[0]))
        except ConfigError:
            pass
        return {
            "game_version": d.get("game_version"),
            "palette": d["palette"],
            "bases": d["bases"],
            "omen_affix_mod": d.get("omen_affix_mod", 0.0),
            "affixes": d["affixes"],
            "uniques": [{**{k: u[k] for k in ("id", "name", "base_type", "base_type_name", "sub_type", "level", "lpl",
                                               "is_set", "weavers_will")},
                         "tooltip": u.get("tooltip"), "rolls": u.get("rolls") or [], "lore": u.get("lore", ""),
                         "hidden": bool(u.get("hidden"))}
                        for u in d["uniques"]],
            "enums": {"rarities": gamedata.RARITIES, "classes": gamedata.CLASSES, "factions": gamedata.FILTER_FACTIONS,
                      "faction_labels": gamedata.FACTION_LABELS, "corruption": gamedata.CORRUPTION, "comparsion": gamedata.COMPARSION,
                      "beam_sizes": gamedata.BEAM_SIZES, "sealed": gamedata.SEALED_TYPES,
                      "level_types": gamedata.LEVEL_CONDITION_TYPES,
                      "flag_conditions": {k: {"tag": tag, "flags": flags}
                                          for k, (tag, flags) in gamedata.FLAG_CONDITIONS.items()},
                      "weapons": gamedata.WEAPON_TYPES, "offhands": gamedata.OFFHAND_TYPES,
                      "class_icons": gamedata.CLASS_FILTER_ICONS},
            "toggles": [{"key": t.key, "label": t.label, "group": t.group} for t in TOGGLES],
            "leveling_defaults": defaults,
            "class_affixes": {c: [a["id"] for a in class_affix_choices(d["affixes"], c)] for c in gamedata.CLASSES},
            # per class ("" = none): toggle -> the base type ids its affixes roll on (which sections offer it)
            "toggle_rolls_on": {c: {k: sorted({i for a in v for i in a["rolls_on"]}) for k, v in
                                    toggle_affixes({}, d["affixes"], c, [t.key for t in TOGGLES]).items()}
                                for c in ("", *gamedata.CLASSES)},
            "sections": {s: {"key": key, "types": types} for s, (key, types) in SECTIONS.items()},
            "bis": {"slots": [{"key": k, "label": label, "types": list(types)} for k, label, types in bis.SLOTS],
                    # per class ("" = none): slot -> affix ids its picker offers
                    "pools": {c: {k: [a["id"] for a in bis.slot_pool(d["affixes"], k, c)] for k, _, _ in bis.SLOTS}
                              for c in ("", *gamedata.CLASSES)},
                    "defaults": asdict(bis.BisOptions()), "tier_defaults": bis.TIER_DEFAULTS,
                    "style_defaults": bis.STYLE_DEFAULTS},
            "idol_kinds": [{**asdict(k), "subtypes": k.all_subtypes} for k in self.idol_kinds],
            "idol_defaults": asdict(idols.IdolOptions()),
            "idol_altar": asdict(self.altar) if self.altar else None,
            "filter_icons": d.get("filter_icons", {"icons": [], "colors": []}),
            "languages": d.get("languages") or [{"code": "en", "label": "English"}],
            "template": {"location": "template", "file": self.template_file.name,
                         "parts": [PARTS[p] for p in TEMPLATE_PARTS], "update": self.template_update,
                         "generated_by": template_stamp(self.template_file)},
            "app_version": __version__,
            "max_rules": MAX_RULES,
            "locations": list(self.dirs),
        }

    # --- generators / preview --------------------------------------------------------

    def leveling(self, body: dict) -> dict:
        opts = parse_options(body.get("options", {}), self.data["bases"])
        plan = plan_leveling(opts, self.data)
        new = parse_rule_blocks([render_rule(r) for r in plan.rules])
        result = {
            "rules": new,
            "windows": {t: [{"min": w.min, "max": w.max,
                             "bases": [{"id": s["id"], "name": s["name"], "level": s["level"]} for s in w.bases]}
                            for w in ws] for t, ws in plan.windows.items()},
            "picked": {s: {k: [a["id"] for a in v] for k, v in toggles.items()} for s, toggles in plan.picked.items()},
            # before the sections' exclusions (the preview's per-affix checkboxes) and the excluded ids
            "candidates": {s: {k: [a["id"] for a in v] for k, v in toggles.items()}
                           for s, toggles in plan.candidates.items()},
            "excluded": {s: sorted(ids) for s, ids in plan.excluded.items()},
            "class_affixes": [a["id"] for a in plan.class_affixes],
            "warnings": plan.warnings,
            "prefix": opts.rule_prefix,
        }
        if "rules" in body:
            current = body["rules"]
            merged, removed, at = place(current, doc_infos(current), new, opts.rule_prefix)
            result.update(merged=merged, removed=removed, position=at)
        return result

    def idols(self, body: dict) -> dict:
        opts = idols.parse_options(body.get("options", {}))
        plan = idols.plan_idols(opts, self.idol_kinds, self.altar)
        new = parse_rule_blocks([render_rule(r) for r in plan.rules])
        result = {"rules": new, "warnings": plan.warnings, "prefix": opts.rule_prefix}
        if "rules" in body:
            current = body["rules"]
            merged, removed, at = place(current, doc_infos(current), new, opts.rule_prefix, **IDOL_PLACEMENT)
            shadows = idols.shadowing_rules(merged, at, altar=bool(opts.altar["bases"] or opts.altar["affixes"]))
            if shadows and new:
                result["warnings"] = result["warnings"] + [
                    "these rules above the section catch idols or altars by type alone, so items they match never reach "
                    "the generated rules: " + ", ".join(shadows)]
            result.update(merged=merged, removed=removed, position=at)
        return result

    def new(self, body: dict) -> dict:
        config = self.config
        template = load_template(self.template_file, config, self.data)
        return new_from_template(config, self.data, template, body.get("options", {}))

    def rebuild_template(self, body: dict) -> dict:
        """Regenerate the new-filter template from config.toml (the old one is backed up)."""
        backup = self._backup(self.template_file) if self.template_file.is_file() else None
        doc = make_template(self.config, self.data)
        write_generated_template(self.template_file, doc)
        return {"path": str(self.template_file), "backup": str(backup) if backup else None, "rules": len(doc["rules"])}

    def refresh(self, body: dict) -> dict:
        return refresh_generated(self.config, self.data, body["rules"])

    def bis(self, body: dict) -> dict:
        """The Best in slot tab's rules, and the open filter with them in its BiS section."""
        opts = bis.parse_options(body.get("options", {}))
        plan = bis.plan_bis(opts, self.data)
        result = {"rules": plan.rules, "warnings": plan.warnings, "prefix": bis.PREFIX}
        if "rules" in body:
            merged, removed, at = bis.place_bis(body["rules"], plan.rules, opts.header)
            result.update(merged=merged, removed=removed, position=at)
        return result

    def reorder(self, body: dict) -> dict:
        """The open filter with its generated sections back in their places (Reorder generated sections)."""
        try:
            spot = class_hide_spot(self.config, self.data)
        except (ConfigError, ValueError, KeyError, tomllib.TOMLDecodeError):   # a broken config.toml: the rest still works
            spot = {}
        prefix = self.config.get("filter", {}).get("rule_prefix", "") if spot else ""
        rules, moved = reorder_generated(body["rules"], {"bis": bis.PREFIX, "uniques": prefix, **body.get("prefixes", {})}, **spot)
        return {"rules": rules, "moved": moved}

    def bis_read(self, body: dict) -> dict:
        return bis.read_picks(body["rules"], self.data)

    def complete(self, body: dict) -> dict:
        """The open filter with the template's sections it lacks (Add missing sections)."""
        template = load_template(self.template_file, self.config, self.data)
        return add_missing_sections(self.config, self.data, template, body["rules"], body.get("options", {}))

    def restore(self, body: dict) -> dict:
        """The template's exalted & legendary section put back into the open filter, both ways (Restore exalted section)."""
        template = load_template(self.template_file, self.config, self.data)
        header = self.config.get("starter", {}).get("header", "------ EXALTED & LEGENDARY ------")
        return {"header": header, **restore_section(body["rules"], template, header)}

    def cleanup(self, body: dict) -> dict:
        """What each way of freeing rules would remove: {kind: {"rules": kept, "removed": [names]}}."""
        rules, lev = body["rules"], body.get("leveling", {})
        done = {"separators": cleanup.remove_separators(rules),
                "leveling": cleanup.remove_leveling(rules, lev.get("prefix", "[L] "), int(lev.get("cap", 60))),
                "common_uniques": cleanup.remove_common_uniques(rules, self.config, self.data["uniques"])}
        return {kind: {"rules": kept, "removed": removed} for kind, (kept, removed) in done.items()}

    def language(self, code: str) -> dict:
        """A locale's game-text overlay (data/lang/<code>.json)."""
        if not re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", code or ""):
            raise ValueError(f"bad language code {code!r}")
        return json.loads((self.lang_dir / f"{code}.json").read_text(encoding="utf-8"))

    def idols_read(self, body: dict) -> dict:
        return idols.read_picks(body["rules"], body.get("prefix", "[I] "), self.idol_kinds)

    def match(self, body: dict) -> dict:
        return evaluate(body["rules"], body["item"], int(body.get("level", 1)), self.ctx)


def _handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _api(self, fn) -> None:
            try:
                self._json(fn())
            except FileExistsError as e:
                self._json({"error": str(e), "exists": True}, HTTPStatus.CONFLICT)
            except (ValueError, KeyError, ConfigError, FileNotFoundError, tomllib.TOMLDecodeError) as e:
                self._json({"error": f"{type(e).__name__}: {e}" if isinstance(e, KeyError) else str(e)},
                           HTTPStatus.BAD_REQUEST)

        def _local(self) -> bool:
            """Only this page may use the API: localhost Host (no DNS rebinding) and, for writes,
            a same-origin JSON request (a cross-site page can't send one without a CORS preflight)."""
            port = self.server.server_port
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

        def do_GET(self):
            if not self._local():
                return self._send(403, b"forbidden", "text/plain")
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/meta":
                return self._api(api.meta)
            if url.path == "/api/filters":
                return self._api(api.filters)
            if url.path == "/api/filter":
                return self._api(lambda: api.load(q.get("location", ""), q.get("file", "")))
            if url.path == "/api/lang":
                return self._api(lambda: api.language(q.get("code", "")))
            if url.path.startswith("/icons/"):   # filter icons extracted from the game
                root, name = api.icons_dir.resolve(), url.path.removeprefix("/icons/")
            else:
                root = WEB_DIR
                name = "index.html" if url.path in ("/", "/index.html") else url.path.removeprefix("/static/")
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype)

        def do_POST(self):
            if not self._local() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad JSON"}, HTTPStatus.BAD_REQUEST)
            routes = {"/api/filter": api.save, "/api/leveling": api.leveling, "/api/match": api.match,
                      "/api/idols": api.idols, "/api/idols/read": api.idols_read,
                      "/api/refresh": api.refresh, "/api/cleanup": api.cleanup, "/api/filter/delete": api.delete,
                      "/api/new": api.new, "/api/complete": api.complete, "/api/bis": api.bis,
                      "/api/bis/read": api.bis_read, "/api/reorder": api.reorder, "/api/restore": api.restore,
                      "/api/template/rebuild": api.rebuild_template}
            fn = routes.get(urlparse(self.path).path)
            if not fn:
                return self._json({"error": "not found"}, 404)
            self._api(lambda: fn(body))

    return Handler


def _open_browser(url: str) -> None:
    try:
        is_wsl = "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        is_wsl = False
    if is_wsl:  # hand the URL to the Windows default browser
        try:
            subprocess.run(["cmd.exe", "/c", "start", "", url], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd="/mnt/c")
            return
        except OSError:
            pass
    webbrowser.open(url)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second editor bind a port the first still listens on.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], ConnectionError):   # the browser dropped a request: nothing to report
            return
        super().handle_error(request, client_address)


def _bind(handler, port: int) -> ThreadingHTTPServer:
    """The server on `port`, or the next free one (e.g. when the editor is already open)."""
    for p in ([port + i for i in range(10)] if port else []) + [0]:
        try:
            return _Server(("127.0.0.1", p), handler)
        except OSError:
            continue
    raise OSError("no free port on 127.0.0.1")


def serve(api: Api, port: int, open_browser: bool) -> None:
    server = _bind(_handler(api), port)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Filter editor running at {url}  (Ctrl+C or close this window to stop)")
    for location, d in api.dirs.items():
        print(f"  {location:8} filters: {d}")
    if open_browser:
        threading.Timer(0.5, _open_browser, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        server.server_close()
