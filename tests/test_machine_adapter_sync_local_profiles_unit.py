from __future__ import annotations

from pathlib import Path

from tools.machine_adapter.sync_local_profiles import (
    ensure_official_orca_cover_asset_cache,
    discover_local_asset_roots,
    discover_local_import_sources,
)


def test_discover_local_asset_roots_includes_image_only_vendor_dirs(tmp_path):
    appdata_root = tmp_path / "AppData" / "Roaming"
    bambu_elegoo = appdata_root / "BambuStudio" / "system" / "Elegoo"
    bambu_elegoo.mkdir(parents=True)
    (bambu_elegoo / "Elegoo Neptune 2D_cover.png").write_bytes(b"cover")

    roots = discover_local_asset_roots(
        appdata_root=appdata_root,
        slicer_ids=("BambuStudio",),
    )

    assert roots == ((appdata_root / "BambuStudio" / "system", "Elegoo"),)


def test_discover_local_import_sources_keeps_anycubic_client_version_overrides(tmp_path):
    appdata_root = tmp_path / "AppData" / "Roaming"
    anycubic_root = appdata_root / "AnycubicSlicerNext" / "system"
    (anycubic_root / "Anycubic" / "machine").mkdir(parents=True)
    (anycubic_root / "Anycubic.json").write_text(
        '{"version":"1.3.2605.22"}',
        encoding="utf-8",
    )

    sources = discover_local_import_sources(
        appdata_root=appdata_root,
        slicer_ids=("AnycubicSlicerNext",),
    )

    assert len(sources) == 1
    source = sources[0]
    assert source.source_version == "1.3.2605.22"
    assert source.application_metadata == "AnycubicSlicerNext-1.4.1.2"
    assert source.client_version == "1.4.1.2 20260604104233"


def test_discover_local_asset_roots_includes_snapmaker_web_images(tmp_path):
    appdata_root = tmp_path / "AppData" / "Roaming"
    image_dir = (
        appdata_root
        / "Snapmaker_Orca"
        / "web"
        / "flutter_web"
        / "assets"
        / "assets"
        / "images"
    )
    (appdata_root / "Snapmaker_Orca" / "system").mkdir(parents=True)
    image_dir.mkdir(parents=True)
    (image_dir / "snapmakerU1Cover.png").write_bytes(b"cover")

    roots = discover_local_asset_roots(
        appdata_root=appdata_root,
        slicer_ids=("SnapmakerOrca",),
    )

    assert roots == ((image_dir, ""),)


def test_ensure_official_orca_cover_asset_cache_downloads_centauri_covers(tmp_path):
    downloaded: list[tuple[str, Path]] = []

    def fake_downloader(url: str, destination: Path) -> None:
        downloaded.append((url, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(destination.name.encode("utf-8"))

    roots = ensure_official_orca_cover_asset_cache(
        cache_root=tmp_path / "cache",
        downloader=fake_downloader,
    )

    assert roots == ((tmp_path / "cache" / "OrcaSlicer" / "profiles", "Elegoo"),)
    names = {destination.name for _, destination in downloaded}
    assert names == {
        "Elegoo Centauri_cover.png",
        "Elegoo Centauri Carbon_cover.png",
        "Elegoo Centauri Carbon 2_cover.png",
    }
    for _, destination in downloaded:
        assert destination.read_bytes() == destination.name.encode("utf-8")
