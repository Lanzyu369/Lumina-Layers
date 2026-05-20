"""Per-image batch metadata sidecar schemas.
批量模式 per-image 元数据 sidecar 数据模型。

These schemas describe the JSON sidecar emitted by
``worker_batch_convert_item`` alongside each per-image 3MF / preview GLB
during ``batch-mode-merged-3mf``. The parent process consumes the sidecar
in the merge stage to (a) feed XY footprints to ``Layout_Helper`` and
(b) hand canonical material slot identities to
``MergedBambu3MFWriter`` without re-parsing the per-image 3MF.

本模块定义批量模式中 ``worker_batch_convert_item`` 在每张图旁边落盘的
JSON sidecar 数据模型。父进程在合并阶段读取 sidecar，用于 (a) 把 XY
包围盒喂给 ``Layout_Helper``，以及 (b) 把规范化的材料 slot 身份信息
交给 ``MergedBambu3MFWriter``，避免父进程再去重新解析 per-image 3MF。

The shape mirrors design.md §Components 5 ("Metadata sidecar 形态")
exactly. The shape is also consumed by ``utils.merged_bambu_3mf_writer``
through a structurally compatible ``MaterialSlot`` dataclass; keep the
field set in sync if either side changes.
形态严格对齐 design.md §Components 5；``utils.merged_bambu_3mf_writer``
中通过结构兼容的 ``MaterialSlot`` dataclass 消费同样的字段，任意一侧
新增字段需同步更新另一侧。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Hex color string like "#101010". Six hex digits, leading "#",
# case-insensitive. Matches the convention used by existing palette /
# preview color fields elsewhere in the API.
# 形如 "#101010" 的十六进制颜色字符串；与 API 其它 palette / preview
# 颜色字段的惯例保持一致。
_HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class MaterialSlot(BaseModel):
    """Single material slot identity carried in a per-image sidecar.
    单个 per-image sidecar 中携带的材料 slot 身份描述。

    Attributes:
        slot_id: 0-based slot index in the slicer; uniqueness within a
            single sidecar is enforced by ``PerImageMetadataSidecar``.
            切片软件中的 0-based slot 索引；单个 sidecar 内由
            ``PerImageMetadataSidecar`` 强制唯一。
        slot_name: Slot display name shown by the slicer (e.g.
            ``"Bambu PLA Black"``).
            切片软件中显示的 slot 名（例如 ``"Bambu PLA Black"``）。
        preview_color: Six-digit hex color used for frontend preview
            (e.g. ``"#101010"``).
            前端预览用六位十六进制颜色（例如 ``"#101010"``）。
        material_id: Stable identifier in the material archive (e.g.
            ``"GFL00"``); merged 3MF round-trip tests assert this value
            survives unchanged.
            材料 archive 中的稳定标识（例如 ``"GFL00"``）；合并 3MF
            round-trip 测试断言该值原样保留。
    """

    model_config = ConfigDict(extra="forbid")

    slot_id: int = Field(..., ge=0, description="0-based slot index in slicer")
    slot_name: str = Field(..., min_length=1, description="Slot display name")
    preview_color: str = Field(
        ...,
        pattern=_HEX_COLOR_PATTERN,
        description="Hex preview color like '#101010'",
    )
    material_id: str = Field(
        ..., min_length=1, description="Stable material archive identifier"
    )


class PerImageMetadataSidecar(BaseModel):
    """JSON sidecar written next to each per-image 3MF in batch mode.
    批量模式中与每张 per-image 3MF 同目录落盘的 JSON sidecar。

    The parent process loads this file during the merge stage of
    ``convert_batch`` so it does not have to re-parse per-image 3MF
    artifacts to recover slot metadata or XY footprints.
    父进程在 ``convert_batch`` 的合并阶段加载该文件，无需再解析
    per-image 3MF 即可恢复 slot 元数据与 XY 包围盒。

    Attributes:
        schema_version: Sidecar shape version; bump together with any
            breaking field-set change so loaders can refuse stale data.
            sidecar 形态版本号；任何不兼容字段变更必须同步 bump，加载方
            可以据此拒绝旧数据。
        source_filename: Original upload filename, surfaced in the
            merged 3MF and in BatchResponse for traceability.
            原始上传文件名；用于合并 3MF 与 BatchResponse 的追踪展示。
        xy_bbox_mm: Occupied XY footprint in millimetres. Transparent
            source-image padding is excluded when the image carries an
            alpha channel. Exactly the keys ``"width_mm"`` and
            ``"depth_mm"`` are required, both > 0.
            以毫米为单位的实际占位 XY 包围盒；带 alpha 通道的源图会排除
            透明留白。必须且仅包含 ``width_mm`` / ``depth_mm`` 两个键，
            且都 > 0。
        slots: Material slots used by this image. ``slot_id`` values
            must be unique within the sidecar (the merge writer handles
            any further normalisation).
            该图使用的材料 slot 列表；``slot_id`` 在同一 sidecar 内必须
            唯一（更进一步的规范化由合并 writer 负责）。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(
        default=1,
        ge=1,
        description="Sidecar schema version; current canonical value is 1",
    )
    source_filename: str = Field(
        ..., min_length=1, description="Original upload filename"
    )
    xy_bbox_mm: dict[Literal["width_mm", "depth_mm"], float] = Field(
        ...,
        description=(
            "Occupied XY footprint in mm; requires both width_mm and "
            "depth_mm keys"
        ),
    )
    slots: list[MaterialSlot] = Field(
        ..., min_length=1, description="Material slots used by this image"
    )

    @field_validator("xy_bbox_mm")
    @classmethod
    def _require_both_bbox_keys(
        cls, value: dict[str, float]
    ) -> dict[str, float]:
        """Ensure xy_bbox_mm has exactly the two expected keys with positive values.

        确保 xy_bbox_mm 恰好包含两个预期键，且取值均为正。
        """
        expected = {"width_mm", "depth_mm"}
        if set(value.keys()) != expected:
            raise ValueError(
                "xy_bbox_mm must contain exactly the keys "
                "'width_mm' and 'depth_mm'"
            )
        if value["width_mm"] <= 0 or value["depth_mm"] <= 0:
            raise ValueError(
                "xy_bbox_mm dimensions must be strictly positive"
            )
        return value

    @field_validator("slots")
    @classmethod
    def _require_unique_slot_ids(
        cls, value: list[MaterialSlot]
    ) -> list[MaterialSlot]:
        """Ensure no two slots share the same slot_id within one sidecar.

        在同一 sidecar 内禁止两个 slot 共用同一 ``slot_id``。
        """
        seen: set[int] = set()
        for slot in value:
            if slot.slot_id in seen:
                raise ValueError(
                    f"duplicate slot_id={slot.slot_id} in sidecar slots"
                )
            seen.add(slot.slot_id)
        return value


__all__ = ["MaterialSlot", "PerImageMetadataSidecar"]
