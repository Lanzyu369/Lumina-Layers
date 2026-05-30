"""Material-LUT Studio — FastAPI application factory.
Material-LUT Studio — FastAPI 应用工厂。

Builds the standalone MLS FastAPI instance. MLS is the owner of the material
archive + LUT lifecycle (extract / generate / query / manage / store) and the
converter data API. The main Lumina app keeps only image→3MF conversion and
reaches MLS over HTTP.

构建独立的 MLS FastAPI 实例。MLS 拥有耗材档案 + LUT 的完整生命周期（提取/生成/
查询/管理/存储）与转换器数据 API；主 Lumina 应用只保留图片→3MF 转换，通过
HTTP 访问 MLS。

Extraction / generation / query endpoints are hosted by reusing the existing
domain routers (extractor / calibration / five-color / single-stage) and
overriding their session/registry dependencies with MLS-local singletons via
``dependency_overrides``. This keeps a single implementation of each handler
while making MLS their runtime owner.
提取/生成/查询端点通过复用既有领域路由（extractor / calibration / five-color /
single-stage）托管，并用 ``dependency_overrides`` 把它们的会话/registry 依赖替换
为 MLS 进程内单例。每个处理函数只有一份实现，运行时归 MLS 所有。
"""

from __future__ import annotations

from . import bootstrap

bootstrap.ensure_repo_on_path()

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.dependencies import (  # noqa: E402
    get_file_registry as main_get_file_registry,
    get_session_store as main_get_session_store,
)
from api.file_bridge import file_to_response  # noqa: E402
from api.file_registry import FileRegistry  # noqa: E402
from api.routers import (  # noqa: E402
    calibration_router,
    extractor_router,
    five_color_router,
    lut_router as main_lut_router,
    single_stage_router,
    system_router,
)
from api.structured_logging import configure_structured_logging, get_logger  # noqa: E402

from .dependencies import get_file_registry, get_session_store  # noqa: E402
from .auth import install_write_auth_middleware, get_auth_state  # noqa: E402
from .routers import (  # noqa: E402
    auth_router,
    data_router,
    health_router,
    lut_router,
    materials_router,
    solver_cache_router,
)

configure_structured_logging()
log = get_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure the MLS FastAPI application.
    创建并配置 MLS FastAPI 应用实例。

    Returns:
        FastAPI: Configured instance with CORS, MLS-native routers, the reused
            extract/generate/query domain routers (with MLS-local
            session/registry overrides), and the file-serving endpoint.
            （已配置 CORS、MLS 原生路由、复用的提取/生成/查询领域路由及文件端点）
    """
    app = FastAPI(title="Material-LUT Studio API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Write-access auth: when a password is configured (config.json or
    # ``MLS_WRITE_PASSWORD`` env), mutating endpoints require the
    # ``X-MLS-Password`` header. Pure read endpoints stay open so the
    # frontend can boot in read-only mode without a password.
    # 写入鉴权：配置了密码时，写端点要求 ``X-MLS-Password`` 头；只读端点保持开放，
    # 前端可在未输入密码时以只读模式进入。
    install_write_auth_middleware(app)

    # MLS-native routers (data ownership + management + data API).
    # MLS 原生路由（数据所有权 + 管理 + 数据 API）。
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(lut_router)
    app.include_router(materials_router)
    app.include_router(solver_cache_router)
    app.include_router(data_router)

    # Reused domain routers for extract / generate / query. Their handlers
    # depend on ``api.dependencies.get_session_store`` / ``get_file_registry``;
    # override both with MLS-local singletons so the stateful extraction flows
    # and download URLs are owned by this process.
    # 复用的提取/生成/查询领域路由；将其会话/registry 依赖覆盖为 MLS 进程内单例，
    # 使有状态提取流程与下载 URL 归本进程所有。
    app.include_router(extractor_router)
    app.include_router(single_stage_router)
    app.include_router(calibration_router)
    app.include_router(five_color_router)
    # Reuse the main app's LUT router at its legacy ``/api/lut/...`` paths so
    # frontend calls like ``/api/lut/list``, ``/api/lut/{name}/info``,
    # ``/api/lut/merge`` work directly via the Vite dev proxy. The MLS-native
    # ``/api/mls/lut/...`` router is kept alongside for cross-server callers
    # (the converter app on a different host hits those mls-prefixed paths).
    # 复用主应用的 LUT 路由，使前端 ``/api/lut/...`` 调用通过 Vite dev 代理直达；
    # 同时保留 ``/api/mls/lut/...`` 给跨服务器调用方使用。
    app.include_router(main_lut_router)
    # System router supplies image-preview / ColorChecker resource upload
    # (``/api/system/preview-resources`` etc.) plus printers / slicers /
    # settings used by the restored extraction & calibration panels.
    # system 路由提供图片预览 / ColorChecker 资源上传，以及恢复的提取与校准面板
    # 所需的打印机 / 切片软件 / 设置端点。
    app.include_router(system_router)

    app.dependency_overrides[main_get_session_store] = get_session_store
    app.dependency_overrides[main_get_file_registry] = get_file_registry

    @app.get("/api/files/{file_id}")
    def serve_file(
        file_id: str,
        registry: FileRegistry = Depends(get_file_registry),
    ):
        """Serve a registered file by ``file_id`` (ephemeral download URLs).
        按 ``file_id`` 提供已注册文件（临时下载 URL）。

        Resolves against the MLS-local FileRegistry. Used by material exports,
        extraction artifacts, generated swatches/kits, and warp previews.
        从 MLS 进程内 FileRegistry 解析，服务耗材导出、提取工件、生成色卡/套件、
        梯度卡预览等下载。
        """
        result = registry.resolve(file_id)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found or expired")
        path, filename = result
        return file_to_response(path, filename)

    log.info(
        "MLS application created",
        extra={
            "event": "mls_app_created",
            "router_count": 12,
            "write_password_configured": get_auth_state().password_required,
        },
    )
    if not get_auth_state().password_required:
        # Open mode: any caller can hit write endpoints. Surface this loudly
        # so operators see it during deployment review instead of finding
        # out via an unauthenticated DELETE.
        # 开放模式：任何调用方都能写。启动时大声告警，避免运维到事故时才发现。
        log.warning(
            "MLS write protection is disabled (no password configured)",
            extra={
                "event": "mls_write_protection_disabled",
                "error_type": "auth_unprotected",
                "remediation": (
                    "Set MLS_WRITE_PASSWORD env var, or fill write_password "
                    "in services/material-lut-studio/config.json."
                ),
            },
        )
    return app


app: FastAPI = create_app()
