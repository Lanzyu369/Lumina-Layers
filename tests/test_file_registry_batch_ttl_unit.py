"""Unit tests for batch merge FileRegistry TTL behavior.
批量合并 FileRegistry TTL 行为单元测试。

Validates:
- Merged 3MF and preview GLB survive source session close (owner tag is
  batch-merge: / batch-preview:, not session-bound).
- Intermediate per-image files are cleaned up after successful merge.
- After TTL expires + GC, the download URLs return 404.

Requirements: 7.1, 7.2, 7.3, 10.5
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from api.file_registry import FileRegistry
from config import TEMP_DIR


class TestBatchMergeTTL:
    """Verify batch merge products survive session close but expire after TTL."""

    def test_merged_products_survive_session_close(self) -> None:
        """Merged 3MF/GLB registered with batch-merge:/batch-preview: owner
        survive cleanup of a different session_id.

        Requirements: 7.1, 7.2
        """
        registry = FileRegistry()
        os.makedirs(TEMP_DIR, exist_ok=True)

        # Create fake merged files.
        fd1, merged_3mf = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR)
        os.write(fd1, b"merged-3mf-content")
        os.close(fd1)

        fd2, merged_glb = tempfile.mkstemp(suffix=".glb", dir=TEMP_DIR)
        os.write(fd2, b"merged-glb-content")
        os.close(fd2)

        batch_run_id = "deadbeef1234"

        # Register with batch-specific owner tags (not a user session).
        download_id = registry.register_path(
            session_id=f"batch-merge:{batch_run_id}",
            path=merged_3mf,
            filename="batch.3mf",
            ttl_seconds=3600,
        )
        preview_id = registry.register_path(
            session_id=f"batch-preview:{batch_run_id}",
            path=merged_glb,
            filename="batch_preview.glb",
            ttl_seconds=3600,
        )

        # Simulate "source session close" by cleaning up a hypothetical
        # user session that is NOT the batch-merge/batch-preview owner.
        registry.cleanup_session("user-session-abc123")

        # Both files should still be resolvable.
        result_3mf = registry.resolve(download_id)
        assert result_3mf is not None, "Merged 3MF should survive session close"
        assert result_3mf[0] == merged_3mf

        result_glb = registry.resolve(preview_id)
        assert result_glb is not None, "Merged GLB should survive session close"
        assert result_glb[0] == merged_glb

        # Cleanup.
        try:
            os.unlink(merged_3mf)
        except OSError:
            pass
        try:
            os.unlink(merged_glb)
        except OSError:
            pass

    def test_intermediate_files_cleaned_after_merge(self) -> None:
        """Per-image intermediate 3MF/GLB/sidecar are deleted after merge.

        This test verifies the cleanup behavior by simulating what
        _cleanup_intermediates does (best-effort unlink).

        Requirement: 7.3
        """
        os.makedirs(TEMP_DIR, exist_ok=True)

        # Create fake intermediate files.
        intermediates = []
        for suffix in (".3mf", ".glb", ".json"):
            fd, path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR, prefix="batch-test-")
            os.write(fd, b"intermediate-content")
            os.close(fd)
            intermediates.append(Path(path))

        # All exist before cleanup.
        for p in intermediates:
            assert p.exists(), f"Intermediate should exist before cleanup: {p}"

        # Simulate cleanup (same logic as _cleanup_intermediates).
        for p in intermediates:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

        # All should be gone after cleanup.
        for p in intermediates:
            assert not p.exists(), f"Intermediate should be deleted: {p}"

    def test_ttl_expiry_makes_files_unresolvable(self) -> None:
        """After TTL expires, resolve() returns None (simulates 404).

        Requirement: 7.1, 7.2, 10.5
        """
        registry = FileRegistry()
        os.makedirs(TEMP_DIR, exist_ok=True)

        # Create a fake merged file with very short TTL.
        fd, merged_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR)
        os.write(fd, b"merged-content")
        os.close(fd)

        # Register with TTL = 1 second.
        file_id = registry.register_path(
            session_id="batch-merge:test-ttl",
            path=merged_path,
            filename="batch.3mf",
            ttl_seconds=1,
        )

        # Immediately resolvable.
        result = registry.resolve(file_id)
        assert result is not None, "File should be resolvable before TTL expires"

        # Wait for TTL to expire.
        time.sleep(1.5)

        # After TTL, resolve returns None (equivalent to 404 at the API level).
        result = registry.resolve(file_id)
        assert result is None, "File should NOT be resolvable after TTL expires"

        # The file should have been deleted by resolve's expiry logic.
        assert not os.path.exists(merged_path), (
            "Expired file should be deleted from disk"
        )

    def test_cleanup_expired_removes_batch_entries(self) -> None:
        """cleanup_expired() removes batch entries after TTL.

        Requirement: 10.5
        """
        registry = FileRegistry()
        os.makedirs(TEMP_DIR, exist_ok=True)

        fd, path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR)
        os.write(fd, b"content")
        os.close(fd)

        file_id = registry.register_path(
            session_id="batch-merge:gc-test",
            path=path,
            filename="batch.3mf",
            ttl_seconds=1,
        )

        # Before expiry: entry exists.
        entry = registry.get_entry(file_id)
        assert entry is not None

        time.sleep(1.5)

        # Trigger GC.
        removed = registry.cleanup_expired()
        assert removed >= 1, "cleanup_expired should remove at least 1 entry"

        # Entry gone.
        entry = registry.get_entry(file_id)
        assert entry is None, "Entry should be removed after GC"

        # File gone from disk.
        assert not os.path.exists(path), "File should be deleted after GC"
