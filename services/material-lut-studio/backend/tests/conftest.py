"""Pytest bootstrap for the MLS backend test suite.
MLS 后端测试套件的 pytest 引导。

Adds the service directory (so ``import backend`` works) and the repo root
(so ``import core/config/api`` works) to ``sys.path`` before any test module
imports the app. This mirrors ``server.py``'s path handling so MLS tests run
without an editable install.
将服务目录（使 ``import backend`` 可用）与仓库根（使 ``import core/config/api``
可用）加入 ``sys.path``，对齐 ``server.py`` 的路径处理，使 MLS 测试无需可编辑
安装即可运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

# services/material-lut-studio/backend/tests/conftest.py
#   parents[1] -> backend            (not needed on path)
#   parents[2] -> material-lut-studio (so ``import backend`` works)
#   parents[4] -> repo root           (so ``import core/config/api`` works)
_SERVICE_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
for _p in (str(_SERVICE_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
