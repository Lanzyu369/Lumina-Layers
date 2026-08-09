#!/usr/bin/env python3
"""Build the scratch-only patched GEOS dense-buffer proof library."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROOF_ROOT = ROOT / ".scratch" / "geos_buffer_fast_proof"
SOURCE_ROOT = PROOF_ROOT / "geos"
BUILD_ROOT = PROOF_ROOT / "build"
MANIFEST_PATH = PROOF_ROOT / "build_manifest.json"
PATCH_MARKER_PATH = SOURCE_ROOT / ".lumina_patch_sha256"
PATCH_PATH = (
    ROOT
    / "native"
    / "geos_buffer_fast"
    / "patches"
    / "geos-3.13.1-buffer-subgraph-index.patch"
)
GEOS_REPOSITORY = "https://github.com/libgeos/geos.git"
GEOS_REF = "3.13.1"


def clone_command() -> list[str]:
    """Return the pinned shallow-clone command. / 返回固定版本浅克隆命令。"""

    return [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        GEOS_REF,
        GEOS_REPOSITORY,
        str(SOURCE_ROOT),
    ]


def apply_command() -> list[str]:
    """Return the patch command. / 返回补丁应用命令。"""

    return ["git", "-C", str(SOURCE_ROOT), "apply", str(PATCH_PATH)]


def configure_command() -> list[str]:
    """Return the release-only CMake configure command. / 返回 CMake 配置命令。"""

    return [
        "cmake",
        "-S",
        str(SOURCE_ROOT),
        "-B",
        str(BUILD_ROOT),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_TESTING=OFF",
        "-DBUILD_DOCUMENTATION=OFF",
        "-DBUILD_GEOSOP=OFF",
    ]


def build_command(*, parallel: int | None = None) -> list[str]:
    """Return the bounded parallel build command. / 返回有限并行构建命令。"""

    workers = min(10, max(1, int(parallel or os.cpu_count() or 1)))
    return [
        "cmake",
        "--build",
        str(BUILD_ROOT),
        "--config",
        "Release",
        "--parallel",
        str(workers),
    ]


def validate_rebuild_target(path: Path) -> Path:
    """Accept only the exact proof root as a destructive target.

    仅允许把精确的证明目录作为清理目标。

    Args:
        path: Requested directory to recreate.

    Returns:
        Resolved proof-root path.

    Raises:
        ValueError: If the target is broader than the proof root.
    """

    resolved = path.resolve()
    expected = PROOF_ROOT.resolve()
    if resolved != expected:
        raise ValueError(f"refusing rebuild target outside proof root: {resolved}")
    if resolved in {Path("/").resolve(), Path.home().resolve(), ROOT.resolve()}:
        raise ValueError(f"refusing broad rebuild target: {resolved}")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def resolve_built_library() -> Path:
    """Locate the proof GEOS C library. / 定位证明构建的 GEOS C 动态库。"""

    patterns = (
        "lib/libgeos_c*.dylib",
        "lib/libgeos_c*.so*",
        "lib/Release/geos_c*.dll",
        "bin/geos_c*.dll",
        "bin/Release/geos_c*.dll",
    )
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(path for path in BUILD_ROOT.glob(pattern) if path.is_file())
    if not matches:
        raise FileNotFoundError(f"patched GEOS C library not found under {BUILD_ROOT}")
    return sorted(matches, key=lambda path: (len(path.name), path.name))[0].resolve()


def build_proof(*, rebuild: bool = False) -> dict[str, object]:
    """Build patched GEOS into the ignored proof directory.

    在忽略跟踪的证明目录中构建打补丁的 GEOS。

    Args:
        rebuild: Remove only the exact proof root before building.

    Returns:
        Reproducible build-manifest fields.
    """

    if rebuild and PROOF_ROOT.exists():
        shutil.rmtree(validate_rebuild_target(PROOF_ROOT))
    PROOF_ROOT.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    if not SOURCE_ROOT.exists():
        _run(clone_command())

    if not PATCH_PATH.is_file():
        raise FileNotFoundError(f"GEOS proof patch is missing: {PATCH_PATH}")
    patch_sha256 = _sha256_file(PATCH_PATH)
    previous_patch = (
        PATCH_MARKER_PATH.read_text(encoding="utf-8").strip()
        if PATCH_MARKER_PATH.is_file()
        else None
    )
    if previous_patch is not None and previous_patch != patch_sha256:
        raise RuntimeError("proof patch changed; rerun with --rebuild")
    if previous_patch is None:
        _run(apply_command())
        PATCH_MARKER_PATH.write_text(patch_sha256 + "\n", encoding="utf-8")

    _run(configure_command())
    _run(build_command())
    library_path = resolve_built_library()
    manifest: dict[str, object] = {
        "geos_repository": GEOS_REPOSITORY,
        "geos_ref": GEOS_REF,
        "patch_sha256": patch_sha256,
        "library_path": str(library_path),
        "build_seconds": round(time.perf_counter() - started, 6),
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-only", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_only:
        for command in (
            clone_command(),
            apply_command(),
            configure_command(),
            build_command(),
        ):
            print(shlex.join(command))
        return 0
    manifest = build_proof(rebuild=bool(args.rebuild))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
