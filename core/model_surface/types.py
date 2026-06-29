from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ModelSurfaceError(ValueError):
    """Domain error for model-surface workflow.

    模型覆面流程的领域错误。
    """


class EdgeMode(str, Enum):
    """Artwork edge handling mode for selected model surfaces.

    选中模型表面的画面边缘处理模式。
    """

    EDGE_TO_EDGE = "edge_to_edge"
    INSET = "inset"


@dataclass(frozen=True)
class MeshSummary:
    """Public mesh quality summary in millimeters.

    面向接口和界面的毫米单位模型质量摘要。
    """

    vertex_count: int
    face_count: int
    bounds_min_mm: tuple[float, float, float]
    bounds_max_mm: tuple[float, float, float]
    extents_mm: tuple[float, float, float]
    is_watertight: bool
    is_winding_consistent: bool
    body_count: int
    unit_warning: str | None

    def to_public_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation.

        返回适合 JSON 序列化的公开数据。
        """

        return asdict(self)


@dataclass(frozen=True)
class LoadedSurfaceMesh:
    """Loaded mesh plus immutable summary for model-surface operations.

    用于模型覆面操作的已加载网格和不可变摘要。
    """

    path: Path
    mesh: Any
    summary: MeshSummary
