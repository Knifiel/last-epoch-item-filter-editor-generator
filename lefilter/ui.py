"""Local web editor: browse, preview and edit loot filters, generate leveling sections.

`python -m lefilter ui` serves lefilter/web/ on 127.0.0.1 with a small JSON API. Filters are
read from and written to two places only: the game's Filters folder ("game") and out/
("out"). Overwriting a file backs the old one up to .cache/backups/ first.
"""
from __future__ import annotations

import json
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
import tomllib
import webbrowser
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import gamedata
from .filterdoc import parse_filter, parse_rule_blocks, render_filter
from .filterxml import MAX_RULES, render_rule, write_filter
from .game import find_filters_dir
from . import idols
from .leveling import TOGGLES, LevelingOptions, parse_options, plan_leveling
from .sections import doc_infos, place
from .starter import (PARTS, TEMPLATE_PARTS, ensure_template, load_template, make_template, new_from_template,
                      refresh_generated)
from .matcher import Context, evaluate
from .rules import ConfigError

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
        ensure_template(template_file, self.config, data)
        self.ctx = Context(data)
        self.idol_kinds = idols.idol_kinds(data)
        self.backup_dir = backup_dir
        self.dirs = {"out": out_dir, "template": template_file.parent}
        game_dir = find_filters_dir()
        if game_dir:
            self.dirs["game"] = game_dir

    @property
    def config(self) -> dict:
        """config.toml, read fresh so edits apply without restarting the editor."""
        return tomllib.loads(self.config_path.read_text(encoding="utf-8"))

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
        text = render_filter(doc)
        backup = None
        if path.exists():
            if not body.get("overwrite"):
                raise FileExistsError(f"{path.name} already exists")
            backup = self._backup(path)
        write_filter(path, text)
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
        defaults = asdict(LevelingOptions())
        try:
            defaults.update(asdict(parse_options(lcfg, d["bases"])))
        except ConfigError:
            pass
        return {
            "game_version": d.get("game_version"),
            "palette": d["palette"],
            "bases": d["bases"],
            "omen_affix_mod": d.get("omen_affix_mod", 0.0),
            "affixes": d["affixes"],
            "uniques": [{k: u[k] for k in ("id", "name", "base_type", "base_type_name", "sub_type", "level", "lpl",
                                            "is_set", "weavers_will")} for u in d["uniques"]],
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
            "idol_kinds": [{**asdict(k), "subtypes": k.all_subtypes} for k in self.idol_kinds],
            "idol_defaults": asdict(idols.IdolOptions()),
            "filter_icons": d.get("filter_icons", {"icons": [], "colors": []}),
            "languages": d.get("languages") or [{"code": "en", "label": "English"}],
            "template": {"location": "template", "file": self.template_file.name,
                         "parts": [PARTS[p] for p in TEMPLATE_PARTS]},
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
            "picked": {k: [{"id": a["id"], "name": a["name"]} for a in v] for k, v in plan.picked.items()},
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
        plan = idols.plan_idols(opts, self.idol_kinds)
        new = parse_rule_blocks([render_rule(r) for r in plan.rules])
        result = {"rules": new, "warnings": plan.warnings, "prefix": opts.rule_prefix}
        if "rules" in body:
            current = body["rules"]
            merged, removed, at = place(current, doc_infos(current), new, opts.rule_prefix, section="IDOL",
                                        fallback="top")
            shadows = idols.shadowing_rules(merged, at)
            if shadows and new:
                result["warnings"] = result["warnings"] + [
                    "these rules above the section catch idols by type alone, so idols they match never reach "
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
        write_filter(self.template_file, render_filter(doc))
        return {"path": str(self.template_file), "backup": str(backup) if backup else None, "rules": len(doc["rules"])}

    def refresh(self, body: dict) -> dict:
        return refresh_generated(self.config, self.data, body["rules"])

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
                      "/api/refresh": api.refresh, "/api/filter/delete": api.delete, "/api/new": api.new,
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
