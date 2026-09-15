"""Portable ownership of material workers, including abrupt parent exit."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import time

import psutil


def _process_alive(pid: int, created: float) -> bool:
    try:
        process = psutil.Process(pid)
        return process.create_time() == created and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return psutil.pid_exists(pid)


def _remove_owned_directory(path: Path, parent: Path, prefix: str) -> None:
    # Only private direct children of the original temporary root are owned.
    if (path.parent.resolve() != parent.resolve() or not path.name.startswith(prefix)
            or path.is_symlink() or getattr(path, "is_junction", lambda: False)()):
        return
    shutil.rmtree(path, ignore_errors=True)


def _clean_abandoned_work(directory: Path) -> None:
    processes = []
    for record in directory.glob("child-*.json"):
        try:
            identity = json.loads(record.read_text(encoding="utf-8"))
            process = psutil.Process(identity["pid"])
            if process.create_time() == identity["created"]:
                process.kill()
                processes.append(process)
        except (OSError, ValueError, psutil.Error):
            continue
    _gone, alive = psutil.wait_procs(processes, timeout=5)
    if any(_process_alive(p.pid, p.create_time()) for p in alive):
        return
    data_record = directory / "data-directory"
    if data_record.exists():
        name = data_record.read_text(encoding="utf-8")
        if Path(name).name == name:
            _remove_owned_directory(directory.parent / name, directory.parent, "lumina-vector-material-")
    _remove_owned_directory(directory, directory.parent, "lumina-material-owner-")


def _watch_parent(directory_path: str, parent_pid: int, created: float) -> None:
    directory = Path(directory_path)
    (directory / "ready").touch()
    while _process_alive(parent_pid, created):
        if (directory / "stop").exists():
            (directory / "cpu.json").write_text(str(time.process_time()), encoding="utf-8")
            return
        time.sleep(0.1)
    _clean_abandoned_work(directory)


class MaterialProcessLifetime:
    """Own material workers with an independent portable parent monitor.

    用独立的跨平台监控进程管理材质子进程，父进程退出后终止遗留计算。
    """

    def __init__(self) -> None:
        self.name: str | None = None
        self.cpu_seconds = 0.0
        self._directory: tempfile.TemporaryDirectory | None = None
        self._monitor: multiprocessing.Process | None = None

    def open(self) -> None:
        """Start ownership monitoring before any material worker is created.
        在创建任何材质计算进程前启动生命周期监控。
        """
        self._directory = tempfile.TemporaryDirectory(prefix="lumina-material-owner-")
        self.name = self._directory.name
        directory = Path(self.name)
        created = psutil.Process().create_time()
        (directory / "owner.json").write_text(
            json.dumps({"pid": os.getpid(), "created": created}), encoding="utf-8",
        )
        self._monitor = multiprocessing.get_context("spawn").Process(
            target=_watch_parent, args=(self.name, os.getpid(), created), daemon=True,
        )
        try:
            self._monitor.start()
            deadline = time.monotonic() + 10
            while not (directory / "ready").exists():
                if not self._monitor.is_alive() or time.monotonic() >= deadline:
                    raise OSError("Cannot start material process ownership monitor")
                time.sleep(0.02)
        except BaseException:
            self.close()
            raise

    def track_data_directory(self, path: str) -> None:
        """Register private transport files for cleanup after abrupt parent exit.
        登记私有传输目录，在父进程异常退出后清理。
        """
        directory, data = Path(self.name), Path(path)
        if data.parent.resolve() != directory.parent.resolve() or not data.name.startswith("lumina-vector-material-"):
            raise ValueError("Material transport directory must be a private temporary sibling")
        (directory / "data-directory").write_text(data.name, encoding="utf-8")

    def close(self) -> None:
        """Stop the monitor after owned workers have exited and release files.
        等计算子进程退出后停止监控，并释放私有文件。
        """
        if self._directory is None:
            return
        directory = Path(self._directory.name)
        (directory / "stop").touch(exist_ok=True)
        if self._monitor is not None and self._monitor.pid is not None:
            self._monitor.join(timeout=5)
            if self._monitor.is_alive():
                self._monitor.kill()
                self._monitor.join(timeout=5)
            self._monitor.close()
        cpu = directory / "cpu.json"
        if cpu.exists():
            self.cpu_seconds = float(cpu.read_text(encoding="utf-8"))
        self._directory.cleanup()
        self._directory, self._monitor = None, None


def attach_material_worker(job_name: str | None, parent_pid: int) -> None:
    """Register this worker with the independent parent monitor.

    向独立监控进程登记当前子进程，并确认父进程仍然存活。

    Args:
        job_name: Private ownership directory. 私有生命周期目录。
        parent_pid: Expected parent process ID. 预期父进程编号。
    """
    directory = Path(job_name)
    owner = json.loads((directory / "owner.json").read_text(encoding="utf-8"))
    if owner["pid"] != parent_pid or not _process_alive(parent_pid, owner["created"]):
        raise RuntimeError("Material worker parent already exited")
    process = psutil.Process()
    record = directory / f"child-{process.pid}.json"
    temporary = record.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"pid": process.pid, "created": process.create_time()}), encoding="utf-8",
    )
    temporary.replace(record)
    if not _process_alive(parent_pid, owner["created"]):
        raise RuntimeError("Material worker parent exited during registration")
