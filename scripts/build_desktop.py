#!/usr/bin/env python3
"""Build Lumina Studio desktop installer (Electron + PyInstaller).

Usage:
    python scripts/build_desktop.py

Steps:
    1. Build frontend (VITE_API_BASE_URL=http://127.0.0.1:8000/api)
    2. Build backend native extensions
    3. Build backend (PyInstaller -> lumina-backend.exe)
    4. Copy artifacts to electron/resources/
    5. Build Electron installer (electron-builder -> NSIS Setup.exe)
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
FRONTEND_DIR = ROOT / "frontend"
ELECTRON_DIR = ROOT / "electron"
RESOURCES_DIR = ELECTRON_DIR / "resources"
BACKEND_RES_DIR = RESOURCES_DIR / "backend"
APP_DIST_RES_DIR = RESOURCES_DIR / "app" / "dist"
MATERIALS_RES_DIR = RESOURCES_DIR / "materials"
PYINSTALLER_DIST = ROOT / "dist"


def run(cmd, cwd=None, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    print(f"  > {cmd}")
    subprocess.check_call(cmd, shell=True, cwd=cwd, env=env)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build Lumina Studio desktop installer.",
    )
    parser.add_argument(
        "--materials-seed-path",
        default=os.environ.get("MATERIALS_SEED_PATH", ""),
        help="Optional lumina-materials-seed.zip artifact to bundle.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("=" * 60)
    print("  Lumina Studio — Desktop Build")
    print("=" * 60)

    BACKEND_RES_DIR.mkdir(parents=True, exist_ok=True)
    APP_DIST_RES_DIR.mkdir(parents=True, exist_ok=True)
    MATERIALS_RES_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Build frontend ──
    print("\n[1/4] Building frontend...")
    run(
        "pnpm run build",
        cwd=str(FRONTEND_DIR),
        env_extra={"VITE_API_BASE_URL": "http://127.0.0.1:8000/api"},
    )

    # ── Step 2: Build backend ──
    print("\n[2/5] Building backend native extensions...")
    run(f"{sys.executable} scripts/build_native_extensions.py", cwd=str(ROOT))

    print("\n[3/5] Building backend (PyInstaller)...")
    run("pyinstaller lumina_studio.spec", cwd=str(ROOT))

    # ── Step 3: Copy artifacts ──
    print("\n[4/5] Copying artifacts to electron/resources/...")

    backend_exe = PYINSTALLER_DIST / "lumina-backend.exe"
    if not backend_exe.exists():
        print(f"ERROR: Backend exe not found at {backend_exe}")
        sys.exit(1)
    shutil.copy2(backend_exe, BACKEND_RES_DIR / "lumina-backend.exe")
    print(f"  Copied: {backend_exe} -> {BACKEND_RES_DIR / 'lumina-backend.exe'}")

    frontend_dist = FRONTEND_DIR / "dist"
    if not frontend_dist.exists():
        print(f"ERROR: Frontend dist not found at {frontend_dist}")
        sys.exit(1)
    if APP_DIST_RES_DIR.exists():
        shutil.rmtree(APP_DIST_RES_DIR)
    shutil.copytree(frontend_dist, APP_DIST_RES_DIR)
    print(f"  Copied: {frontend_dist} -> {APP_DIST_RES_DIR}")

    seed_path = Path(args.materials_seed_path).expanduser() if args.materials_seed_path else None
    target_seed_path = MATERIALS_RES_DIR / "lumina-materials-seed.zip"
    if seed_path:
        if not seed_path.is_file():
            print(f"ERROR: Materials seed not found at {seed_path}")
            sys.exit(1)
        shutil.copy2(seed_path, target_seed_path)
        print(f"  Copied: {seed_path} -> {target_seed_path}")
    elif target_seed_path.exists():
        target_seed_path.unlink()
        print(f"  Removed stale seed: {target_seed_path}")

    # ── Step 4: Build Electron installer ──
    print("\n[5/5] Building Electron installer (electron-builder)...")
    if not (ELECTRON_DIR / "node_modules").exists():
        print("  Installing Electron dependencies...")
        run("pnpm install", cwd=str(ELECTRON_DIR))
    run("pnpm run build", cwd=str(ELECTRON_DIR))

    print("\n" + "=" * 60)
    print("  Build complete!")
    output_dir = ELECTRON_DIR / "dist_electron"
    if output_dir.exists():
        installers = list(output_dir.glob("*.exe"))
        if installers:
            print(f"  Installer: {installers[0]}")
    print("=" * 60)


if __name__ == "__main__":
    main()
