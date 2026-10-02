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
for package in ("UnityPy", "texture2ddecoder", "etcpak", "astc_encoder", "archspec", "TypeTreeGeneratorAPI", "brotli", "lz4",
                "fsspec"):
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
    hiddenimports=hiddenimports + ["lefilter.ui"],
    # FMOD (UnityPy's audio export, never used here; lefilter.extract stubs it) is proprietary: not bundled.
    excludes=["pytest", "tkinter", "pyfmodex", "fmod_toolkit"],
)
a.datas = [d for d in a.datas if "libfmod" not in d[0]]
a.binaries = [b for b in a.binaries if "libfmod" not in b[0] and "fmod" not in Path(b[0]).name.lower()]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="LastEpochItemFilterEditor",
    console=True,          # status and errors show in the console window; closing it stops the editor
    upx=False,
)
