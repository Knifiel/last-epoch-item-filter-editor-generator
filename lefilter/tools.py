"""Tools fetched on the user's computer the first time they're needed - never shipped with this
program: Cpp2IL (recovers the game's class layouts from its code) and TypeTreeGeneratorAPI
(turns them into Unity type trees; its native library contains code that may not be
redistributed). Both are pinned by version and SHA-256 and kept in .cache/tools/.

A source checkout uses the TypeTreeGeneratorAPI installed with pip (requirements.txt) instead.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import ssl
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

CPP2IL_VERSION = "2022.1.0-pre-release.21"
CPP2IL_URL = "https://github.com/SamboyCoding/Cpp2IL/releases/download/{version}/{asset}"
CPP2IL_ASSETS = {   # platform.system() -> (release asset, SHA-256 as GitHub lists it)
    "Windows": (f"Cpp2IL-{CPP2IL_VERSION}-Windows.exe", "663fb432433b4371fd1ee0ebc321a8fff2a9aac5ac4230c843f9e03ddee4e04c"),
    "Linux": (f"Cpp2IL-{CPP2IL_VERSION}-Linux", "526998e593c52c029c5a6215c5c6c9f9d963706bfc409fc9ff80a95c4c500349"),
    "Darwin": (f"Cpp2IL-{CPP2IL_VERSION}-OSX", "15faab020698512807f792aef32a89fe529d41d2cc03955dd3516f0519fe8f72"),
}

TTG_VERSION = "0.0.10"
_PYPI = "https://files.pythonhosted.org/packages/"
TTG_WHEELS = {   # (platform.system(), machine) -> (PyPI wheel URL, SHA-256)
    ("Windows", "amd64"): (_PYPI + "ed/bc/f911995cae93fa8fd882a677f6bc304965db6f066bbabdee6e761762d512/"
                           "typetreegeneratorapi-0.0.10-cp36-abi3-win_amd64.whl",
                           "e96003e973c8d52d221b4ae50f377bcaf7538f2098e437d5383a1b7f13fa72ba"),
    ("Linux", "x86_64"): (_PYPI + "79/f0/cabdd091063c844ffdaf1f5b7a8efce7835556ce81affab5329cdf49b87a/"
                          "typetreegeneratorapi-0.0.10-cp36-abi3-manylinux2014_x86_64.whl",
                          "c61b3986d49ccd69d62e5147795d1e82c1f6582cfdd3df169f95dd00cd605219"),
    ("Linux", "aarch64"): (_PYPI + "a0/6c/d0d976267909f1e0cd271c7d025c78c3dc6d2a5597f422f67db898689c1e/"
                           "typetreegeneratorapi-0.0.10-cp36-abi3-manylinux2014_aarch64.whl",
                           "90b2e132aa2b8698a5ea2698227fb91932bf5c334f89e7fa2394ed401d510aea"),
    ("Darwin", "arm64"): (_PYPI + "a4/ae/a881d33c296276dd9bf9c0bb8d89acec6301831291fcec5bb12587bc715c/"
                          "typetreegeneratorapi-0.0.10-cp36-abi3-macosx_11_0_arm64.whl",
                          "8ba72e60ba512707fe63873d3bb55f8e86d99c0b45d4b5205bd4ca43465cf331"),
    ("Darwin", "x86_64"): (_PYPI + "20/07/9ba8ba47c623f6533206c3c15526e91413bef661e457642b727921841b73/"
                           "typetreegeneratorapi-0.0.10-cp36-abi3-macosx_11_0_x86_64.whl",
                           "037c8ddddaa39134c7a5ea8c004749d7df6a28a9cdeb89a6ae12c73eeef40ee0"),
}

# Where Linux distributions keep their CA certificates. The packaged Linux app carries the build
# machine's OpenSSL, which looks in Ubuntu's place only (SteamOS / Arch / Fedora differ).
CA_FILES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem",
            "/etc/ssl/ca-bundle.pem", "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem")


class ToolError(Exception):
    pass


def _platform_key() -> tuple[str, str]:
    return platform.system(), platform.machine().lower()


def ssl_context() -> ssl.SSLContext:
    if os.name == "nt" or os.environ.get("SSL_CERT_FILE"):
        return ssl.create_default_context()
    paths = ssl.get_default_verify_paths()
    if (paths.cafile and os.path.isfile(paths.cafile)) or (paths.capath and os.path.isdir(paths.capath)
                                                           and any(Path(paths.capath).iterdir())):
        return ssl.create_default_context()
    for f in CA_FILES:
        if os.path.isfile(f):
            return ssl.create_default_context(cafile=f)
    return ssl.create_default_context()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str, what: str) -> Path:
    """dest, downloaded unless a file with the expected checksum is already there. Written to a
    .part file first, so an interrupted download is never mistaken for a finished one."""
    if dest.is_file() and _sha256(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    print(f"Downloading {what} ({url}) ...")
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, context=ssl_context(), timeout=60) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                h.update(chunk)
    except OSError as e:   # URLError, timeouts, disk errors
        tmp.unlink(missing_ok=True)
        raise ToolError(f"couldn't download {what} from {url}: {e}\nCheck the internet connection (and whether "
                        f"a firewall blocks GitHub / PyPI), then start the program again.") from e
    if h.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise ToolError(f"the downloaded {what} doesn't match its known checksum; start the program again "
                        f"(if this keeps happening, something on this computer or network alters downloads)")
    tmp.replace(dest)
    return dest


def ensure_cpp2il(tools_dir: Path) -> Path:
    asset = CPP2IL_ASSETS.get(platform.system())
    if not asset:
        raise ToolError(f"no Cpp2IL build for {platform.system()}")
    name, sha256 = asset
    exe = download(CPP2IL_URL.format(version=CPP2IL_VERSION, asset=name), tools_dir / name, sha256, "Cpp2IL")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def type_tree_generator(tools_dir: Path):
    """TypeTreeGeneratorAPI's TypeTreeGenerator: the pip-installed one, else the pinned wheel,
    downloaded and unpacked into tools_dir."""
    try:
        from TypeTreeGeneratorAPI import TypeTreeGenerator
        return TypeTreeGenerator
    except ImportError:
        pass
    key = _platform_key()
    if key not in TTG_WHEELS:
        raise ToolError(f"no TypeTreeGeneratorAPI build for {key[0]} {key[1]}")
    url, sha256 = TTG_WHEELS[key]
    target = tools_dir / f"TypeTreeGeneratorAPI-{TTG_VERSION}-{key[0]}-{key[1]}"
    if not (target / "TypeTreeGeneratorAPI" / "__init__.py").is_file():
        wheel = download(url, tools_dir / url.rsplit("/", 1)[1], sha256, "TypeTreeGeneratorAPI")
        tmp = target.with_name(target.name + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(wheel) as z:
            z.extractall(tmp)
        shutil.rmtree(target, ignore_errors=True)
        tmp.replace(target)
        wheel.unlink(missing_ok=True)
    sys.path.insert(0, str(target))
    try:
        from TypeTreeGeneratorAPI import TypeTreeGenerator
    except Exception as e:
        raise ToolError(f"TypeTreeGeneratorAPI ({target}) didn't load: {e}") from e
    return TypeTreeGenerator
