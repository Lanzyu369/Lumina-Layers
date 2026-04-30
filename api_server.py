"""Lumina Studio API — Server Entry Point.
Lumina Studio API — 服务启动入口。

Minimal entry script that imports the FastAPI application instance
and starts the uvicorn ASGI server. Run with ``python api_server.py``.
最小化入口脚本，导入 FastAPI 应用实例并启动 uvicorn ASGI 服务器。
通过 ``python api_server.py`` 运行。
"""

import uvicorn

if __name__ == "__main__":
    # ``api.app`` is the canonical place that calls
    # ``load_env_local()`` at module scope; importing it here populates
    # ``.env.local`` values into ``os.environ`` before uvicorn boots.
    # ``api.app`` 在模块级调用 ``load_env_local()`` 是规范入口；在这里导入
    # 它会先把 ``.env.local`` 写入 ``os.environ``，再启动 uvicorn。
    from api.app import app

    uvicorn.run(app, host="0.0.0.0", port=8000)
