#!/usr/bin/env python3
"""Build Lumina Studio desktop installer (Electron + PyInstaller).

Usage:
    python scripts/build_desktop.py

Steps:
    1. Build frontend (VITE_API_BASE_URL=/api, same-origin desktop backend)
    2. Check geometry dependencies
    3. Build backend (PyInstaller -> lumina-backend.exe)
    4. Copy artifacts to electron/resources/
    5. Build Electron installer (electron-builder -> NSIS Setup.exe)
"""

import argparse
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.workshop import (  # noqa: E402
    WorkshopSeedLock,
    verify_workshop_seed as verify_seed_contract,
)
from scripts.fatcat_packaging_contract import (  # noqa: E402
    FATCAT_ADAPTER_MODULE,
    FATCAT_MODULE,
    FATCAT_WRITER_VERSION,
    validate_fatcat_packaging_contract,
)

FRONTEND_DIR = ROOT / "frontend"
ELECTRON_DIR = ROOT / "electron"
RESOURCES_DIR = ELECTRON_DIR / "resources"
BACKEND_RES_DIR = RESOURCES_DIR / "backend"
APP_DIST_RES_DIR = RESOURCES_DIR / "app" / "dist"
MATERIALS_RES_DIR = RESOURCES_DIR / "materials"
WORKSHOP_SEED_RES_DIR = RESOURCES_DIR / "workshop-seed"
WORKSHOP_SEED_LOCK = (
    ROOT / "assets" / "workshop-seed" / "seed-lock.json"
)
PYINSTALLER_DIST = ROOT / "dist"
CORE_GEOMETRY_REQUIRED_MODULES = (
    "manifold3d", "lumina_svg_core", "lumina_svg_core._lumina_svg_compensation",
)
GLB_V2_OPTIONAL_MODULES = ("rasterio.features",)
WORKSHOP_DESKTOP_SECURITY_FILES = (
    ELECTRON_DIR / "backend-endpoint.cjs",
    ELECTRON_DIR / "generated-file-save.cjs",
    ELECTRON_DIR / "generated-file-directory.cjs",
    ELECTRON_DIR / "storage-migration.cjs",
    ELECTRON_DIR / "storage-migration-preload.cjs",
    ELECTRON_DIR / "bed-model-bridge.cjs",
    ELECTRON_DIR / "workshop-security.cjs",
    ELECTRON_DIR / "preload.cjs",
)


def run(cmd, cwd=None, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    print(f"  > {cmd}")
    subprocess.check_call(cmd, shell=True, cwd=cwd, env=env)


def check_core_geometry_dependencies_available() -> None:
    """Fail packaging when slicer-safe vector triangulation is unavailable."""

    missing = []
    for module_name in CORE_GEOMETRY_REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            missing.append((module_name, exc))

    if not missing:
        native = importlib.import_module("lumina_svg_core")
        if not callable(getattr(native, "project_regions_to_grid", None)):
            missing.append(("lumina_svg_core.project_regions_to_grid", RuntimeError(
                "Rebuild requirements-native-svg.txt from this checkout; the installed native library is stale."
            )))
        elif not callable(getattr(native, "canonicalize_grid_regions", None)):
            missing.append(("lumina_svg_core.canonicalize_grid_regions", RuntimeError(
                "Rebuild requirements-native-svg.txt from this checkout; the installed native library is stale."
            )))

    if not missing:
        print("  Core geometry dependencies available for packaging.")
        return

    details = "; ".join(
        f"{module_name}: {exc}"
        for module_name, exc in missing
    )
    raise RuntimeError(
        "Core geometry dependencies are missing; refusing a desktop build "
        f"that could export slicer-unsafe vector meshes. {details}"
    )


def check_glb_v2_dependencies_available() -> bool:
    """Warn when desktop builds cannot bundle the optional raster GLB v2 path."""

    missing = []
    for module_name in GLB_V2_OPTIONAL_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            missing.append((module_name, exc))

    if not missing:
        print("  GLB v2 preview dependencies available for packaging.")
        return True

    print(
        "WARNING: GLB v2 preview dependencies are missing; packaged preview "
        "generation will fall back to v1 unless these modules are installed.",
    )
    print("  Install optional preview acceleration with: pip install -r requirements-glb-v2.txt")
    for module_name, exc in missing:
        print(f"  - {module_name}: {exc}")
    return False


def check_3mf_native_dependencies_available() -> None:
    """Require the exact Fat Cat binding and patched writer for desktop builds.

    桌面打包必须使用精确的 Fat Cat C++ 绑定和下游 writer；缺失时直接失败，
    不把 B4 目标静默降级到库存 writer。
    """

    try:
        fatcat = importlib.import_module(FATCAT_MODULE)
        importlib.import_module(FATCAT_ADAPTER_MODULE)
        n3mf = importlib.import_module("neroued_3mf")
    except Exception as exc:
        raise RuntimeError(
            "B4 desktop packaging requires the installed Fat Cat C++ wheel and "
            f"patched neroued writer: {exc}"
        ) from exc

    data_root = validate_fatcat_packaging_contract(fatcat, n3mf)
    builder = n3mf.DocumentBuilder()
    missing_writer_methods = [
        name
        for name in (
            "plan_production_layout",
            "set_production_build_uuid",
            "set_production_assembly_uuid",
            "set_component_uuid",
        )
        if not hasattr(builder, name)
    ]
    if missing_writer_methods:
        raise RuntimeError(
            "patched neroued writer is missing B4 production APIs: "
            f"{missing_writer_methods}"
        )
    print(
        "  3MF native dependencies available: "
        f"Fat Cat data at {data_root}, neroued {FATCAT_WRITER_VERSION}."
    )


def check_workshop_desktop_security_files() -> None:
    """Fail packaging if the Workshop desktop trust boundary is incomplete."""

    missing = [
        path.relative_to(ROOT)
        for path in WORKSHOP_DESKTOP_SECURITY_FILES
        if not path.is_file()
    ]
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"Workshop desktop security files are missing: {rendered}"
        )


