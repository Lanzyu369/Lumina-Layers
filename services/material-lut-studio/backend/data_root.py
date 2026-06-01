"""Data-root ownership for the MLS backend.
MLS 后端的数据根所有权。

Route B makes Material-LUT Studio the sole owner of the material-archive and
LUT data directories. This module is the single place that resolves those
roots so routers never hard-code paths. By default it reuses the main
repository's canonical locations (``config.MATERIALS_DIR`` and
``LUTManager.LUT_PRESET_DIR``); both can be overridden via environment
variables for tests or alternate deployments.

路线 B 让 MLS 成为耗材档案与 LUT 数据目录的唯一所有者。本模块是解析这些
根目录的唯一位置，路由不再硬编码路径。默认复用主仓库的规范位置
（``config.MATERIALS_DIR`` 与 ``LUTManager.LUT_PRESET_DIR``）；两者均可通过
环境变量覆盖，便于测试或其他部署。

Environment overrides (环境变量覆盖):
    MLS_MATERIALS_DIR: Absolute path to the materials root. (耗材根目录)
    MLS_LUT_PRESET_DIR: Absolute path to the LUT preset root. (LUT 预设根目录)
"""

from __future__ import annotations

import os
from pathlib import Path

from . import bootstrap

bootstrap.ensure_repo_on_path()

from config import MATERIALS_DIR as _REPO_MATERIALS_DIR  # noqa: E402
from utils.lut_manager import LUTManager  # noqa: E402

_SOLVER_CACHE_DIRNAME = "_solver_cache"


def materials_root() -> Path:
    """Resolve the material-archive root directory.
    解析耗材档案根目录。

    Returns:
        Path: ``MLS_MATERIALS_DIR`` if set, else ``config.MATERIALS_DIR``.
            （设置了 ``MLS_MATERIALS_DIR`` 则用它，否则用主仓库的 MATERIALS_DIR）
    """
    override = os.environ.get("MLS_MATERIALS_DIR")
    root = Path(override) if override else Path(_REPO_MATERIALS_DIR)
    return root


def solver_cache_root() -> Path:
    """Resolve the solver-cache directory under the materials root.
    解析耗材根目录下的求解缓存目录。

    Returns:
        Path: ``<materials_root>/_solver_cache``. (求解缓存目录)
    """
    return materials_root() / _SOLVER_CACHE_DIRNAME


def lut_preset_root() -> Path:
    """Resolve the LUT preset root directory.
    解析 LUT 预设根目录。

    Returns:
        Path: ``MLS_LUT_PRESET_DIR`` if set, else ``LUTManager.LUT_PRESET_DIR``.
            （设置了 ``MLS_LUT_PRESET_DIR`` 则用它，否则用 LUTManager 的默认根）
    """
    override = os.environ.get("MLS_LUT_PRESET_DIR")
    if override:
        return Path(override)
    return Path(LUTManager.LUT_PRESET_DIR)


def describe_roots() -> dict[str, str]:
    """Return a serializable snapshot of the resolved data roots.
    返回已解析数据根目录的可序列化快照。

    Returns:
        dict[str, str]: Keys ``materials``, ``solver_cache``, ``lut_preset``
            mapped to absolute string paths. (三个数据根的绝对路径)
    """
    return {
        "materials": str(materials_root()),
        "solver_cache": str(solver_cache_root()),
        "lut_preset": str(lut_preset_root()),
    }
