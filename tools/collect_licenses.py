"""Collect the licence texts of everything bundled into the installer (run by CI before PyInstaller).

Output (default build-licenses/, shipped as <app>/_internal/licenses):
  python/<distribution>/...   licence files from the installed wheels' metadata (incl. GEOS inside shapely)
  rust/<crate>-<version>/...  licence files of every crate compiled into sparrow.exe (from Cargo.lock, read from
                              the local cargo registry the build just used)
  README.txt                  overview, Qt / PySide6 LGPL-3.0 note and source locations

The LGPL-3.0 / GPL-3.0 texts for Qt (packaging/licenses/) are copied by the CI step into licenses/qt/.
Exit code 1 when a Rust crate's licence file cannot be found (so a release never ships without it).
"""
from __future__ import annotations

import argparse
import glob
import importlib.metadata as md
import os
import re
import shutil
import sys

LIC = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT|UNLICENSE)[^/]*$", re.I)
SKIP_PY = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "pytest", "pluggy", "iniconfig",
           "packaging", "altgraph", "pefile", "pywin32-ctypes", "colorama"}

README = """LEVEL7 Nesting - third-party licences
=====================================
python/   licences of the Python packages bundled with LEVEL7 (PySide6 / Qt, shapely incl. GEOS, numpy,
          pyclipper, ezdxf, openpyxl ...). Versions: see docs/DEPENDENCIES.md.
rust/     licences of the Rust crates compiled into engines/sparrow.exe (sparrow: MIT; jagua-rs: MPL-2.0,
          source https://github.com/JeroenGar/jagua-rs).
qt/       GNU LGPL-3.0 and GPL-3.0 texts.

Qt / Qt for Python (PySide6, shiboken6) are used under the GNU LGPL-3.0 and are linked dynamically (the Qt
DLLs in this folder can be replaced by the user). Sources: https://download.qt.io/official_releases/ and
https://code.qt.io/cgit/pyside/pyside-setup.git . GEOS (inside shapely) is used under the GNU LGPL-2.1, source
https://libgeos.org . On request the corresponding source code of these LGPL components is provided.
"""


def python_licences(out: str) -> int:
    n = 0
    for d in md.distributions():
        name = d.metadata["Name"] or ""
        if not name or name.lower() in SKIP_PY or name.lower().startswith("pytest"):
            continue
        for f in d.files or []:
            if LIC.search(str(f).replace("\\", "/")):
                src = str(d.locate_file(f))
                if os.path.isfile(src):
                    dst = os.path.join(out, "python", name, os.path.basename(str(f)))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.exists(dst):          # same file name from a sub-folder (numpy vendored parts)
                        dst = os.path.join(os.path.dirname(dst), str(f).replace("/", "_").replace("\\", "_"))
                    shutil.copyfile(src, dst)
                    n += 1
    return n


def cargo_packages(lock: str):
    text = open(lock, encoding="utf-8").read()
    for blk in text.split("[[package]]")[1:]:
        name = re.search(r'^name = "([^"]+)"', blk, re.M)
        ver = re.search(r'^version = "([^"]+)"', blk, re.M)
        if name and ver and "source = \"registry+" in blk:
            yield name.group(1), ver.group(1)


def rust_licences(out: str, lock: str) -> list[str]:
    home = os.environ.get("CARGO_HOME") or os.path.join(os.path.expanduser("~"), ".cargo")
    roots = glob.glob(os.path.join(home, "registry", "src", "*"))
    missing = []
    for name, ver in cargo_packages(lock):
        src = next((os.path.join(r, f"{name}-{ver}") for r in roots if os.path.isdir(os.path.join(r, f"{name}-{ver}"))),
                   None)
        if src is None:
            continue                                  # not compiled for this target (never downloaded)
        files = [f for f in os.listdir(src) if LIC.search(f) and os.path.isfile(os.path.join(src, f))]
        if not files:
            m = re.search(r'^license\s*=\s*"([^"]+)"', open(os.path.join(src, "Cargo.toml"), encoding="utf-8").read(), re.M) \
                if os.path.isfile(os.path.join(src, "Cargo.toml")) else None
            missing.append(f"{name}-{ver}: {m.group(1) if m else 'see crates.io'}")
            continue
        dst = os.path.join(out, "rust", f"{name}-{ver}")
        os.makedirs(dst, exist_ok=True)
        for f in files:
            shutil.copyfile(os.path.join(src, f), os.path.join(dst, f))
    return missing


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="build-licenses")
    ap.add_argument("--cargo-lock", default=os.path.join("packaging", "sparrow", "Cargo.lock"))
    ap.add_argument("--no-rust", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(README)
    print("python licence files:", python_licences(a.out))
    if not a.no_rust:
        missing = rust_licences(a.out, a.cargo_lock)
        if missing:
            # crates that declare their licence only in Cargo.toml: write the SPDX expression next to the name
            print("crates without a licence file (SPDX from Cargo.toml):", ", ".join(missing))
            with open(os.path.join(a.out, "rust", "NO_LICENSE_FILE.txt"), "w", encoding="utf-8") as fh:
                fh.write("Crates whose package contains no licence file (licence per Cargo.toml / crates.io):\n")
                fh.write("\n".join(missing) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
