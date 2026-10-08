#!/usr/bin/env python3
"""Build the exact native wheels required by Lumina's metadata export route.

构建 Lumina 元数据导出路径所需的精确原生 wheel；脚本只在显式构建阶段运行，
不会在产品运行时联网、安装依赖或回退到库存 writer。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fatcat_packaging_contract import (
    FATCAT_DISTRIBUTION,
    FATCAT_LEGACY_DISTRIBUTION,
    FATCAT_MODULE,
    FATCAT_SOURCE_COMMIT,
    FATCAT_VERSION,
    FATCAT_WRITER_DISTRIBUTION,
    FATCAT_WRITER_PATCH,
    FATCAT_WRITER_PATCH_SHA256,
    FATCAT_WRITER_SOURCE_COMMIT as WRITER_SOURCE_COMMIT,
    FATCAT_WRITER_VERSION as WRITER_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
WRITER_PATCH_RELATIVE = Path(FATCAT_WRITER_PATCH)
FATCAT_WHEEL_PREFIX = FATCAT_DISTRIBUTION.replace("-", "_") + "-"
WRITER_WHEEL_PREFIX = FATCAT_WRITER_DISTRIBUTION.replace("-", "_") + "-"


def _run(command: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run one build command with its real output.

    运行单条构建命令并保留真实输出；失败时直接终止构建，不隐藏错误。
    """

    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _verify_patch_applied(source_root: Path, patch_path: Path) -> None:
    """Require the pinned downstream patch to be applied exactly once.

    要求指定的下游补丁已经完整应用；干净的上游 checkout 或半应用状态都拒绝构建。
    """

    result = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "apply",
            "--reverse",
            "--check",
            str(patch_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "patched neroued source does not match the required B7 cumulative patch"
            + (f": {detail}" if detail else "")
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _one_wheel(directory: Path, prefix: str) -> Path:
    wheels = sorted(directory.glob(f"{prefix}*.whl"))
    if len(wheels) != 1:
        names = ", ".join(path.name for path in wheels) or "none"
        raise RuntimeError(f"expected one {prefix} wheel, found {names}")
    return wheels[0]


def _copy_wheel(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(".whl.tmp")
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def _wheel_records(directory: Path, prefix: str) -> list[dict[str, str]]:
    """Return every wheel variant currently present in the wheelhouse."""

    return [
        {"wheel": path.name, "sha256": _sha256(path)}
        for path in sorted(directory.glob(f"{prefix}*.whl"))
    ]


def build_native_wheels(
    *,
    fatcat_root: Path,
    neroued_source: Path,
    output_dir: Path,
    python_executable: Path,
) -> dict[str, Any]:
    """Build and record the C++ binding and patched writer wheels.

    构建并记录 C++ 绑定与补丁 writer wheel；输入源码必须由调用方明确提供。
    """

    fatcat_root = fatcat_root.resolve()
    neroued_source = neroued_source.resolve()
    output_dir = output_dir.resolve()
    patch_path = ROOT / WRITER_PATCH_RELATIVE
    for required in (
        fatcat_root / "pyproject.toml",
        neroued_source / "pyproject.toml",
        patch_path,
    ):
        if not required.is_file():
            raise FileNotFoundError(f"native dependency input is missing: {required}")

    writer_commit = _git_value(neroued_source, "rev-parse", "HEAD")
    if writer_commit != WRITER_SOURCE_COMMIT:
        raise RuntimeError(
            "patched neroued source must be the pinned v0.4.0 commit "
            f"{WRITER_SOURCE_COMMIT}, got {writer_commit}"
        )
    _verify_patch_applied(neroued_source, patch_path)
    fatcat_commit = _git_value(fatcat_root, "rev-parse", "HEAD")
    if fatcat_commit != FATCAT_SOURCE_COMMIT:
        raise RuntimeError(
            f"Fat Cat source must be pinned to {FATCAT_SOURCE_COMMIT}, got {fatcat_commit}"
        )
    package = tomllib.loads(
        (fatcat_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    if package["name"] != FATCAT_DISTRIBUTION or package["version"] != FATCAT_VERSION:
        raise RuntimeError(
            f"Fat Cat wheel must be {FATCAT_DISTRIBUTION}=={FATCAT_VERSION}, "
            f"got {package['name']}=={package['version']}"
        )
    patch_sha256 = _sha256(patch_path)
    if patch_sha256 != FATCAT_WRITER_PATCH_SHA256:
        raise RuntimeError(
            "Lumina B7 patch does not match the pinned patch bytes: "
            f"expected {FATCAT_WRITER_PATCH_SHA256}, got {patch_sha256}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lumina-3mf-native-build-") as temp:
        temp_root = Path(temp)
        fatcat_wheels = temp_root / "fatcat"
        writer_wheels = temp_root / "writer"
        fatcat_wheels.mkdir()
        writer_wheels.mkdir()

        _run(
            [
                str(python_executable),
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(fatcat_wheels),
                str(fatcat_root),
            ],
            cwd=ROOT,
        )
        _run(
            [
                str(python_executable),
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(writer_wheels),
                str(neroued_source),
            ],
            cwd=ROOT,
            env={**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": WRITER_VERSION},
        )

        fatcat_wheel = _one_wheel(fatcat_wheels, FATCAT_WHEEL_PREFIX)
        writer_wheel = _one_wheel(writer_wheels, WRITER_WHEEL_PREFIX)
        if WRITER_VERSION not in writer_wheel.name:
            raise RuntimeError(
                f"patched writer wheel is not version {WRITER_VERSION}: {writer_wheel.name}"
            )
        manifest_path = output_dir / "manifest.json"
        previous = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file() else {}
        )
        if (
            previous.get("fatcat_cpp", {}).get("source_commit") != fatcat_commit
            or previous.get("neroued_writer", {}).get("upstream_commit") != writer_commit
            or previous.get("neroued_writer", {}).get("patch_sha256") != patch_sha256
        ):
            # Only native wheels owned by this builder belong to a generation.
            for prefix in (
                FATCAT_WHEEL_PREFIX, WRITER_WHEEL_PREFIX,
                FATCAT_LEGACY_DISTRIBUTION.replace("-", "_") + "-",
            ):
                for stale in output_dir.glob(f"{prefix}*.whl"):
                    stale.unlink()
        fatcat_destination = output_dir / fatcat_wheel.name
        writer_destination = output_dir / writer_wheel.name
        _copy_wheel(fatcat_wheel, fatcat_destination)
        _copy_wheel(writer_wheel, writer_destination)

    manifest: dict[str, Any] = {
        "format": 1,
        "fatcat_cpp": {
            "distribution": FATCAT_DISTRIBUTION,
            "import": FATCAT_MODULE,
            "version": FATCAT_VERSION,
            "source_commit": fatcat_commit,
            "project_root": ".",
            "wheel": fatcat_destination.name,
            "sha256": _sha256(fatcat_destination),
            "wheels": _wheel_records(output_dir, FATCAT_WHEEL_PREFIX),
        },
        "neroued_writer": {
            "distribution": FATCAT_WRITER_DISTRIBUTION,
            "version": WRITER_VERSION,
            "upstream_commit": writer_commit,
            "patch": str(WRITER_PATCH_RELATIVE),
            "patch_sha256": patch_sha256,
            "wheel": writer_destination.name,
            "sha256": _sha256(writer_destination),
            "wheels": _wheel_records(output_dir, WRITER_WHEEL_PREFIX),
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"native wheelhouse ready: {output_dir}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def install_native_wheels(*, output_dir: Path, python_executable: Path) -> None:
    """Install the exact current build after checking its identity and hashes.

    校验当前构建的身份和文件摘要后精确安装；先卸载旧包，避免删除新包共用数据。
    """

    output_dir = output_dir.resolve()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = (
        ("fatcat_cpp", FATCAT_DISTRIBUTION, FATCAT_VERSION, "source_commit", FATCAT_SOURCE_COMMIT),
        ("neroued_writer", FATCAT_WRITER_DISTRIBUTION, WRITER_VERSION, "upstream_commit", WRITER_SOURCE_COMMIT),
    )
    wheels: list[str] = []
    for key, distribution, version, commit_key, commit in expected:
        record = manifest[key]
        if (record["distribution"], record["version"], record[commit_key]) != (distribution, version, commit):
            raise RuntimeError(f"native wheel manifest does not match the pinned {distribution}")
        wheel = (output_dir / record["wheel"]).resolve()
        if wheel.parent != output_dir or not wheel.name.endswith(".whl"):
            raise RuntimeError(f"native wheel is outside the generated wheelhouse: {wheel}")
        if _sha256(wheel) != record["sha256"]:
            raise RuntimeError(f"native wheel hash does not match manifest: {wheel.name}")
        wheels.append(str(wheel))
    _run(
        [str(python_executable), "-m", "pip", "uninstall", "-y", FATCAT_LEGACY_DISTRIBUTION],
        cwd=ROOT,
    )
    _run(
        [str(python_executable), "-m", "pip", "install", "--no-deps", "--force-reinstall", *wheels],
        cwd=ROOT,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fatcat-root", type=Path)
    parser.add_argument("--neroued-source", type=Path)
    parser.add_argument("--install", action="store_true", help="Install the exact wheels after building.")
    parser.add_argument("--install-only", action="store_true", help="Install the current manifest without rebuilding.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "wheelhouse" / "3mf",
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        type=Path,
        default=Path(sys.executable),
    )
    args = parser.parse_args()
    if not args.install_only and (args.fatcat_root is None or args.neroued_source is None):
        parser.error("--fatcat-root and --neroued-source are required when building")
    return args


def main() -> int:
    args = parse_args()
    if not args.install_only:
        build_native_wheels(
            fatcat_root=args.fatcat_root,
            neroued_source=args.neroued_source,
            output_dir=args.output_dir,
            python_executable=args.python_executable,
        )
    if args.install or args.install_only:
        install_native_wheels(output_dir=args.output_dir, python_executable=args.python_executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
