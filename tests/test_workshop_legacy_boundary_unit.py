"""Regression guards for the installable-only Workshop boundary."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def test_obsolete_in_process_workshop_implementation_is_absent() -> None:
    legacy_paths = (
        FRONTEND / "workshop" / "modules" / "bead",
        FRONTEND / "workshop" / "host.ts",
        FRONTEND / "workshop" / "registry.ts",
    )

    assert [path.relative_to(ROOT) for path in legacy_paths if path.exists()] == []


def test_host_translations_do_not_embed_module_specific_bead_ui() -> None:
    translations = (
        FRONTEND / "i18n" / "translations.ts"
    ).read_text(encoding="utf-8")

    assert '"workshop.bead.' not in translations
