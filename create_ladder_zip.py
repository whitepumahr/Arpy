#!/usr/bin/env python3
"""Create a ladder-ready zip for Arpy bot.

Works regardless of where the script is located — it auto-detects the
project root by looking for `run.py` in parent directories.

Automatically patches ares/main.py to ensure cython_extensions and
map_analyzer can be found on the ladder (where the zip extracts to /bot/).

Required directories in the project root:
  - bot/           Your bot code
  - ares-sc2/      Ares framework (src/ and sc2_helper/)
  - cython_extensions/  Compiled C extensions (from QueenBot or PyPI)
  - map_analyzer/  Map analysis library (from QueenBot)
  - sc2/           python-sc2 library (from QueenBot)

Usage:
    python create_ladder_zip.py
    python scripts/create_ladder_zip.py
"""
import shutil
import sys
from pathlib import Path


def find_project_root() -> Path:
    """Walk up from the script's location to find the directory containing run.py."""
    candidate = Path(__file__).resolve().parent
    for _ in range(5):
        if (candidate / "run.py").exists():
            return candidate
        candidate = candidate.parent
    print("ERROR: Could not find project root (directory containing run.py)")
    sys.exit(1)


def patch_ares_main_py(filepath: Path) -> None:
    """Patch ares/main.py to add sys.path fix BEFORE 'from cython_extensions import'.

    This is the most direct fix: patch the exact file that fails. On the ladder,
    the zip extracts to /bot/, so we need /bot/ on sys.path before ares tries
    to import cython_extensions or map_analyzer.  Idempotent — won't duplicate.
    """
    text = filepath.read_text(encoding="utf-8")

    # Already patched?
    if "_cython_ext_path_fix_done" in text:
        print(f"  [OK] ares/main.py already has cython_extensions path patch")
        return

    # Insert the path fix right before 'from cython_extensions import'
    # This also fixes map_analyzer since it's at the same level
    patch_code = """\
# === LADDER FIX: ensure bundled packages can be found ===
# On the SC2 ladder, the bot zip extracts to /bot/.  The directory containing
# cython_extensions/ and map_analyzer/ must be on sys.path for these imports
# to work.  This fix is injected by create_ladder_zip.py.
# ares/main.py is at /bot/ares-sc2/src/ares/main.py, so we need 4 dirname()
# calls to get to /bot/: main.py -> ares/ -> src/ -> ares-sc2/ -> /bot/
_cython_ext_path_fix_done = True
import os as _os_for_ce, sys as _sys_for_ce
_ce_p = _os_for_ce.path.abspath(__file__)
for _ in range(4):
    _ce_p = _os_for_ce.path.dirname(_ce_p)
if _ce_p not in _sys_for_ce.path:
    _sys_for_ce.path.insert(0, _ce_p)

"""

    # Find 'from cython_extensions import' and insert before it
    lines = text.split("\n")
    insert_idx = 0
    for i, line in enumerate(lines):
        if "from cython_extensions import" in line:
            insert_idx = i
            break
        insert_idx = i + 1

    lines.insert(insert_idx, patch_code.rstrip())
    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [PATCHED] ares/main.py — added bundled packages path fix at line {insert_idx + 1}")


