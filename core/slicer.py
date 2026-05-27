# -*- coding: utf-8 -*-
"""
Slicer detection and launch module.

Extracted from ui/layout_new.py — pure business logic, no UI dependencies.
Scans Windows registry for known slicer software and launches them
with subprocess.Popen (non-blocking).
"""

import logging
import os
import platform
import plistlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_SLICERS: dict[str, dict] = {
    "bambu_studio": {
        "match": ["bambu studio", "bambustudio"],
        "display_name": "Bambu Studio",
    },
    "orca_slicer": {"match": ["orcaslicer", "orca slicer"], "display_name": "OrcaSlicer"},
    "snapmaker_orca": {
        "match": ["snapmaker_orca", "snapmaker orca", "snapmakerorca"],
        "display_name": "Snapmaker Orca",
    },
    "elegoo_slicer": {
        "match": ["elegooslicer", "elegoo slicer", "elegoo satellit"],
        "display_name": "ElegooSlicer",
    },
    "anycubic_slicer_next": {
        "match": [
            "anycubic slicer next",
            "anycubicslicernext",
            "anycubic slicer",
            "anycubicslicer",
        ],
        "display_name": "Anycubic Slicer Next",
    },
    "prusa_slicer": {
        "match": ["prusaslicer", "prusa slicer"],
        "display_name": "PrusaSlicer",
    },
    "cura": {
        "match": ["ultimaker cura", "ultimaker-cura", "cura"],
        "display_name": "Ultimaker Cura",
    },
}


@dataclass
class DetectedSlicer:
    """Detected slicer software information."""

    id: str  # Identifier, e.g. "bambu_studio"
    display_name: str  # Display name, e.g. "Bambu Studio"
    exe_path: str  # Absolute path to executable
    source: str = "auto"


# ---------------------------------------------------------------------------
# Registry scanning (Windows only)
# ---------------------------------------------------------------------------


def _match_slicer_id(display_name: str) -> tuple[str, str] | None:
    """Match a registry DisplayName against KNOWN_SLICERS.

    Returns (slicer_id, display_name_from_config) or None if no match.
    """
    dn_lower = display_name.lower()
    dn_compact = re.sub(r"[^a-z0-9]+", "", dn_lower)
    for sid, info in KNOWN_SLICERS.items():
        for kw in info["match"]:
            kw_lower = kw.lower()
            kw_compact = re.sub(r"[^a-z0-9]+", "", kw_lower)
            if kw_lower in dn_lower or (kw_compact and kw_compact in dn_compact):
                # Skip CUDA / NVIDIA entries that accidentally match "cura"
                if sid == "cura" and ("cuda" in dn_lower or "nvidia" in dn_lower):
                    break
                return sid, info["display_name"]
    return None


def _extract_exe_from_icon(icon_value: str) -> str | None:
    """Extract a valid exe path from a registry DisplayIcon value.

    DisplayIcon can be ``"path.exe"`` or ``"path.exe,0"`` and sometimes
    contains a doubled path like ``"F:\\...\\F:\\...\\exe"``.
    """
    icon = icon_value.split(",")[0].strip().strip('"')
    # Handle doubled path: try progressively shorter suffixes
    parts = icon.split("\\")
    for idx in range(1, len(parts)):
        candidate = "\\".join(parts[idx:])
        if os.path.isfile(candidate):
            return candidate
    if os.path.isfile(icon):
        return icon
    return None


def _find_exe_in_directory(directory: str, hint: str = "") -> str | None:
    """Find the slicer .exe in *directory*.
    找到目录中的切片器可执行文件。

    Args:
        directory (str): Directory to search. (搜索目录)
        hint (str): Lowercase keyword to prefer in filename. (文件名优先匹配关键词)

    Returns:
        str | None: Path to exe or None. (可执行文件路径或 None)
    """
    if not os.path.isdir(directory):
        return None
    candidates: list[str] = []
    for fname in os.listdir(directory):
        fl = fname.lower()
        if fl.endswith(".exe") and "unins" not in fl and "crashpad" not in fl:
            candidates.append(os.path.join(directory, fname))
    if not candidates:
        return None
    # Prefer exe whose name contains the hint keyword
    if hint:
        for c in candidates:
            # Compare with hyphens/underscores stripped for fuzzy match
            basename = os.path.basename(c).lower().replace("-", "").replace("_", "")
            if hint in basename:
                return c
    return candidates[0]


