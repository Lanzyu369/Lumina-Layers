from __future__ import annotations

from pathlib import Path

from tools.machine_adapter.sync_local_profiles import (
    ensure_official_orca_cover_asset_cache,
    discover_local_asset_roots,
    discover_local_import_sources,
)
import tools.machine_adapter.sync_local_profiles as sync_local_profiles_module


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


def test_default_profile_root_uses_macos_application_support(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(sync_local_profiles_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(sync_local_profiles_module.Path, "home", lambda: Path("/Users/tester"))

    assert sync_local_profiles_module._default_appdata_root() == (
        Path("/Users/tester") / "Library" / "Application Support"
    )


def test_discover_local_asset_roots_includes_bed_model_only_vendor_dirs(tmp_path):
    appdata_root = tmp_path / "AppData" / "Roaming"
    anycubic = appdata_root / "AnycubicSlicerNext" / "system" / "Anycubic"
    anycubic.mkdir(parents=True)
    (anycubic / "Anycubic Kobra 3_buildplate_model.stl").write_bytes(b"stl")

    roots = discover_local_asset_roots(
        appdata_root=appdata_root,
        slicer_ids=("AnycubicSlicerNext",),
    )

    assert roots == (
        (appdata_root / "AnycubicSlicerNext" / "system", "Anycubic"),
    )


def test_discovers_bed_models_inside_installed_macos_slicer_bundles(tmp_path):
    discover_installed_slicer_asset_roots = getattr(
        sync_local_profiles_module,
        "discover_installed_slicer_asset_roots",
        None,
    )
    assert callable(discover_installed_slicer_asset_roots)
    if discover_installed_slicer_asset_roots is None:
        return

    profiles_root = (
        tmp_path
        / "Applications"
        / "BambuStudio.app"
        / "Contents"
        / "Resources"
        / "profiles"
    )
    vendor_root = profiles_root / "BBL"
    vendor_root.mkdir(parents=True)
    (vendor_root / "bbl-3dp-A1M.stl").write_bytes(b"stl")

    roots = discover_installed_slicer_asset_roots(
        applications_root=tmp_path / "Applications",
    )

    assert roots == ((profiles_root, "BBL"),)


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


def test_discover_local_import_sources_keeps_flash_studio_version_contract(tmp_path):
    appdata_root = tmp_path / "AppData" / "Roaming"
    flash_root = appdata_root / "Orca-Flashforge" / "system"
    (flash_root / "Flashforge" / "machine").mkdir(parents=True)
    (flash_root / "Flashforge.json").write_text(
        '{"version":"02.01.01.00"}',
        encoding="utf-8",
    )

    sources = discover_local_import_sources(
        appdata_root=appdata_root,
        slicer_ids=("FlashStudio",),
    )

    assert len(sources) == 1
    source = sources[0]
    assert source.source_root == flash_root
    assert source.source_version == "02.01.01.00"
    assert source.application_metadata == "BambuStudio-2.3.2"
    assert source.client_version == ""


def test_discover_local_import_sources_keeps_qidi_studio_version_contract(tmp_path):
    appdata_root = tmp_path / "AppData" / "Roaming"
    qidi_root = appdata_root / "QIDIStudio" / "system"
    for vendor_key in ("Q Series", "X 4 Series", "X 5 Series"):
        (qidi_root / vendor_key / "machine").mkdir(parents=True)
        (qidi_root / f"{vendor_key}.json").write_text(
            '{"version":"02.07.02.60"}',
            encoding="utf-8",
        )

    sources = discover_local_import_sources(
        appdata_root=appdata_root,
        slicer_ids=("QIDIStudio",),
    )

    assert len(sources) == 3
    assert {source.vendor_keys for source in sources} == {
        ("Q Series",),
        ("X 4 Series",),
        ("X 5 Series",),
    }
    for source in sources:
        assert source.source_root == qidi_root
        assert source.source_version == "02.07.02.60"
        assert source.application_metadata == "QIDIStudio-02.07.02.60"
        assert source.client_version == "02.07.02.60"


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