def verify_workshop_seed(
    seed_path: Path,
    lock_path: Path,
) -> WorkshopSeedLock:
    """Verify one seed archive against the committed immutable lock.

    对照已提交的不可变锁文件校验一个预装模块安装包。

    Args:
        seed_path: Exact `.lumina-workshop` package. 精确安装包。
        lock_path: Committed seed-lock JSON. 已提交锁文件。

    Returns:
        Validated seed-lock identity. 已验证的锁定身份。

    Raises:
        ValueError: If size, hash, package, or manifest identity differs.
            大小、摘要、安装包或清单身份不一致时抛出。
    """

    return verify_seed_contract(seed_path, lock_path).lock


def _clear_workshop_seed_resources(resource_dir: Path) -> None:
    if resource_dir.is_symlink():
        raise ValueError("Workshop seed resource directory cannot be a symlink")
    resource_dir.mkdir(parents=True, exist_ok=True)
    for path in resource_dir.iterdir():
        if path.name == ".gitignore":
            continue
        if (
            path.is_file()
            and (
                path.name == "seed-lock.json"
                or path.name.endswith(".lumina-workshop")
                or path.name.endswith(".lumina-workshop.sha256")
            )
        ):
            path.unlink()
            continue
        raise ValueError(
            f"unexpected Workshop seed resource: {path.name}"
        )


def prepare_workshop_seed_resource(
    *,
    seed_path: Path | None,
    lock_path: Path,
    resource_dir: Path,
    allow_missing: bool,
) -> WorkshopSeedLock | None:
    """Prepare only a verified seed and lock for Electron packaging.

    仅将已验证的预装模块和锁文件准备给 Electron 打包。

    Args:
        seed_path: Explicit build input, or `None`. 明确构建输入或空值。
        lock_path: Committed immutable lock. 已提交不可变锁。
        resource_dir: Generated Electron resource directory.
            Electron 生成资源目录。
        allow_missing: Explicit development-only omission.
            仅开发用途的显式省略开关。

    Returns:
        Verified lock, or `None` for an explicit development omission.
            已验证锁；显式开发省略时返回空值。

    Raises:
        ValueError: If release packaging lacks or fails seed verification.
            发布打包缺少预装模块或校验失败时抛出。
    """

    if seed_path is None:
        if not allow_missing:
            raise ValueError(
                "Workshop seed is required for desktop release builds"
            )
        _clear_workshop_seed_resources(resource_dir)
        return None
    lock = verify_workshop_seed(seed_path, lock_path)
    _clear_workshop_seed_resources(resource_dir)
    shutil.copy2(seed_path, resource_dir / lock.release_asset)
    shutil.copy2(lock_path, resource_dir / "seed-lock.json")
    return lock


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build Lumina Studio desktop installer.",
    )
    parser.add_argument(
        "--materials-seed-path",
        default=os.environ.get("MATERIALS_SEED_PATH", ""),
        help="Optional lumina-materials-seed.zip artifact to bundle.",
    )
    parser.add_argument(
        "--workshop-seed-path",
        default=os.environ.get("WORKSHOP_SEED_PATH", ""),
        help="Required official .lumina-workshop seed for release builds.",
    )
    parser.add_argument(
        "--allow-missing-workshop-seed",
        action="store_true",
        help="Development only: build without the official Workshop seed.",
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
    WORKSHOP_SEED_RES_DIR.mkdir(parents=True, exist_ok=True)

    workshop_seed_path = (
        Path(args.workshop_seed_path).expanduser()
        if args.workshop_seed_path
        else None
    )
    try:
        prepare_workshop_seed_resource(
            seed_path=workshop_seed_path,
            lock_path=WORKSHOP_SEED_LOCK,
            resource_dir=WORKSHOP_SEED_RES_DIR,
            allow_missing=args.allow_missing_workshop_seed,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    # ── Step 1: Build frontend ──
    print("\n[1/5] Building frontend...")
    run(
        "pnpm run build",
        cwd=str(FRONTEND_DIR),
        env_extra={"VITE_API_BASE_URL": "/api"},
    )

    # ── Step 2: Check backend dependencies ──
    print("\n[2/5] Checking desktop geometry dependencies...")
    try:
        check_3mf_native_dependencies_available()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1
    try:
        check_core_geometry_dependencies_available()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1
    check_glb_v2_dependencies_available()

    print("\n[3/5] Building backend (PyInstaller)...")
    run(
        "pyinstaller lumina_studio.spec",
        cwd=str(ROOT),
    )

    # ── Step 4: Copy artifacts ──
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

    # ── Step 5: Build Electron installer ──
    print("\n[5/5] Building Electron installer (electron-builder)...")
    check_workshop_desktop_security_files()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
