"""Shared contract for preview-analysis cache reuse.
预览分析缓存复用的共享契约。
"""

from __future__ import annotations

from typing import Final, Literal, TypeAlias


REQUIRED_PREVIEW_ANALYSIS_REUSE: Final[Literal["required"]] = "required"
PreviewAnalysisReuse: TypeAlias = bool | Literal["required"]


def preview_analysis_reuse_is_required(value: object) -> bool:
    """Return whether cached analysis is mandatory for this generation.

    返回本次生成是否必须消费缓存分析；必须模式禁止静默回退到重新分析。
    """

    return value == REQUIRED_PREVIEW_ANALYSIS_REUSE