def create_ladder_zip():
    project_root = find_project_root()
    dist_dir = project_root / "dist"
    dist_dir.mkdir(exist_ok=True)

    bot_name = "Arpy"

    # Create a temporary directory for the zip contents
    temp_dir = dist_dir / bot_name
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    # ---- Validate required directories exist ----
    required_dirs = {
        "bot": project_root / "bot",
        "ares-sc2/src": project_root / "ares-sc2" / "src",
        "cython_extensions": project_root / "cython_extensions",
        "map_analyzer": project_root / "map_analyzer",
        "sc2": project_root / "sc2",
    }
    missing = []
    for name, dirpath in required_dirs.items():
        if not dirpath.exists():
            print(f"  [MISSING] {name} ({dirpath})")
            missing.append(name)
        else:
            print(f"  [OK] Found: {name}")

    if missing:
        print(f"\n  [ERROR] Missing required directories: {', '.join(missing)}")
        print(f"  Cannot create ladder zip!")
        print(f"\n  To get missing packages, extract them from QueenBot's zip:")
        print(f"    Expand-Archive -Path queenbot.zip -DestinationPath temp_qb")
        print(f"    Copy-Item -Recurse temp_qb\\<package> .")
        print(f"    Remove-Item -Recurse temp_qb")
        sys.exit(1)

    # ---- Copy bot code ----
    bot_dir = temp_dir / "bot"
    shutil.copytree(project_root / "bot", bot_dir)

    # ---- Copy ares-sc2 src ----
    ares_src = temp_dir / "ares-sc2" / "src"
    shutil.copytree(project_root / "ares-sc2" / "src", ares_src)

    # ---- Copy sc2_helper compiled modules ----
    sc2_helper_src = project_root / "ares-sc2" / "sc2_helper"
    if sc2_helper_src.exists():
        sc2_helper_dst = temp_dir / "ares-sc2" / "sc2_helper"
        shutil.copytree(sc2_helper_src, sc2_helper_dst)
        print(f"  [OK] Copied: sc2_helper")
    else:
        print(f"  [WARN] Missing: sc2_helper (combat simulator won't work)")

    # ---- Copy cython_extensions (REQUIRED for ares) ----
    cython_ext_src = project_root / "cython_extensions"
    cython_ext_dst = temp_dir / "cython_extensions"
    shutil.copytree(cython_ext_src, cython_ext_dst)
    ce_init = cython_ext_dst / "__init__.py"
    ce_bootstrap_files = list(cython_ext_dst.glob("bootstrap*.so"))
    print(f"  [OK] Copied: cython_extensions")
    print(f"       __init__.py exists: {ce_init.exists()}")
    print(f"       bootstrap.so files: {[f.name for f in ce_bootstrap_files]}")

    # ---- Copy map_analyzer (REQUIRED by ares managers) ----
    shutil.copytree(project_root / "map_analyzer", temp_dir / "map_analyzer")
    print(f"  [OK] Copied: map_analyzer")

    # ---- Copy sc2 / python-sc2 (REQUIRED by ares) ----
    shutil.copytree(project_root / "sc2", temp_dir / "sc2")
    print(f"  [OK] Copied: sc2")

    # ---- Copy ladder files ----
    shutil.copy2(project_root / "ladder.py", temp_dir / "ladder.py")
    shutil.copy2(project_root / "run.py", temp_dir / "run.py")

    # ---- Copy config ----
    if (project_root / "config.yml").exists():
        shutil.copy2(project_root / "config.yml", temp_dir / "config.yml")
    if (project_root / "protoss_builds.yml").exists():
        shutil.copy2(project_root / "protoss_builds.yml", temp_dir / "protoss_builds.yml")

    # ---- PATCH: ensure bundled packages can be found by ares ----
    print("\nPatching ares/main.py for ladder compatibility...")
    ares_main_py = temp_dir / "ares-sc2" / "src" / "ares" / "main.py"
    if ares_main_py.exists():
        patch_ares_main_py(ares_main_py)
    else:
        print(f"  [ERROR] ares/main.py not found at {ares_main_py}!")
        sys.exit(1)

    # ---- Create zip ----
    # Use temp_dir as root_dir so files are at the zip root (not wrapped in
    # a subfolder). The ladder requires run.py at the root of the zip.
    zip_path = dist_dir / f"{bot_name}.zip"
    if zip_path.exists():
        zip_path.unlink()

    shutil.make_archive(str(dist_dir / bot_name), "zip", str(temp_dir))

    # Clean up temp dir
    shutil.rmtree(temp_dir)

    print(f"\nProject root: {project_root}")
    print(f"Ladder zip created: {zip_path}")
    print(f"Size: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")

    # ---- Verification ----
    print("\n=== Zip verification ===")
    import zipfile
    with zipfile.ZipFile(zip_path, 'r') as z:
        names = z.namelist()
        root_files = [n for n in names if '/' not in n]
        print(f"Files at zip root: {root_files}")
        print(f"run.py at root: {'run.py' in root_files}")

        # Check all required top-level packages
        for pkg in ['cython_extensions', 'map_analyzer', 'sc2', 'ares-sc2', 'bot']:
            pkg_files = [n for n in names if n.startswith(f'{pkg}/') and not n.endswith('/')]
            print(f"{pkg} files: {len(pkg_files)}")

        # Verify ares/main.py has the patch
        ares_main_content = z.read('ares-sc2/src/ares/main.py').decode('utf-8')
        has_patch = '_cython_ext_path_fix_done' in ares_main_content
        print(f"ares/main.py has path patch: {has_patch}")


if __name__ == "__main__":
    create_ladder_zip()