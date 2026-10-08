"""Core-layer domain exceptions.

Core modules should raise these exceptions instead of API-specific errors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CoreError(Exception):
    """Base exception for core-layer failures."""

    detail: str
    error_type: str = "core_error"

    def __str__(self) -> str:
        return self.detail


class CoreValidationError(CoreError):
    """Raised when caller input/parameters are invalid for core logic."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_validation_error")


class WipeTowerLayoutError(CoreValidationError):
    """Report a model-and-tower layout that cannot be safely exported.

    报告无法安全导出的模型与擦料塔布局；调用方应调整打印板或摆放选项。
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.error_type = "wipe_tower_layout_unavailable"


class CoreDependencyError(CoreError):
    """Raised when optional dependencies or external resources are unavailable."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_dependency_error")


class CoreProcessingError(CoreError):
    """Raised for unexpected processing failures in core logic."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_processing_error")


class MaterialArchiveConflictError(CoreError):
    """Raised when a material archive identity already exists.

    按品牌和名称保存耗材档案时发现已存在同一身份的档案。
    """

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="material_archive_conflict")


class NativeSvgInvalidError(CoreValidationError):
    """Report deterministic invalid input from the native SVG boundary.

    报告原生 SVG 边界识别出的确定性无效输入。
    """

    def __init__(self, detail: str, *, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(detail)


class NativeSvgInternalError(CoreProcessingError):
    """Report a native SVG ABI or processing failure without legacy retry.

    报告原生 SVG ABI 或处理故障；此类错误不得静默走旧链路重试。
    """

    def __init__(self, detail: str, *, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(detail)


class CachedPreviewAnalysisError(CoreError):
    """Raised when explicitly required preview analysis cannot be consumed.

    当用户的空间编辑要求复用预览分析，而缓存三件套无法安全读取或投影时抛出。
    """

    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            error_type="cached_preview_analysis_error",
        )
