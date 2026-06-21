#!/usr/bin/env python3
"""Build optional native extension modules for Lumina Studio."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import subprocess
import sysconfig
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
NATIVE_ROOT = ROOT / "native" / "clipper2_batch"
CLIPPER_ROOT = NATIVE_ROOT / "Clipper2" / "CPP" / "Clipper2Lib"


@dataclass(frozen=True)
class NativeExtension:
    name: str
    sources: list[str]
    include_dirs: list[str]
    language: str
    extra_compile_args: list[str]


def _build_path(path: Path) -> str:
    """Return a repo-relative path when possible, otherwise an absolute path."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _compiler_args() -> list[str]:
    if os.name == "nt":
        return ["/std:c++17", "/O2"]
    return ["-std=c++17", "-O3", "-DNDEBUG"]


def get_clipper2_extension() -> NativeExtension:
    """Return build metadata for the Clipper2 vector mesh module."""

    sources = [
        NATIVE_ROOT / "clipper2_batch_module.cpp",
        CLIPPER_ROOT / "src" / "clipper.engine.cpp",
        CLIPPER_ROOT / "src" / "clipper.offset.cpp",
        CLIPPER_ROOT / "src" / "clipper.triangulation.cpp",
    ]
    include_dirs = [CLIPPER_ROOT / "include", Path(np.get_include()).resolve()]
    return NativeExtension(
        name="clipper2_batch",
        sources=[_build_path(path) for path in sources],
        include_dirs=[_build_path(path) for path in include_dirs],
        language="c++",
        extra_compile_args=_compiler_args(),
    )


def _extension_suffix() -> str:
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if suffix:
        return str(suffix)
    return ".pyd" if os.name == "nt" else ".so"


def _output_path(extension: NativeExtension) -> Path:
    return ROOT / f"{extension.name}{_extension_suffix()}"


def _compile_command(extension: NativeExtension) -> list[str]:
    if os.name == "nt":
        raise RuntimeError(
            "Native extension build currently requires a POSIX-like C++ compiler. "
            "Set up a platform build step for Windows before enabling packaged native mesh acceleration there."
        )

    compiler = os.environ.get("CXX", "c++")
    include_dirs = [
        sysconfig.get_paths()["include"],
        *[str(ROOT / include_dir) for include_dir in extension.include_dirs],
    ]
    command = [
        compiler,
        *extension.extra_compile_args,
        "-fPIC",
        "-shared",
    ]
    if sysconfig.get_platform().startswith("macosx"):
        command.extend(["-undefined", "dynamic_lookup"])
    command.extend(f"-I{include_dir}" for include_dir in include_dirs)
    command.extend(str(ROOT / source) for source in extension.sources)
    command.extend(["-o", str(_output_path(extension))])
    return command


def build_extensions() -> None:
    """Build native extensions in-place at the repository root."""

    extension = get_clipper2_extension()
    missing = [path for path in extension.sources if not (ROOT / path).exists()]
    missing.extend(path for path in extension.include_dirs if not (ROOT / path).exists())
    if missing:
        missing_text = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Native extension sources are missing:\n{missing_text}")

    command = _compile_command(extension)
    print(" ".join(shlex.quote(part) for part in command))
    subprocess.run(command, check=True, cwd=ROOT)
    print(_output_path(extension))


def main() -> int:
    build_extensions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