def scan_registry() -> list[DetectedSlicer]:
    """Scan Windows registry Uninstall keys for known slicer executables.

    On non-Windows platforms this returns an empty list immediately,
    avoiding any ``winreg`` import.
    """
    if platform.system() != "Windows":
        return []

    # Deferred import — only available on Windows
    import winreg  # noqa: F811

    found: dict[str, DetectedSlicer] = {}
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hive, base_path in reg_paths:
        try:
            key = winreg.OpenKey(hive, base_path)
        except OSError:
            continue

        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break

            try:
                subkey = winreg.OpenKey(key, subkey_name)
                try:
                    display_name: str = winreg.QueryValueEx(subkey, "DisplayName")[0]
                except OSError:
                    subkey.Close()
                    continue

                match = _match_slicer_id(display_name)
                if match is None or match[0] in found:
                    subkey.Close()
                    continue

                sid, config_display_name = match

                # --- resolve exe path ---
                exe_path: str | None = None

                # 1) Try DisplayIcon (most reliable)
                try:
                    icon_val: str = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                    exe_path = _extract_exe_from_icon(icon_val)
                except OSError:
                    pass

                # 2) Fallback: InstallLocation
                if exe_path is None:
                    try:
                        install_loc: str = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                        exe_hint = sid.replace("_", "")  # e.g. "snapmakerorca"
                        exe_path = _find_exe_in_directory(install_loc, hint=exe_hint)
                    except OSError:
                        pass

                # 3) Fallback: derive directory from UninstallString
                if exe_path is None:
                    try:
                        uninst: str = winreg.QueryValueEx(subkey, "UninstallString")[0]
                        uninst_path = uninst.strip().strip('"')
                        uninst_dir = os.path.dirname(uninst_path)
                        if uninst_dir:
                            exe_hint = sid.replace("_", "")
                            exe_path = _find_exe_in_directory(uninst_dir, hint=exe_hint)
                    except OSError:
                        pass

                subkey.Close()

                if exe_path and exe_path.lower().endswith(".exe") and os.path.isfile(exe_path):
                    found[sid] = DetectedSlicer(
                        id=sid,
                        display_name=config_display_name,
                        exe_path=exe_path,
                    )
                    logger.info(
                        "Slicer registry entry detected: %s -> %s",
                        config_display_name,
                        exe_path,
                        extra={
                            "event": "slicer_registry_entry_detected",
                            "slicer_name": config_display_name,
                            "exe_path": exe_path,
                        },
                    )
            except OSError:
                pass

        key.Close()

    return list(found.values())


# ---------------------------------------------------------------------------
# macOS .app bundle scanning
# ---------------------------------------------------------------------------


def _iter_macos_app_bundles(root: Path, max_depth: int = 2) -> list[Path]:
    """Return .app bundles under *root* without walking the whole filesystem.
    返回 root 下的 .app 包，避免全盘深度扫描。
    """
    if max_depth < 0 or not root.is_dir():
        return []
    bundles: list[Path] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return bundles
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.suffix.lower() == ".app":
            bundles.append(entry)
            continue
        if max_depth > 0 and not entry.name.startswith("."):
            bundles.extend(_iter_macos_app_bundles(entry, max_depth=max_depth - 1))
    return bundles


