"""Refresh Prusa picker artwork using FatCat's native hardware configuration.

通过 FatCat 原生硬件配置更新 Prusa 设备选择图片，不生成模型或 3MF。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import fatcat_metadata as fatcat
import resvg_py


def sync_prusa_assets(asset_root: Path, registry_root: Path) -> None:
    """Render native thumbnails referenced by the installed FatCat catalog.

    将已安装 FatCat 目录引用的原生缩略图渲染为 512 像素 PNG。

    Args:
        asset_root: Native PrusaResearch assets directory. 原生图片目录。
        registry_root: Lumina machine registry directory. Lumina 设备目录。
    """
    catalog = fatcat.list_machines("PrusaSlicer")
    version = catalog["application_version"]
    relative_root = Path("slicers") / "PrusaSlicer" / version
    destination = registry_root / relative_root
    source_root = asset_root.resolve()
    artwork: dict[str, str] = {}
    vendor_versions: set[str] = set()
    rendered: set[Path] = set()
    for source in catalog["sources"]:
        result = fatcat.compose_project_settings({
            "project_source": "fatcat_native",
            "slicer_id": "PrusaSlicer",
            "application_version": version,
            "machine_uid": source["machine_uid"],
            "nozzle_uid": source["nozzle_uid"],
            "source_materials": [{"name": "PLA", "material_type": "PLA",
                                  "colour": "#808080"}],
        })
        hardware = result["project_settings"]["config_containers"][0]["preset"]["hw_config"]
        filename = str(hardware["thumbnail"])
        image = (source_root / filename).resolve()
        if not filename or image.parent != source_root or image.suffix.lower() != ".svg":
            raise ValueError(f"Invalid native Prusa thumbnail: {filename!r}")
        if not image.is_file():
            raise FileNotFoundError(image)
        output_filename = image.with_suffix(".png").name
        output_image = destination / "assets" / output_filename
        output_image.parent.mkdir(parents=True, exist_ok=True)
        if output_image not in rendered:
            output_image.write_bytes(bytes(resvg_py.svg_to_bytes(
                svg_path=str(image), width=512, dpi=96,
            )))
            rendered.add(output_image)
        artwork[source["machine_uid"]] = (
            relative_root / "assets" / output_filename
        ).as_posix()
        vendor_versions.add(str(hardware["repo_version"]))
    index = {
        "application_version": version,
        "source": {
            "release_tag": catalog["source"]["release_tag"],
            "vendor_id": "PrusaResearch",
            "vendor_versions": sorted(vendor_versions),
            "fatcat_source_revision": fatcat.__source_revision__,
        },
        "thumbnails": artwork,
    }
    (destination / "picker-assets.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, required=True)
    args = parser.parse_args()
    sync_prusa_assets(args.asset_root, args.registry_root)


if __name__ == "__main__":
    main()
