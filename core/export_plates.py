"""Original-size independent print projects for explicitly separated backing."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import trimesh


def export_separate_backing_projects(
    scene: trimesh.Scene,
    output_path: str,
    *,
    project_slot_names: Sequence[str],
    exporter: Callable[..., str],
    base_height_mm: float,
    color_height_mm: float,
) -> str:
    """Write two independently laid-out native projects without changing geometry.

    Args:
        scene: Scene carrying explicit backing-role metadata. 含明确背板角色的场景。
        output_path: Requested model output path. 原始模型输出路径。
        project_slot_names: Source palette ordering. 来源调色板顺序。
        exporter: Existing native project writer with shared options bound.
            已绑定共享参数的既有原生工程写入入口。
        base_height_mm: Backing thickness. 背板厚度。
        color_height_mm: Optical model thickness. 彩色模型厚度。

    Returns:
        ZIP containing independently valid model and backing projects.
        包含独立模型工程和背板工程的 ZIP。
    """
    groups: dict[bool, list[tuple[str, trimesh.Trimesh]]] = {False: [], True: []}
    for name, mesh in scene.geometry.items():
        groups[mesh.metadata.get("lumina_print_role") == "backing"].append((name, mesh))
    if not groups[True] or not groups[False]:
        raise ValueError("Independent backing output requires both a model and an explicit backing part")
    target = Path(output_path).with_suffix(".zip")
    with TemporaryDirectory(prefix="lumina-plates-", dir=target.parent) as staging:
        projects: list[Path] = []
        for is_backing, name in [(False, "plate_1_model.3mf"), (True, "plate_2_backing.3mf")]:
            part = trimesh.Scene()
            used: set[str] = set()
            for geometry_name, mesh in groups[is_backing]:
                part.add_geometry(mesh.copy(), geom_name=geometry_name)
                used.add(str(mesh.metadata.get("bambu_material_name") or geometry_name))
            palette = [name for name in project_slot_names if name in used]
            palette.extend(sorted(used.difference(palette)))
            path = str(Path(staging) / name)
            exporter(
                scene=part, output_path=path, slot_names=list(part.geometry),
                project_slot_names=palette, preserve_template_filament_slots=False,
                base_height_mm=base_height_mm if is_backing else 0.0,
                color_height_mm=0.0 if is_backing else color_height_mm,
            )
            projects.append(Path(path))
        # Finish both native projects before exposing the final download.
        staged_zip = Path(staging) / target.name
        with ZipFile(staged_zip, "w", compression=ZIP_DEFLATED) as archive:
            for project in projects:
                archive.write(project, project.name)
        staged_zip.replace(target)
    return str(target)
