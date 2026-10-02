"""Write THIRD_PARTY_LICENSES.txt for the packaged app: the license texts of Python and of every
installed package the app bundles (UnityPy, TypeTreeGeneratorAPI and their dependencies).

    python packaging/collect_licenses.py dist/THIRD_PARTY_LICENSES.txt
"""
from __future__ import annotations

import re
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOTS = ["UnityPy", "TypeTreeGeneratorAPI"]
EXCLUDED = {"pyfmodex"}   # left out of the build (lefilter.spec; fmod_toolkit goes in without its FMOD libraries)
LICENSE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.I)


def _name(requirement: str) -> str:
    return re.split(r"[\s;<>=!~\[(]", requirement, maxsplit=1)[0]


def closure(roots: list[str]) -> list[metadata.Distribution]:
    """The root distributions and everything they require (for this platform)."""
    seen: dict[str, metadata.Distribution] = {}
    todo = list(roots)
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen or key in EXCLUDED:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            marker = req.split(";", 1)[1] if ";" in req else ""
            if marker and "sys_platform" in marker and sys.platform not in marker and "!=" not in marker:
                continue
            todo.append(_name(req))
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def license_texts(dist: metadata.Distribution) -> list[str]:
    texts = []
    for f in dist.files or []:
        if LICENSE_FILE.search(str(f)):
            try:
                texts.append(Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip())
            except OSError:
                pass
    if not texts:
        meta = dist.metadata
        text = meta.get("License-Expression") or meta.get("License") or ""
        classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License")]
        texts.append("\n".join(filter(None, [text.strip(), *classifiers])) or "(no license text found)")
    return texts


def python_license() -> str | None:
    for base in (sysconfig.get_paths()["stdlib"], sys.base_prefix):
        for name in ("LICENSE.txt", "LICENSE"):
            p = Path(base) / name
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace").strip()
    return None


def main(out: str) -> None:
    sep = "\n\n" + "=" * 78 + "\n"
    parts = ["Third-party software bundled with Last Epoch Item Filter editor/generator.\n"
             "Cpp2IL (https://github.com/SamboyCoding/Cpp2IL, MIT) is not bundled: the program\n"
             "downloads it from its GitHub releases when it first reads a game build."]
    py = python_license()
    if py:
        parts.append(f"Python {sys.version.split()[0]}\n\n{py}")
    for dist in closure(ROOTS):
        meta = dist.metadata
        head = f"{meta['Name']} {dist.version}" + (f" - {meta['Home-page']}" if meta.get("Home-page") else "")
        parts.append(head + "\n\n" + "\n\n".join(license_texts(dist)))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(sep.join(parts) + "\n", encoding="utf-8")
    print(f"{out}: Python + {len(parts) - 2} packages")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "THIRD_PARTY_LICENSES.txt")
