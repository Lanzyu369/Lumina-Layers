#!/usr/bin/env python3
"""Material-LUT Studio — backend dev launcher.
Material-LUT Studio — 后端开发启动器。

Starts the MLS FastAPI app with uvicorn on the configured port. Run from the
repository root so relative data roots resolve correctly:

    python services/material-lut-studio/backend/server.py
    MLS_PORT=8100 python services/material-lut-studio/backend/server.py

The parent ``material-lut-studio`` directory contains a hyphen, so it cannot
be a dotted Python module path. We therefore add the service directory to
``sys.path`` and import the ``backend`` package, then hand uvicorn the app
object directly (dev launcher runs with ``reload=False``).

父目录 ``material-lut-studio`` 含连字符，不能作为点分模块路径。因此把服务
目录加入 ``sys.path`` 并导入 ``backend`` 包，再把 app 对象直接交给 uvicorn
（开发启动器以 ``reload=False`` 运行）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# services/material-lut-studio/backend/server.py
#   parents[1] -> services/material-lut-studio   (so ``import backend`` works)
#   parents[3] -> repo root                       (so ``import core/config`` works)
_SERVICE_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_SERVICE_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uvicorn  # noqa: E402

from backend.app import app  # noqa: E402

DEFAULT_PORT = 8100


def main() -> None:
    """Launch the MLS backend with uvicorn.
    使用 uvicorn 启动 MLS 后端。
    """
    port = int(os.environ.get("MLS_PORT", DEFAULT_PORT))
    host = os.environ.get("MLS_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
