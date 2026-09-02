"""Local Docker deployment contract tests.

These tests pin local-only rollout knobs that are easy to regress because the
GLB v2 kernel itself lives in production Python code while activation happens
through PowerShell deployment scripts.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read_repo_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_local_docker_image_installs_glb_v2_dependencies() -> None:
    base_requirements = _read_repo_text("requirements.txt")
    v2_requirements = _read_repo_text("requirements-glb-v2.txt")
    dockerfile = _read_repo_text("Dockerfile")

    base_declared = {
        line.partition("#")[0].strip().casefold().split(">=", 1)[0]
        for line in base_requirements.splitlines()
        if line.partition("#")[0].strip()
    }
    v2_declared = {
        line.partition("#")[0].strip().casefold().split(">=", 1)[0]
        for line in v2_requirements.splitlines()
        if line.partition("#")[0].strip()
    }

    assert "rasterio" not in base_declared
    assert "manifold3d" in base_declared
    assert "rasterio" in v2_declared
    assert "manifold3d" not in v2_declared
    assert "COPY requirements.txt requirements-glb-v2.txt /app/" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt -r requirements-glb-v2.txt" in dockerfile


def test_base_runtime_requirements_include_task_parallelism_memory_sampler() -> None:
    base_requirements = _read_repo_text("requirements.txt")
    declared_requirements = [
        line.partition("#")[0].strip().casefold()
        for line in base_requirements.splitlines()
        if line.partition("#")[0].strip()
    ]

    assert any(
        requirement == "psutil"
        or requirement.startswith(
            ("psutil<", "psutil>", "psutil=", "psutil!", "psutil~", "psutil[")
        )
        for requirement in declared_requirements
    )


def test_local_docker_deploy_enables_glb_kernel_v2_by_default_with_rollback() -> None:
    deploy_script = _read_repo_text("scripts/docker_local_deploy.ps1")

    assert "[string]$GlbKernel = \"v2\"" in deploy_script
    assert 'ValidateSet("v1", "v2", "auto", "shapely_v1", "rasterio_manifold3d")' in deploy_script
    assert '"-e", "LUMINA_GLB_KERNEL=$GlbKernel"' in deploy_script
    assert '"GLB kernel   : $GlbKernel"' in deploy_script


def test_local_docker_deploy_enables_vector_glb_v2_without_overriding_bitmap_v2() -> None:
    deploy_script = _read_repo_text("scripts/docker_local_deploy.ps1")

    assert "[string]$VectorGlbKernel = \"v2\"" in deploy_script
    assert 'ValidateSet("v1", "v2", "trimesh_v1", "rasterio_manifold3d")' in deploy_script
    assert '"-e", "LUMINA_GLB_KERNEL=$GlbKernel"' in deploy_script
    assert '"-e", "LUMINA_VECTOR_GLB_KERNEL=$VectorGlbKernel"' in deploy_script
    assert '"Vector GLB   : $VectorGlbKernel"' in deploy_script


def test_local_docker_deploy_persists_materials_on_runtime_volume() -> None:
    deploy_script = _read_repo_text("scripts/docker_local_deploy.ps1")
    dockerfile = _read_repo_text("Dockerfile")

    assert '$materialsDir = Ensure-Directory (Join-Path $RuntimeRoot "materials")' in deploy_script
    assert '"-v", "${materialsDir}:/app/materials"' in deploy_script
    assert '"-e", "LUMINA_MATERIALS_DIR=/app/materials"' in deploy_script
    assert '"Materials    : $materialsDir"' in deploy_script
    assert "LUMINA_MATERIALS_DIR=/app/materials" in dockerfile


def test_local_docker_deploy_accepts_optional_material_seed() -> None:
    deploy_script = _read_repo_text("scripts/docker_local_deploy.ps1")
    dockerfile = _read_repo_text("Dockerfile")

    assert "[string]$MaterialsSeedPath = \"\"" in deploy_script
    assert "[string]$MaterialsSeedUrl = \"\"" in deploy_script
    assert "[string]$MaterialsSeedSha256 = \"\"" in deploy_script
    assert "MATERIALS_SEED_URL=$MaterialsSeedUrl" in deploy_script
    assert "MATERIALS_SEED_SHA256=$MaterialsSeedSha256" in deploy_script
    assert "LUMINA_MATERIALS_SEED_PATH=/app/resources/materials/lumina-materials-seed.zip" in deploy_script
    assert "ARG MATERIALS_SEED_URL=\"\"" in dockerfile
    assert "ARG MATERIALS_SEED_SHA256=\"\"" in dockerfile
    assert "lumina-materials-seed.zip" in dockerfile


def test_local_docker_deploy_forwards_material_registry_configuration() -> None:
    deploy_script = _read_repo_text("scripts/docker_local_deploy.ps1")
    auto_update_script = _read_repo_text("scripts/docker_auto_update.ps1")

    assert '[string]$MaterialRegistryUrl = ""' in deploy_script
    assert '[string]$MaterialRegistryChannels = ""' in deploy_script
    for key in (
        "LUMINA_MATERIAL_REGISTRY_URL",
        "LUMINA_MATERIAL_REGISTRY_CHANNELS",
        "LUMINA_MATERIAL_REGISTRY_TOKEN",
        "LUMINA_MATERIAL_REGISTRY_TIMEOUT_S",
        "LUMINA_MATERIAL_SYNC_STARTUP_REFRESH",
        "LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S",
    ):
        assert f'"{key}"' in deploy_script
    assert '$runArgs += @("-e", $key)' in deploy_script
    assert "LUMINA_MATERIAL_REGISTRY_TOKEN=$" not in deploy_script

    assert '[string]$MaterialRegistryUrl = ""' in auto_update_script
    assert '[string]$MaterialRegistryChannels = ""' in auto_update_script
    assert "if ($MaterialRegistryUrl.Trim())" in auto_update_script
    assert (
        '$deployArgs += @("-MaterialRegistryUrl", $MaterialRegistryUrl)'
        in auto_update_script
    )
    assert "if ($MaterialRegistryChannels.Trim())" in auto_update_script
    assert (
        '$deployArgs += @("-MaterialRegistryChannels", $MaterialRegistryChannels)'
        in auto_update_script
    )


def test_local_docker_deploy_accepts_omitted_registry_overrides(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell is not available")

    runtime_root = tmp_path / "runtime"
    lut_preset_root = runtime_root / "lut-preset"
    lut_preset_root.mkdir(parents=True)
    lut_preset_root.joinpath(".test-seed").write_text("seeded", encoding="utf-8")
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "docker_local_deploy.ps1"),
            "-RepoRoot",
            str(ROOT),
            "-RuntimeRoot",
            str(runtime_root),
            "-SkipBuild",
            "-NoStart",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (runtime_root / "user_settings.json").is_file()


def test_local_docker_serves_built_frontend_dist_on_public_port() -> None:
    dockerfile = _read_repo_text("Dockerfile")
    deploy_script = _read_repo_text("scripts/docker_local_deploy.ps1")

    assert "RUN cd frontend && pnpm build" in dockerfile
    assert "LUMINA_SERVE_FRONTEND_DIST=1" in dockerfile
    assert "LUMINA_FRONTEND_DIST_DIR=/app/frontend/dist" in dockerfile
    assert 'CMD ["python", "api_server.py"]' in dockerfile

    assert '"-p", "${PublicFrontendPort}:8000"' in deploy_script
    assert '"-e", "LUMINA_SERVE_FRONTEND_DIST=1"' in deploy_script
    assert '"-e", "LUMINA_FRONTEND_DIST_DIR=/app/frontend/dist"' in deploy_script


def test_local_docker_context_excludes_worktrees() -> None:
    dockerignore = _read_repo_text(".dockerignore")

    assert ".worktrees/" in dockerignore


def test_auto_update_preserves_local_glb_kernel_choice() -> None:
    auto_update_script = _read_repo_text("scripts/docker_auto_update.ps1")

    assert "[string]$GlbKernel = \"v2\"" in auto_update_script
    assert '"-GlbKernel", $GlbKernel' in auto_update_script
    assert "[string]$VectorGlbKernel = \"v2\"" in auto_update_script
    assert '"-VectorGlbKernel", $VectorGlbKernel' in auto_update_script
