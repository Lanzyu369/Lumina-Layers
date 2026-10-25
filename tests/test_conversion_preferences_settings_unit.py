"""Durable conversion preferences through the existing settings-file API."""

import json
from pathlib import Path

from api.routers import system
from api.schemas.system import UserSettings


def test_conversion_preferences_survive_settings_file_reload(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "user_settings.json"
    monkeypatch.setattr(system, "SETTINGS_FILE", path)
    preferences = {"last": {"source_version": "material", "size_mm": 225}, "selectedPresetId": "art",
                   "presets": [{"id": "art", "name": "日常单面板画", "parameters": {"size_mm": 225}}]}
    system.save_settings(UserSettings(conversion_preferences=preferences))
    assert json.loads(path.read_text(encoding="utf-8"))["conversion_preferences"] == preferences
    assert system.get_settings().settings.conversion_preferences == preferences


def test_older_settings_clients_preserve_conversion_preferences(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "user_settings.json"
    monkeypatch.setattr(system, "SETTINGS_FILE", path)
    preferences = {"last": {"size_mm": 225}, "presets": [], "selectedPresetId": None}
    path.write_text(json.dumps({"conversion_preferences": preferences}), encoding="utf-8")
    system.save_settings(UserSettings(language="en"))
    saved = system.get_settings().settings
    assert saved.language == "en"
    assert saved.conversion_preferences == preferences


def test_missing_preferences_keep_existing_partial_settings(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "user_settings.json"
    monkeypatch.setattr(system, "SETTINGS_FILE", path)
    path.write_text('{"language":"en","theme":"dark"}', encoding="utf-8")
    saved = system.get_settings().settings
    assert saved.conversion_preferences is None
    assert saved.language == "en"
    assert saved.theme == "dark"
