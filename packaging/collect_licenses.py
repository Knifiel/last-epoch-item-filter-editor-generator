"""Write THIRD_PARTY_LICENSES.txt for the packaged app: Python's license, every bundled Python
package's license, notices for third-party code compiled into those packages
(NOTICES-native.txt) and, on Debian/Ubuntu build machines, the copyright files of the system
libraries PyInstaller bundled. Fails when something that must not be redistributed got in.

    python packaging/collect_licenses.py dist/THIRD_PARTY_LICENSES.txt build/lefilter/bundled-binaries.txt
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOTS = ["UnityPy"]
# Left out of the build (see lefilter.spec): FMOD is proprietary, TypeTreeGeneratorAPI is fetched on
# the user's computer instead.
EXCLUDED = {"fmod-toolkit", "pyfmodex", "typetreegeneratorapi"}
FORBIDDEN = ("libreadline", "fmod", "typetreegeneratorapi", "libcapstone")   # never in the bundle
LICENSE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.I)
NATIVE_NOTICES = Path(__file__).with_name("NOTICES-native.txt")
SEP = "\n\n" + "=" * 78 + "\n"
HEADER = """Third-party software in Last Epoch Item Filter editor/generator.

Not included, but downloaded on your computer the first time the program reads a game build
(each pinned to a version and checksum):
- Cpp2IL by Samboy063 (https://github.com/SamboyCoding/Cpp2IL), MIT license.
- TypeTreeGeneratorAPI by K0lb3 (https://github.com/K0lb3/TypeTreeGeneratorAPI), from PyPI; its
  native library carries its own licenses.

Included:"""


def _name(requirement: str) -> str:
    return re.split(r"[\s;<>=!~\[(]", requirement, maxsplit=1)[0]


def _key(name: str) -> str:
    return name.lower().replace("_", "-")


def closure(roots: list[str]) -> list[metadata.Distribution]:
    """The root distributions and everything they require (for this platform)."""
    seen: dict[str, metadata.Distribution] = {}
    todo = list(roots)
    while todo:
        name = todo.pop()
        key = _key(name)
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


def read_manifest(path: str | None) -> list[tuple[str, str]]:
    if not path or not Path(path).is_file():
        return []
    rows = [line.split("\t", 1) for line in Path(path).read_text(encoding="utf-8").splitlines() if "\t" in line]
    return [(dest, src) for dest, src in rows]


def _dpkg_package(src: str) -> str | None:
    candidates = {src, os.path.realpath(src)}
    for p in list(candidates):   # merged /usr: dpkg may know either spelling
        if p.startswith("/usr/lib/"):
            candidates.add(p.removeprefix("/usr"))
        elif p.startswith("/lib/"):
            candidates.add("/usr" + p)
    for p in candidates:
        r = subprocess.run(["dpkg", "-S", p], capture_output=True, text=True)
        if r.returncode == 0 and ":" in r.stdout:
            return r.stdout.split(":", 1)[0].strip()
    return None


def system_library_notices(manifest: list[tuple[str, str]]) -> list[str]:
    """Copyright files of bundled system libraries (Debian / Ubuntu build machines)."""
    if not shutil.which("dpkg"):
        return []
    parts, seen = [], set()
    for _, src in manifest:
        if not src.startswith(("/lib/", "/usr/lib/", "/lib64/")) or "python3" in src:
            continue
        pkg = _dpkg_package(src)
        if not pkg or pkg in seen:
            continue
        seen.add(pkg)
        copyright = Path("/usr/share/doc") / pkg.split(":")[0] / "copyright"
        if copyright.is_file():
            parts.append(f"{Path(src).name} (system library, Debian/Ubuntu package {pkg})\n\n"
                         + copyright.read_text(encoding="utf-8", errors="replace").strip())
    return parts


def main(out: str, manifest_path: str | None = None) -> None:
    manifest = read_manifest(manifest_path)
    bad = [dest for dest, _ in manifest if any(f in dest.lower() for f in FORBIDDEN)]
    if bad:
        sys.exit(f"must not be redistributed, but bundled: {bad}")
    parts = [HEADER]
    py = python_license()
    if py:
        parts.append(f"Python {sys.version.split()[0]}\n\n{py}")
    packages = closure(ROOTS)
    for dist in packages:
        meta = dist.metadata
        head = f"{meta['Name']} {dist.version}" + (f" - {meta['Home-page']}" if meta.get("Home-page") else "")
        parts.append(head + "\n\n" + "\n\n".join(license_texts(dist)))
    if NATIVE_NOTICES.is_file():
        parts.append(NATIVE_NOTICES.read_text(encoding="utf-8").strip())
    system = system_library_notices(manifest)
    parts += system
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(SEP.join(parts) + "\n", encoding="utf-8")
    print(f"{out}: Python + {len(packages)} packages + native notices + {len(system)} system libraries")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "THIRD_PARTY_LICENSES.txt", sys.argv[2] if len(sys.argv) > 2 else None)
