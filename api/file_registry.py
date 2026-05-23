import os
import threading
import time
import uuid
from typing import Optional, Tuple
from config import MATERIALS_DIR, TEMP_DIR

class FileRegistry:
    """文件注册表，管理生成文件的 UUID 映射。

    支持两种注册方式：
    1. register_path(session_id, path, filename) — 注册磁盘文件路径
    2. register_bytes(session_id, data, filename) — 注册内存字节流（保存为临时文件）
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}
        # {file_id: {path, filename, session_id, created_at, expires_at, lifecycle}}
        self._lock = threading.Lock()

    def register_path(
        self,
        session_id: str,
        path: str,
        filename: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        is_public: bool = True,
        purpose: Optional[str] = None,
    ) -> str:
        """注册磁盘文件，返回 file_id。"""
        file_id = str(uuid.uuid4())
        if filename is None:
            filename = os.path.basename(path)
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds is not None else None
        delete_on_cleanup = self._should_delete_path(path)
        with self._lock:
            self._registry[file_id] = {
                "path": path,
                "filename": filename,
                "session_id": session_id,
                "created_at": now,
                "expires_at": expires_at,
                "ttl_seconds": ttl_seconds,
                "lifecycle": "ephemeral" if ttl_seconds is not None else "session_bound",
                "delete_on_cleanup": delete_on_cleanup,
                "is_public": bool(is_public),
                "purpose": purpose,
            }
        return file_id

    def register_bytes(
        self,
        session_id: str,
        data: bytes,
        filename: str,
        ttl_seconds: Optional[int] = None,
        is_public: bool = True,
        purpose: Optional[str] = None,
    ) -> str:
        """注册字节流（写入临时文件），返回 file_id。"""
        import tempfile

        suffix = os.path.splitext(filename)[1] or ".bin"
        fd, path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return self.register_path(
            session_id=session_id,
            path=path,
            filename=filename,
            ttl_seconds=ttl_seconds,
            is_public=is_public,
            purpose=purpose,
        )

    def resolve(self, file_id: str) -> Optional[Tuple[str, str]]:
        """解析 file_id，返回 (path, filename) 或 None。"""
        now = time.time()
        with self._lock:
            entry = self._registry.get(file_id)
            if entry is None:
                return None
            path = entry["path"]
            filename = entry["filename"]
            expires_at = entry.get("expires_at")
            ttl_seconds = entry.get("ttl_seconds")
            delete_on_cleanup = bool(entry.get("delete_on_cleanup", True))

        if expires_at is not None and now >= expires_at:
            cleaned = True if not delete_on_cleanup else self._delete_path(path)
            with self._lock:
                current = self._registry.get(file_id)
                if current is not None and current.get("path") == path and cleaned:
                    self._registry.pop(file_id, None)
            return None

        if not os.path.exists(path):
            with self._lock:
                current = self._registry.get(file_id)
                if current is not None and current.get("path") == path:
                    self._registry.pop(file_id, None)
            return None

        with self._lock:
            current = self._registry.get(file_id)
            if current is None or current.get("path") != path:
                return None
            current_ttl_seconds = current.get("ttl_seconds")
            if current_ttl_seconds is not None:
                current["expires_at"] = now + current_ttl_seconds
            return current["path"], current["filename"]

    def get_entry(self, file_id: str) -> dict | None:
        """Return a shallow copy of a registry entry.
        返回指定条目的只读浅拷贝。
        """
        with self._lock:
            entry = self._registry.get(file_id)
            if entry is None:
                return None
            return dict(entry)

    def get_session_entries(self, session_id: str) -> dict[str, dict]:
        """Return shallow copies of all entries owned by a session.
        返回指定 session 拥有的所有条目的浅拷贝。
        """
        with self._lock:
            return {
                file_id: dict(entry)
                for file_id, entry in self._registry.items()
                if entry.get("session_id") == session_id
            }

    def cleanup_expired(self) -> int:
        """删除所有已过期条目及磁盘文件，返回清理数量。"""
        now = time.time()
        with self._lock:
            expired_ids = [
                fid
                for fid, entry in self._registry.items()
                if entry.get("expires_at") is not None and now >= entry["expires_at"]
            ]
        return self._cleanup_entries(expired_ids)

    def cleanup_session(self, session_id: str) -> int:
        """Clean up all registered files for a session and delete from disk.
        清理指定 session 的所有注册文件并删除磁盘文件，返回清理数量。
        """
        with self._lock:
            file_ids = [
                fid for fid, entry in self._registry.items() if entry["session_id"] == session_id
            ]
        return self._cleanup_entries(file_ids, expire_failed_session_bound=True)

    def cleanup_session_except(self, session_id: str, keep_file_ids: set[str] | None = None) -> int:
        """Delete all registered files for a session except those in *keep_file_ids*.
        删除指定 session 的注册文件（保留 keep_file_ids 中的），返回清理数量。
        """
        if keep_file_ids is None:
            keep_file_ids = set()
        with self._lock:
            file_ids = [
                fid
                for fid, entry in self._registry.items()
                if entry["session_id"] == session_id and fid not in keep_file_ids
            ]
        return self._cleanup_entries(file_ids, expire_failed_session_bound=True)

    def cleanup_file(self, file_id: str) -> int:
        """Clean up one registered file and delete it from disk.
        清理单个注册文件并删除磁盘文件。
        """
        return self._cleanup_entries([file_id], expire_failed_session_bound=True)

    def clear_all(self) -> int:
        """清除所有注册文件并删除磁盘文件，返回清理数量。"""
        with self._lock:
            file_ids = list(self._registry.keys())
        return self._cleanup_entries(file_ids)

    def _cleanup_entries(
        self,
        file_ids: list[str],
        expire_failed_session_bound: bool = False,
    ) -> int:
        """Delete registry entries in two phases so filesystem I/O stays outside the lock.
        两阶段删除 registry 条目，将文件系统 I/O 移到锁外。
        """
        snapshots: list[tuple[str, str, bool]] = []
        with self._lock:
            for file_id in file_ids:
                entry = self._registry.get(file_id)
                if entry is None:
                    continue
                path = entry.get("path")
                if not path:
                    self._registry.pop(file_id, None)
                    continue
                delete_on_cleanup = bool(entry.get("delete_on_cleanup", True))
                snapshots.append((file_id, path, delete_on_cleanup))

        outcomes = [
            (file_id, path, True if not delete_on_cleanup else self._delete_path(path))
            for file_id, path, delete_on_cleanup in snapshots
        ]

        removed = 0
        with self._lock:
            for file_id, path, cleaned in outcomes:
                current = self._registry.get(file_id)
                if current is None or current.get("path") != path:
                    continue
                if cleaned:
                    self._registry.pop(file_id, None)
                    removed += 1
                    continue
                if expire_failed_session_bound and current.get("lifecycle") == "session_bound":
                    current["expires_at"] = time.time()
        return removed

    def _should_delete_path(self, path: str) -> bool:
        try:
            resolved_path = os.path.realpath(path)
            materials_root = os.path.realpath(MATERIALS_DIR)
            return os.path.commonpath([resolved_path, materials_root]) != materials_root
        except (ValueError, OSError):
            return True

    def _delete_path(self, path: str) -> bool:
        """Delete one path outside the registry lock.
        在 registry 锁外删除单个路径。
        """
        if not os.path.exists(path):
            return True

        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except (PermissionError, OSError):
            return not os.path.exists(path)