def _spotlight_macos_app_bundles() -> list[Path]:
    """Best-effort Spotlight lookup for application bundles.
    使用 Spotlight 尽力查找应用包。
    """
    try:
        result = subprocess.run(
            ["mdfind", "kMDItemContentType == 'com.apple.application-bundle'"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    bundles: list[Path] = []
    for line in result.stdout.splitlines():
        candidate = Path(line.strip())
        if candidate.suffix.lower() == ".app" and candidate.is_dir():
            bundles.append(candidate)
    return bundles


def _read_macos_app_info(app_path: Path) -> dict | None:
    info_path = app_path / "Contents" / "Info.plist"
    if not info_path.is_file():
        return None
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    except Exception as exc:  # noqa: BLE001 - third-party app bundles ship malformed plists
        # Some apps (e.g. broken installs, corrupt updates) leave an
        # Info.plist that fails XML/binary parsing with implementation-specific
        # errors such as ``xml.parsers.expat.ExpatError`` which is not in the
        # plistlib-declared exception set. Skip the bundle instead of letting
        # one bad plist take down the entire slicer-detection endpoint.
        # 某些应用包的 Info.plist 损坏，会抛出 plistlib 未声明的异常（如 ExpatError）；
        # 这里跳过该 bundle，避免单个坏文件拖垮整个 slicer 检测接口。
        logger.warning(
            "Failed to parse macOS app Info.plist, skipping bundle",
            extra={
                "event": "slicer_macos_plist_parse_failed",
                "app_path": str(app_path),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None
    return info if isinstance(info, dict) else None


def _slicer_from_macos_app(app_path: Path) -> DetectedSlicer | None:
    info = _read_macos_app_info(app_path)
    if info is None:
        return None
    fields = [
        app_path.stem,
        str(info.get("CFBundleName") or ""),
        str(info.get("CFBundleDisplayName") or ""),
        str(info.get("CFBundleIdentifier") or ""),
        str(info.get("CFBundleExecutable") or ""),
    ]
    match = _match_slicer_id(" ".join(field for field in fields if field))
    if match is None:
        return None
    sid, display_name = match
    return DetectedSlicer(
        id=sid,
        display_name=display_name,
        exe_path=str(app_path),
        source="macos_app",
    )


def validate_custom_slicer_path(path: str) -> DetectedSlicer | None:
    """Validate a user-provided slicer application path.
    校验用户手动提供的切片软件路径。
    """
    if platform.system() != "Darwin":
        return None
    app_path = Path(path).expanduser()
    if app_path.suffix.lower() != ".app" or not app_path.is_dir():
        return None
    slicer = _slicer_from_macos_app(app_path)
    if slicer is None:
        return None
    return DetectedSlicer(
        id=slicer.id,
        display_name=slicer.display_name,
        exe_path=str(app_path.resolve()),
        source="custom_macos_app",
    )


def scan_macos_app_bundles(
    search_roots: list[Path] | None = None,
    include_spotlight: bool = True,
) -> list[DetectedSlicer]:
    """Scan common macOS application locations for known slicers.
    扫描 macOS 常见应用目录，查找已知切片软件。
    """
    if platform.system() != "Darwin":
        return []
    roots = search_roots or [Path("/Applications"), Path.home() / "Applications"]
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(_iter_macos_app_bundles(root))
    if include_spotlight:
        candidates.extend(_spotlight_macos_app_bundles())

    found: dict[str, DetectedSlicer] = {}
    seen_paths: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except OSError:
            resolved = str(candidate)
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        slicer = _slicer_from_macos_app(candidate)
        if slicer is None or slicer.id in found:
            continue
        found[slicer.id] = DetectedSlicer(
            id=slicer.id,
            display_name=slicer.display_name,
            exe_path=resolved,
            source=slicer.source,
        )
        logger.info(
            "Slicer macOS app detected: %s -> %s",
            slicer.display_name,
            resolved,
            extra={
                "event": "slicer_macos_app_detected",
                "slicer_name": slicer.display_name,
                "app_path": resolved,
            },
        )
    return list(found.values())


def _is_valid_detected_slicer_path(path: str) -> bool:
    if path.lower().endswith(".app"):
        return os.path.isdir(path)
    return os.path.isfile(path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_installed_slicers() -> list[DetectedSlicer]:
    """Detect slicer software installed on the system.

    Delegates to the current platform discovery strategies.
    根据当前平台调用对应的检测策略。
    """
    if platform.system() == "Darwin":
        slicers = scan_macos_app_bundles()
    else:
        slicers = scan_registry()
    # Filter out entries whose exe no longer exists (defensive)
    slicers = [s for s in slicers if _is_valid_detected_slicer_path(s.exe_path)]
    if not slicers:
        logger.info("No slicers detected", extra={"event": "slicers_not_detected"})
    return slicers


def launch_slicer(
    slicer_id: str,
    file_path: str,
    known_slicers: list[DetectedSlicer],
) -> tuple[bool, str]:
    """Launch *slicer_id* to open *file_path*.

    Parameters
    ----------
    slicer_id:
        Identifier such as ``"bambu_studio"``.
    file_path:
        Absolute path to the file (typically ``.3mf``) to open.
    known_slicers:
        List of previously detected slicers (from :func:`detect_installed_slicers`).

    Returns
    -------
    tuple[bool, str]
        ``(success, message)`` — *success* is ``True`` when the process
        was spawned successfully.
    """
    if not os.path.isfile(file_path):
        return False, f"File does not exist: {file_path}"

    target: DetectedSlicer | None = None
    for s in known_slicers:
        if s.id == slicer_id:
            target = s
            break

    if target is None:
        return False, f"Slicer not found: {slicer_id}"

    try:
        if platform.system() == "Darwin" and target.exe_path.lower().endswith(".app"):
            subprocess.Popen(["open", "-a", target.exe_path, file_path])
        else:
            subprocess.Popen([target.exe_path, file_path])
        return True, f"Opened in {target.display_name}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Failed to launch {target.display_name}: {exc}"
