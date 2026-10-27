"""Bootstrap a read-only material seed into the writable material library.
将只读耗材 seed 首次安装到可写耗材库。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from config import MATERIALS_DIR, TEMP_DIR
from core.single_stage import import_saved_stage_a_material_archives

_IGNORED_MATERIAL_ROOT_NAMES = frozenset({"_sync", "_solver_cache"})
_DEFAULT_SEED_FILENAME = "lumina-materials-seed.zip"


def _materials_root_has_user_content(root: Path) -> bool:
    if not root.exists():
        return False
    for child in root.iterdir():
        if child.name in _IGNORED_MATERIAL_ROOT_NAMES:
            continue
        return True
    return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_seed_sha256(path: Path) -> None:
    expected = os.environ.get("LUMINA_MATERIALS_SEED_SHA256", "").strip().lower()
    if not expected:
        return
    if expected.startswith("sha256:"):
        expected = expected.split(":", 1)[1]
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError("Material seed sha256 mismatch")


def _download_seed(seed_url: str) -> Path:
    temp_root = Path(TEMP_DIR)
    temp_root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="lumina_materials_seed_",
        suffix=".zip",
        dir=temp_root,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    timeout_s = float(os.environ.get("LUMINA_MATERIALS_SEED_TIMEOUT_S", "60"))
    try:
        with urllib.request.urlopen(seed_url, timeout=timeout_s) as response:
            with temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return temp_path


def _resolve_seed_path() -> tuple[Path, str, bool] | None:
    raw_path = os.environ.get("LUMINA_MATERIALS_SEED_PATH", "").strip()
    if raw_path:
        seed_path = Path(raw_path).expanduser()
        if not seed_path.is_file():
            raise FileNotFoundError(f"Material seed not found: {seed_path}")
        return seed_path, str(seed_path), False

    raw_url = os.environ.get("LUMINA_MATERIALS_SEED_URL", "").strip()
    if raw_url:
        if not raw_url.startswith(("http://", "https://")):
            raise ValueError("Material seed URL must be http:// or https://")
        seed_path = _download_seed(raw_url)
        return seed_path, raw_url, True

    bundled_seed_path = Path(__file__).resolve().parent.parent / "resources" / "materials" / _DEFAULT_SEED_FILENAME
    if bundled_seed_path.is_file():
        return bundled_seed_path, str(bundled_seed_path), False
    return None


def install_material_seed_if_needed(
    *,
    materials_dir: str | None = None,
) -> dict[str, Any] | None:
    """Install the configured material seed when the writable library is empty.
    当可写耗材库为空时安装配置的耗材 seed。

    Args:
        materials_dir: Optional writable material library root.
            可选的可写耗材库根目录。

    Returns:
        dict[str, Any] | None: Install summary, or ``None`` when no seed is
            configured or the runtime library already has user content.
            安装摘要；未配置 seed 或运行时已有用户内容时返回 ``None``。
    """
    target_root = Path(materials_dir or MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    if _materials_root_has_user_content(target_root):
        return None

    resolved_seed = _resolve_seed_path()
    if resolved_seed is None:
        return None
    seed_path, seed_source, delete_after_import = resolved_seed
    try:
        _verify_seed_sha256(seed_path)
        result = import_saved_stage_a_material_archives(
            archive_path=str(seed_path),
            materials_dir=str(target_root),
        )
        return {
            "seed_source": seed_source,
            "installed_count": len(result.imported_materials),
            "installed_materials": result.imported_materials,
        }
    finally:
        if delete_after_import:
            try:
                seed_path.unlink()
            except OSError:
                pass
