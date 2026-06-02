"""Repository import bootstrap for the MLS backend.
MLS 后端的仓库导入引导。

The Material-LUT Studio service deliberately reuses the main repository's
pure domain logic (``core``, ``utils.lut_manager``, ``config``,
``api.schemas``) instead of copying algorithms, so the two processes never
drift apart. To import those modules the repository root must be on
``sys.path``. This module computes the repo root and inserts it exactly once.

MLS 服务有意复用主仓库的纯领域逻辑（``core``、``utils.lut_manager``、
``config``、``api.schemas``），而非复制算法，避免两份实现漂移。要导入这些
模块，必须把仓库根目录加入 ``sys.path``。本模块计算仓库根并只插入一次。

Import side effects:
    Importing this module caps BLAS/OpenMP thread pools before NumPy/SciPy are
    imported, and guarantees ``sys.path`` contains the repository root. Call
    :func:`configure_blas_thread_limits` and :func:`ensure_repo_on_path`
    explicitly for readability at the top of entry-point modules.
    导入本模块会在 NumPy/SciPy 导入前限制 BLAS/OpenMP 线程池，并保证
    ``sys.path`` 含仓库根；入口模块顶部可显式调用
    :func:`configure_blas_thread_limits` 与 :func:`ensure_repo_on_path`
    以提高可读性。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# services/material-lut-studio/backend/bootstrap.py -> repo root is 3 levels up.
# services/material-lut-studio/backend/bootstrap.py，仓库根在上溯三层。
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
BLAS_THREAD_ENV_VARS: tuple[str, ...] = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def configure_blas_thread_limits(default: str = "1") -> None:
    """Cap BLAS/OpenMP thread pools before numerical libraries are imported.
    在数值计算库导入前限制 BLAS/OpenMP 线程池。

    Uses ``setdefault`` so deployment-specific overrides remain honored.
    使用 ``setdefault``，保留部署环境中的显式覆盖值。

    Args:
        default: Thread count used when no environment override exists.
            (环境未显式设置时使用的线程数)
    """
    for env_name in BLAS_THREAD_ENV_VARS:
        os.environ.setdefault(env_name, default)


def ensure_repo_on_path() -> Path:
    """Insert the repository root onto ``sys.path`` (idempotent).
    将仓库根目录插入 ``sys.path``（幂等）。

    Returns:
        Path: The resolved repository root. (解析后的仓库根目录)
    """
    repo_str = str(REPO_ROOT)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    return REPO_ROOT


configure_blas_thread_limits()
ensure_repo_on_path()
