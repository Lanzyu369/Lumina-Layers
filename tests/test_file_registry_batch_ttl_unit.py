"""Batch artifact ownership and expiry through the real file registry.
通过真实文件注册表验证批量产物的归属和过期清理。
"""

from pathlib import Path

import pytest

from api.file_registry import FileRegistry


class TestBatchMergeTTL:
    def test_merged_products_survive_session_close(self, tmp_path: Path) -> None:
        """Closing a source session removes its files while preserving batch output.
        关闭来源会话时删除其临时文件，并保留批量导出的产物。
        """
        registry = FileRegistry()
        source = tmp_path / "source.png"
        source.write_bytes(b"source-image")
        source_id = registry.register_path("source-session", str(source))

        artifacts = []
        for owner, filename in [
            ("batch-merge:run", "batch.3mf"),
            ("batch-preview:run", "batch.glb"),
        ]:
            path = tmp_path / filename
            path.write_bytes(b"batch-output")
            file_id = registry.register_path(owner, str(path), ttl_seconds=3600)
            artifacts.append((file_id, path))

        assert registry.cleanup_session("source-session") == 1
        assert registry.resolve(source_id) is None
        assert not source.exists()
        for file_id, path in artifacts:
            assert registry.resolve(file_id) == (str(path), path.name)
            assert path.read_bytes() == b"batch-output"

    def test_ttl_expiry_makes_files_unresolvable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Resolving an expired artifact removes its entry and disk file.
        访问过期产物时清除注册条目和磁盘文件。
        """
        now = [1000.0]
        monkeypatch.setattr("api.file_registry.time.time", lambda: now[0])
        registry = FileRegistry()
        path = tmp_path / "batch.3mf"
        path.write_bytes(b"merged-content")
        file_id = registry.register_path("batch-merge:run", str(path), ttl_seconds=1)

        assert registry.resolve(file_id) == (str(path), path.name)
        now[0] += 2

        assert registry.resolve(file_id) is None
        assert registry.get_entry(file_id) is None
        assert not path.exists()

    def test_cleanup_expired_removes_batch_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Expiry cleanup deletes batch artifacts and preserves live entries.
        过期清理删除到期的批量产物，并保留尚未过期的条目。
        """
        now = [1000.0]
        monkeypatch.setattr("api.file_registry.time.time", lambda: now[0])
        registry = FileRegistry()
        expired = tmp_path / "expired.3mf"
        live = tmp_path / "live.3mf"
        expired.write_bytes(b"expired")
        live.write_bytes(b"live")
        expired_id = registry.register_path("batch-merge:old", str(expired), ttl_seconds=1)
        live_id = registry.register_path("batch-merge:new", str(live), ttl_seconds=60)

        now[0] += 2

        assert registry.cleanup_expired() == 1
        assert registry.get_entry(expired_id) is None
        assert not expired.exists()
        assert registry.resolve(live_id) == (str(live), live.name)
        assert live.read_bytes() == b"live"
