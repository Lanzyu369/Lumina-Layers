"""API startup adapter tests for the bundled Workshop seed."""

from __future__ import annotations

from pathlib import Path

import pytest

from api.workshop_seed import install_workshop_seed_if_needed
from core.workshop import WorkshopInstaller
from tests.test_workshop_seed_lifecycle_unit import _seed_directory


def test_seed_startup_is_a_noop_when_desktop_resource_is_not_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_WORKSHOP_SEED_DIR", raising=False)
    installer = WorkshopInstaller(data_dir=tmp_path / "workshop-data")

    assert install_workshop_seed_if_needed(installer=installer) is None
    assert installer.list() == ()


def test_seed_startup_converges_an_explicit_desktop_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_dir = _seed_directory(tmp_path, "1.0.1")
    monkeypatch.setenv("LUMINA_WORKSHOP_SEED_DIR", str(seed_dir))
    installer = WorkshopInstaller(data_dir=tmp_path / "workshop-data")

    result = install_workshop_seed_if_needed(installer=installer)

    assert result is not None
    assert result.action == "installed"
    state = installer.get("lumina.bead-pattern")
    assert state is not None
    assert state.candidate_version == "1.0.1"


def test_seed_startup_fails_closed_for_a_configured_invalid_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_dir = _seed_directory(tmp_path, "1.0.1")
    lock_path = seed_dir / "seed-lock.json"
    lock_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LUMINA_WORKSHOP_SEED_DIR", str(seed_dir))
    installer = WorkshopInstaller(data_dir=tmp_path / "workshop-data")

    with pytest.raises(ValueError):
        install_workshop_seed_if_needed(installer=installer)

    assert installer.list() == ()
