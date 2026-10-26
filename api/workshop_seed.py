"""Runtime adapter for the bundled official Creative Workshop seed.

官方创意工坊预装模块的运行时适配层。
"""

from __future__ import annotations

import os
from pathlib import Path

from config import get_workshop_data_dir
from core.workshop import (
    WorkshopInstallError,
    WorkshopInstaller,
    WorkshopSeedConvergenceResult,
    converge_workshop_seed,
)


def get_configured_workshop_seed_directory() -> Path | None:
    """Return the explicitly configured desktop seed directory.

    返回桌面端显式配置的预装模块目录；未配置时返回空值。
    """

    raw = os.environ.get("LUMINA_WORKSHOP_SEED_DIR")
    if raw is None or not raw.strip():
        return None
    if "\x00" in raw:
        raise ValueError("Workshop seed directory configuration is invalid")
    return Path(raw).expanduser()


def install_workshop_seed_if_needed(
    *,
    installer: WorkshopInstaller | None = None,
) -> WorkshopSeedConvergenceResult | None:
    """Converge a configured seed during application startup.

    在应用启动时收敛已配置的预装模块。普通开发服务器未配置桌面资源时不执行
    任何操作。
    """

    seed_directory = get_configured_workshop_seed_directory()
    if seed_directory is None:
        return None
    active_installer = installer or WorkshopInstaller(
        data_dir=get_workshop_data_dir()
    )
    return converge_workshop_seed(seed_directory, active_installer)


def restore_official_workshop_seed(
    module_id: str,
    *,
    installer: WorkshopInstaller | None = None,
) -> WorkshopSeedConvergenceResult:
    """Restore the matching user-uninstalled official seed candidate.

    从应用内置资源显式恢复匹配的、已被用户卸载的官方模块候选版本。
    """

    seed_directory = get_configured_workshop_seed_directory()
    if seed_directory is None:
        raise FileNotFoundError(
            "bundled official Workshop seed is unavailable"
        )
    active_installer = installer or WorkshopInstaller(
        data_dir=get_workshop_data_dir()
    )
    result = converge_workshop_seed(
        seed_directory,
        active_installer,
        restore_uninstalled=True,
        expected_module_id=module_id,
    )
    if result.state is None:
        raise WorkshopInstallError(
            "official Workshop seed restore did not produce module state"
        )
    return result
