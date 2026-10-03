# PyInstaller spec: one-file executable of the editor (python -m PyInstaller packaging/lefilter.spec).
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
# Program files only: game data, schemas and the new-filter template are made from the user's install.
datas = [
    (str(root / "lefilter" / "web"), "lefilter/web"),
    (str(root / "config.toml"), "."),
    (str(root / "LICENSE"), "."),
]
binaries, hiddenimports = [], []
for package in ("UnityPy", "texture2ddecoder", "etcpak", "astc_encoder", "archspec", "brotli", "lz4", "fsspec"):
    try:
        d, b, h = collect_all(package)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    # ctypes / zipfile: TypeTreeGeneratorAPI, fetched at first use (lefilter/tools.py), needs them.
    hiddenimports=hiddenimports + ["lefilter.ui", "ctypes", "ctypes.util", "zipfile"],
    # Not redistributable with this program: FMOD (UnityPy's audio export, never used; lefilter.extract
    # stubs it), TypeTreeGeneratorAPI (fetched on the user's computer instead), GNU readline (GPL,
    # pulled in through setuptools -> site).
    excludes=["pytest", "tkinter", "pyfmodex", "fmod_toolkit", "TypeTreeGeneratorAPI", "readline", "rlcompleter",
              "setuptools", "_distutils_hack", "pkg_resources"],
)
a.datas = [d for d in a.datas if "libfmod" not in d[0]]
a.binaries = [b for b in a.binaries if "libfmod" not in b[0] and "fmod" not in Path(b[0]).name.lower()]
# What went in, for packaging/collect_licenses.py (system libraries need their notices).
Path(workpath).mkdir(parents=True, exist_ok=True)
(Path(workpath) / "bundled-binaries.txt").write_text("".join(f"{dest}\t{src}\n" for dest, src, _ in a.binaries),
                                                     encoding="utf-8")
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="LEIFEG",         # Last Epoch Item Filter Editor / Generator
    console=True,          # status and errors show in the console window; closing it stops the editor
    upx=False,
)
