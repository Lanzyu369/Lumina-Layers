#!/usr/bin/env python3
"""Review upstream ColorChecker changes for the local fork.

复核 ColorChecker 上游变更，辅助同步本地分叉。

Why this exists / 设计目的:
  ``core/colorchecker/`` is a **downstream fork** of
  ``git@github.com:lumina-layer-studio/ColorChecker.git`` (see
  ``core/colorchecker/UPSTREAM.md``). It is not a verbatim copy, so it cannot
  be updated with ``git pull`` or by overwriting files. Upstream ships a web
  app whose monolithic ``app.py`` we split into modules and then extended with
  features upstream does not have (auto-detection, orientation, strict
  pipeline, diagnostics, reference management).

  This CLI makes upstream updates reviewable instead of destructive. It:

  * clones upstream at the pinned commit and at a target ref into a temp dir
    **outside** the package tree,
  * reports, per tracked source file, whether upstream changed between the
    pinned commit and the target,
  * optionally prints the unified diffs so a human can port relevant bits by
    hand into the local modules,
  * advances the recorded pin in ``UPSTREAM.json`` only when explicitly asked.

  It never edits files under ``core/colorchecker/`` (except ``UPSTREAM.json``
  with ``--update-pin``), so the fork's local changes are always safe.

Usage / 用法::

    python scripts/sync_colorchecker_upstream.py --check
    python scripts/sync_colorchecker_upstream.py --show-diff
    python scripts/sync_colorchecker_upstream.py --target HEAD --show-diff
    python scripts/sync_colorchecker_upstream.py --update-pin <commit-or-HEAD>
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "core" / "colorchecker"
MANIFEST_PATH = PACKAGE_DIR / "UPSTREAM.json"


# ════════════════════════════════════════════════════════════════════
# Manifest helpers / 清单读写
# ════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Manifest:
    """Parsed ``UPSTREAM.json`` describing the upstream pin.

    解析后的 ``UPSTREAM.json``，记录上游来源与固定提交。
    """

    upstream_url: str
    pinned_commit: str
    tracked_files: list[str]
    raw: dict


def load_manifest() -> Manifest:
    """Load and validate ``UPSTREAM.json``.

    读取并校验 ``UPSTREAM.json``。
    """
    if not MANIFEST_PATH.is_file():
        raise SystemExit(f"[sync] manifest not found: {MANIFEST_PATH}")
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[sync] manifest is not valid JSON: {exc}") from exc

    url = data.get("upstream_url")
    pinned = data.get("pinned_commit")
    tracked = data.get("tracked_upstream_files")
    if not url or not pinned or not isinstance(tracked, list) or not tracked:
        raise SystemExit(
            "[sync] manifest must define upstream_url, pinned_commit, "
            "and a non-empty tracked_upstream_files list."
        )
    return Manifest(
        upstream_url=str(url),
        pinned_commit=str(pinned),
        tracked_files=[str(item) for item in tracked],
        raw=data,
    )


def write_pinned_commit(manifest: Manifest, commit: str, date: str) -> None:
    """Persist a new pinned commit + date into ``UPSTREAM.json``.

    将新的固定提交与日期写回 ``UPSTREAM.json``。
    """
    data = dict(manifest.raw)
    data["pinned_commit"] = commit
    data["pinned_date"] = date
    MANIFEST_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ════════════════════════════════════════════════════════════════════
# Git helpers / Git 帮助函数
# ════════════════════════════════════════════════════════════════════


def _run_git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout, raising on failure.

    执行 git 命令并返回标准输出，失败时抛出异常。
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(
            f"[sync] git {' '.join(args)} failed ({result.returncode}):\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout


def clone_upstream(url: str, dest: Path) -> None:
    """Clone the full upstream history into ``dest``.

    完整克隆上游仓库到 ``dest``（需要历史记录以便比较任意提交）。
    """
    print(f"[sync] cloning {url} ...", flush=True)
    result = subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(
            "[sync] failed to clone upstream. Check SSH access to "
            f"{url}.\n{result.stderr.strip()}"
        )


def resolve_commit(repo: Path, ref: str) -> tuple[str, str]:
    """Resolve a ref to ``(full_sha, iso_date)``.

    把引用解析为 ``(完整 sha, ISO 日期)``。
    """
    sha = _run_git(["rev-parse", ref], repo).strip()
    date = _run_git(
        ["show", "-s", "--format=%cd", "--date=short", sha], repo
    ).strip()
    return sha, date


def file_exists_at(repo: Path, commit: str, rel_path: str) -> bool:
    """Return whether ``rel_path`` exists in ``commit``.

    判断指定提交中是否存在该文件。
    """
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{rel_path}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def diff_between(repo: Path, base: str, target: str, rel_path: str) -> str:
    """Return the unified diff of ``rel_path`` between two commits.

    返回两个提交之间该文件的 unified diff（空字符串表示无变化）。
    """
    return _run_git(
        ["diff", f"{base}..{target}", "--", rel_path],
        repo,
    )


# ════════════════════════════════════════════════════════════════════
# Commands / 子命令
# ════════════════════════════════════════════════════════════════════


def _classify(repo: Path, base: str, target: str, rel_path: str) -> tuple[str, str]:
    """Classify a tracked file's change between base and target.

    分类某个被跟踪文件在 base→target 之间的变化，返回 ``(状态, diff)``。
    """
    in_base = file_exists_at(repo, base, rel_path)
    in_target = file_exists_at(repo, target, rel_path)
    if not in_base and not in_target:
        return "missing-both", ""
    if in_base and not in_target:
        return "removed-upstream", ""
    if not in_base and in_target:
        return "added-upstream", ""
    diff = diff_between(repo, base, target, rel_path)
    return ("unchanged" if not diff.strip() else "changed"), diff


def run_report(manifest: Manifest, target_ref: str, show_diff: bool) -> int:
    """Clone upstream and report per-file changes since the pin.

    克隆上游并报告自固定提交以来每个被跟踪文件的变化。
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="lumina_cc_upstream_"))
    repo = tmp_root / "ColorChecker"
    try:
        clone_upstream(manifest.upstream_url, repo)

        base_sha, base_date = resolve_commit(repo, manifest.pinned_commit)
        try:
            target_sha, target_date = resolve_commit(repo, target_ref)
        except SystemExit:
            raise SystemExit(
                f"[sync] cannot resolve target ref '{target_ref}' in upstream."
            )

        print()
        print(f"[sync] pinned : {base_sha[:12]}  ({base_date})")
        print(f"[sync] target : {target_sha[:12]}  ({target_date})")
        if base_sha == target_sha:
            print("[sync] target equals pinned commit — nothing to review.")
            return 0
        print(f"[sync] reviewing {len(manifest.tracked_files)} tracked file(s):")
        print()

        changed_any = False
        for rel_path in manifest.tracked_files:
            status, diff = _classify(repo, base_sha, target_sha, rel_path)
            print(f"  [{status:>16}]  {rel_path}")
            if status in {"changed", "added-upstream", "removed-upstream"}:
                changed_any = True
            if show_diff and diff.strip():
                print()
                for line in diff.splitlines():
                    print(f"      {line}")
                print()

        print()
        if changed_any:
            print(
                "[sync] upstream has changes in tracked files. Port relevant "
                "bits by hand into core/colorchecker/, then run the "
                "colorchecker tests and advance the pin with --update-pin."
            )
        else:
            print(
                "[sync] no tracked-file changes between pin and target. Safe "
                "to advance the pin with --update-pin if desired."
            )
        return 0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def run_update_pin(manifest: Manifest, target_ref: str) -> int:
    """Resolve ``target_ref`` upstream and record it as the new pin.

    解析上游的目标引用并写回为新的固定提交。
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="lumina_cc_upstream_"))
    repo = tmp_root / "ColorChecker"
    try:
        clone_upstream(manifest.upstream_url, repo)
        target_sha, target_date = resolve_commit(repo, target_ref)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if target_sha == manifest.pinned_commit:
        print(f"[sync] pin already at {target_sha[:12]} — no change.")
        return 0

    write_pinned_commit(manifest, target_sha, target_date)
    print(
        f"[sync] pin advanced: {manifest.pinned_commit[:12]} -> "
        f"{target_sha[:12]} ({target_date})"
    )
    print(
        "[sync] reminder: update the 'currently <sha>' note in "
        "core/colorchecker/UPSTREAM.md and re-run the colorchecker tests."
    )
    return 0


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Review upstream ColorChecker changes for the local fork. "
            "Read-only unless --update-pin is given."
        ),
    )
    parser.add_argument(
        "--target",
        default="HEAD",
        help="Upstream ref to compare against the pin (default: HEAD).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report per-file change status (default action).",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Print unified diffs for changed tracked files.",
    )
    parser.add_argument(
        "--update-pin",
        metavar="COMMIT_OR_REF",
        default=None,
        help="Advance the recorded pin in UPSTREAM.json to this upstream ref.",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest()

    if args.update_pin is not None:
        return run_update_pin(manifest, args.update_pin)

    # Default to a report when no explicit mode given.
    return run_report(manifest, args.target, show_diff=args.show_diff)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
