"""Lumina Studio API — Server Entry Point.
Lumina Studio API — 服务启动入口。

Minimal entry script that imports the FastAPI application instance
and starts the uvicorn ASGI server. Run with ``python api_server.py``.
最小化入口脚本，导入 FastAPI 应用实例并启动 uvicorn ASGI 服务器。
通过 ``python api_server.py`` 运行。
"""

import json
import sys
from pathlib import Path

import uvicorn


_DESKTOP_NATIVE_SMOKE_FLAG = "--desktop-native-kernel-smoke"
_DESKTOP_NATIVE_SMOKE_REPORT_FLAG = "--desktop-native-kernel-smoke-report"


def main(argv: list[str] | None = None) -> int:
    """Run the packaged smoke command or start the API server.

    运行桌面打包 smoke 命令，或启动 API 服务。

    Args:
        argv: Command-line arguments without the executable name.
            （不含可执行文件名的命令行参数。）

    Returns:
        int: Process exit code.（进程退出码。）
    """

    arguments = list(sys.argv[1:] if argv is None else argv)
    if _DESKTOP_NATIVE_SMOKE_FLAG in arguments:
        from api.desktop_release_smoke import run_native_relief_smoke

        result = run_native_relief_smoke()
        report_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        if _DESKTOP_NATIVE_SMOKE_REPORT_FLAG in arguments:
            report_index = arguments.index(_DESKTOP_NATIVE_SMOKE_REPORT_FLAG) + 1
            if report_index >= len(arguments):
                raise ValueError(
                    f"{_DESKTOP_NATIVE_SMOKE_REPORT_FLAG} requires a file path",
                )
            Path(arguments[report_index]).write_text(
                report_json + "\n",
                encoding="utf-8",
            )
        else:
            print(report_json)
        return 0

    # ``api.app`` is the canonical place that calls ``load_env_local()`` at
    # module scope; importing it here populates ``.env.local`` before uvicorn.
    from api.app import app

    uvicorn.run(app, host="0.0.0.0", port=8000)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
