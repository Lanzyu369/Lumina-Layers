#!/usr/bin/env python3
"""Generate macOS icon assets from the project logo.

中文说明：把 ``logo.png`` 居中填到 1024x1024 透明正方形画布，再切出
所有 iconset 标准尺寸，最后用 macOS 自带 ``iconutil`` 打包成 ``icon.icns``，
并额外导出一份 ``icon.png`` 供 Electron 运行时窗口/Dock 使用。

This script is intentionally tiny and idempotent: 重跑会覆盖输出，原始 logo
不被修改。仅在 macOS 上有意义，因为它依赖 ``iconutil``。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
# 源选择优先级:
#   1) frontend/public/favicon.ico  — 网页左上角 / 浏览器标签上的彩色 L logo
#                                     (256x256 多分辨率 ICO,所有平台共用同一张图)
#   2) icon.ico                     — 仓库根的 ICO 副本(目前与上面是同一份文件)
#   3) logo.png                     — fallback,旧的方块 logo
SOURCE_CANDIDATES = [
    REPO_ROOT / "frontend" / "public" / "favicon.ico",
    REPO_ROOT / "icon.ico",
    REPO_ROOT / "logo.png",
]
OUTPUT_DIR = Path(__file__).resolve().parent
ICONSET_DIR = OUTPUT_DIR / "icon.iconset"
ICNS_PATH = OUTPUT_DIR / "icon.icns"
PNG_PATH = OUTPUT_DIR / "icon.png"

# Apple iconset 标准尺寸表：(实际像素, 文件名)
# 同一个尺寸需要 1x 和 2x 两份命名，sip 出来的图片像素是相同的。
ICONSET_ENTRIES: list[tuple[int, str]] = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]


def build_square_master(source: Path, size: int = 1024) -> Image.Image:
    """Produce a transparent ``size x size`` master from ``source``.

    For ICO inputs we pick the largest embedded frame; the chosen frame is then
    upscaled (or downscaled) to fit the target square so that the visible logo
    fills the canvas at the same proportion the source designer intended.

    Apple HIG recommends macOS app icons leave roughly a 10% margin and let the
    artwork occupy ~80% of the canvas. Our source favicon already bakes in safe
    padding (~60% width × 80% height of the 256 frame), so we resize the entire
    frame to ``size`` instead of pasting it at native resolution; this keeps the
    designer's safe-area choices and avoids the icon looking tiny in the Dock.
    """
    src = Image.open(source)

    if source.suffix.lower() == ".ico" and hasattr(src, "ico"):
        sizes = src.info.get("sizes") or set()
        if sizes:
            largest = max(sizes, key=lambda wh: wh[0] * wh[1])
            src.size = largest  # Pillow uses .size to choose ICO frame
            src.load()

    src = src.convert("RGBA")

    # Force the (already-square) source frame to ``size``; for non-square sources
    # fall back to thumbnail-then-paste so we don't squash the aspect ratio.
    if src.width == src.height:
        return src.resize((size, size), Image.Resampling.LANCZOS)

    src.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - src.width) // 2, (size - src.height) // 2)
    canvas.paste(src, offset, src)
    return canvas


def pick_source() -> Path | None:
    for cand in SOURCE_CANDIDATES:
        if cand.exists():
            return cand
    return None


def main() -> int:
    source = pick_source()
    if source is None:
        print(
            "[icon] no source logo found; tried: "
            + ", ".join(str(p) for p in SOURCE_CANDIDATES),
            file=sys.stderr,
        )
        return 1
    print(f"[icon] source = {source}")
    if shutil.which("iconutil") is None:
        print("[icon] iconutil not found; macOS only", file=sys.stderr)
        return 2

    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True)

    master = build_square_master(source, size=1024)

    # Emit one PNG per iconset slot.
    for px, name in ICONSET_ENTRIES:
        resized = master.resize((px, px), Image.Resampling.LANCZOS)
        resized.save(ICONSET_DIR / name, format="PNG")

    # Also emit a 512px PNG for runtime use (BrowserWindow.icon, app.dock.setIcon).
    master.resize((512, 512), Image.Resampling.LANCZOS).save(PNG_PATH, format="PNG")

    if ICNS_PATH.exists():
        ICNS_PATH.unlink()
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)],
        check=True,
    )

    # 打包完之后保留 .iconset 目录方便日后增改尺寸；占用很小，无需删除。
    print(f"[icon] wrote {ICNS_PATH}")
    print(f"[icon] wrote {PNG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
