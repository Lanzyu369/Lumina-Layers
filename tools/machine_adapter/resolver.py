from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class ResolvedMachineProfile:
    name: str
    vendor_key: str
    settings: dict[str, Any]
    source_files: tuple[SourceFile, ...]


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Profile JSON must be an object: {path}")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index_machine_json(machine_dir: Path) -> dict[str, Path]:
    if not machine_dir.is_dir():
        raise FileNotFoundError(f"Machine profile directory not found: {machine_dir}")

    index: dict[str, Path] = {}
    for path in sorted(machine_dir.rglob("*.json"), key=lambda item: item.as_posix()):
        data = _read_json(path)
        name = str(data.get("name") or path.stem)
        index[name] = path
    return index


def _resolve_profile(name: str, index: dict[str, Path], seen: set[str]) -> tuple[dict[str, Any], list[Path]]:
    if name in seen:
        chain = " -> ".join([*seen, name])
        raise ValueError(f"Cyclic machine profile inheritance/include: {chain}")
    if name not in index:
        raise KeyError(f"Machine profile reference not found: {name}")

    seen.add(name)
    path = index[name]
    data = _read_json(path)
    merged: dict[str, Any] = {}
    source_paths: list[Path] = []

    parent = str(data.get("inherits") or "").strip()
    if parent:
        parent_settings, parent_paths = _resolve_profile(parent, index, seen)
        merged.update(parent_settings)
        source_paths.extend(parent_paths)

    for include_name in data.get("include", []) or []:
        include_settings, include_paths = _resolve_profile(str(include_name), index, seen)
        merged.update(include_settings)
        source_paths.extend(include_paths)

    merged.update(data)
    source_paths.append(path)
    seen.remove(name)
    return merged, source_paths


def resolve_machine_profiles(*, root: Path, vendor_key: str) -> list[ResolvedMachineProfile]:
    """Resolve native Orca/Bambu-family machine profiles for one vendor."""
    machine_dir = root / vendor_key / "machine"
    index = _index_machine_json(machine_dir)
    resolved: list[ResolvedMachineProfile] = []

    for name, path in sorted(index.items()):
        data = _read_json(path)
        if str(data.get("instantiation", "")).lower() != "true":
            continue

        settings, source_paths = _resolve_profile(name, index, set())
        source_files = tuple(
            SourceFile(path=str(source_path.as_posix()), sha256=_sha256(source_path))
            for source_path in source_paths
        )
        resolved.append(
            ResolvedMachineProfile(
                name=name,
                vendor_key=vendor_key,
                settings=settings,
                source_files=source_files,
            )
        )

    return resolved
