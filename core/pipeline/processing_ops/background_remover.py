"""
背景移除模块（Background Remover）

仅基于 alpha 透明度判定实体掩码。早期版本支持基于像素颜色的自动背景检测
（auto_bg + bg_tol），该路径已下线，参数同步移除以减少功能面与误用。

Background removal based purely on alpha transparency. The legacy
auto-background-color heuristic (auto_bg + bg_tol) has been retired and
its parameters were dropped to shrink the surface and avoid misuse.
"""

import numpy as np


def remove_background(alpha_arr: np.ndarray, rgb_arr: np.ndarray) -> np.ndarray:
    """基于 alpha 透明度返回实体掩码。
    Return the solid (non-transparent) mask using only alpha.

    Args:
        alpha_arr: (H, W) uint8 alpha 通道数组
        rgb_arr: (H, W, 3) uint8 RGB 图像数组（保留入参以兼容上层调用，
            目前未使用 / kept for upstream call-site compatibility, currently unused）

    Returns:
        (H, W) bool 实体掩码（mask_solid），True 表示非透明像素
    """
    del rgb_arr  # currently unused; kept in signature for stability
    mask_transparent = alpha_arr < 10
    mask_solid = ~mask_transparent
    return mask_solid
