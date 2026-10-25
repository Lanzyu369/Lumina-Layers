"""Local history exposes installation dates without changing revision identity."""
import json
from pathlib import Path

from api.schemas.responses import MaterialSyncInstalledEntryResponse
from core.single_stage import material_sync


def test_history_uses_install_date_not_rollback_update_date(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(material_sync, "_local_material_sync_entries", lambda _root: [])
    sync = tmp_path / "_sync"
    sync.mkdir()
    old = {"revision_id": "old", "installed_at": "2026-09-01T00:00:00Z", "updated_at": "2026-10-25T00:00:00Z"}
    current = {"revision_id": "current", "installed_at": "2026-10-01T00:00:00Z"}
    (sync / "index.json").write_text(json.dumps({
        "schema_version": "1.0", "installed": {"material": current},
        "revisions": {"material": {"old": old, "current": current, "unknown": {"revision_id": "unknown"}}},
    }), encoding="utf-8")
    entry = material_sync.get_material_sync_status(materials_dir=str(tmp_path))["installed"][0]
    history = {row["revision_id"]: row["installed_at"] for row in entry["revision_history"]}
    assert history == {"old": "2026-09-01T00:00:00Z", "current": "2026-10-01T00:00:00Z", "unknown": None}
    assert MaterialSyncInstalledEntryResponse(**entry).model_dump()["revision_history"] == entry["revision_history"]
