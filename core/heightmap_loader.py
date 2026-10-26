"""
Lumina Studio - 高度图加载与处理模块 (Heightmap Loader)

负责加载灰度高度图并将其转换为可用于 3D 模型生成的高度矩阵。
灰度值映射规则：黑色(0) = 最低底板厚度，白色(255) = 最高浮雕高度。
"""

import numpy as np
import cv2
from PIL import Image as PILImage
from api.structured_logging import get_logger

# HEIC/HEIF support (optional dependency)
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

log = get_logger(__name__)


class HeightmapLoader:
    """高度图加载与处理器。"""

    # 缩略图最大尺寸
    THUMBNAIL_MAX_SIZE = 200

    @staticmethod
    def _to_grayscale(image: np.ndarray) -> np.ndarray:
        """将输入图像转换为灰度图。

        Args:
            image: np.ndarray 格式的输入图像，支持灰度(H,W)、RGB (H,W,3) 或 RGBA (H,W,4)

        Returns:
            np.ndarray: (H, W) uint8 灰度图
        """
        # 已是灰度图，保留灰度数据
        if image.ndim == 2:
            gray = image
        elif image.shape[2] == 4:
            # RGBA → BGR → 灰度
            bgr = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        elif image.shape[2] == 3:
            # cv2.imread 默认加载为 BGR 格式，直接转灰度
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            # 其他通道数，取第一个通道
            gray = image[:, :, 0]

        # Preserve absolute brightness: casting uint16 directly wraps every 256.
        # Use the full encoding range, never the individual image's min/max.
        if gray.dtype == np.uint16:
            gray = np.rint(gray.astype(np.float32) / 257.0)
        return gray.astype(np.uint8)

    @staticmethod
    def _resize_to_target(grayscale: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        """将灰度图缩放到目标尺寸。

        Args:
            grayscale: (H, W) uint8 灰度图
            target_w: 目标宽度（像素）
            target_h: 目标高度（像素）

        Returns:
            np.ndarray: (target_h, target_w) uint8 缩放后的灰度图
        """
        orig_h, orig_w = grayscale.shape[:2]
        resized = cv2.resize(grayscale, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        log.debug(
            "Heightmap resized",
            extra={
                "event": "heightmap_resized",
                "source_width": orig_w,
                "source_height": orig_h,
                "target_width": target_w,
                "target_height": target_h,
            },
        )
        return resized.astype(np.uint8)

    @staticmethod
    def _map_grayscale_to_height(grayscale: np.ndarray, max_relief_height: float, base_thickness: float) -> np.ndarray:
        """将灰度值映射为高度值，使用 NumPy 向量化运算。

        公式: height_mm = base_thickness + (grayscale / 255.0) * (max_relief_height - base_thickness)
        黑色(0) → base_thickness（最低点）
        白色(255) → max_relief_height（最高点）

        Args:
            grayscale: (H, W) uint8 灰度图
            max_relief_height: 最大浮雕高度（mm）
            base_thickness: 底板最小厚度（mm）

        Returns:
            np.ndarray: (H, W) float32 高度值，单位 mm
        """
        height_mm = base_thickness + (grayscale.astype(np.float32) / 255.0) * (
            max_relief_height - base_thickness
        )
        return height_mm.astype(np.float32)

    @staticmethod
    def _check_aspect_ratio(heightmap_w: int, heightmap_h: int, target_w: int, target_h: int) -> str | None:
        """检查高度图与目标尺寸的宽高比偏差。

        偏差计算: |w1/h1 - w2/h2| / (w2/h2)
        偏差超过 20% 时返回警告信息，否则返回 None。
        """
        if heightmap_h == 0 or target_h == 0:
            return "[WARNING] ⚠️ Invalid dimensions: height cannot be zero for aspect-ratio check."

        hm_ratio = heightmap_w / heightmap_h
        target_ratio = target_w / target_h
        deviation = abs(hm_ratio - target_ratio) / target_ratio

        if deviation > 0.2:
            return (
                f"⚠️ Aspect ratio deviation is {deviation:.0%}; this may distort relief details "
                f"(heightmap: {heightmap_w}x{heightmap_h}, target: {target_w}x{target_h})."
            )
        return None

    @staticmethod
    def _check_contrast(grayscale: np.ndarray) -> str | None:
        """检查灰度图对比度是否过低。

        标准差小于 1.0 时发出警告，提示浮雕效果可能较弱。
        """
        std_val = float(np.std(grayscale))
        if std_val < 1.0:
            return f"[WARNING] Heightmap contrast is very low (std={std_val:.2f}); relief effect may be weak."
        return None

    @staticmethod
    def load_and_validate(heightmap_path: str) -> dict:
        """Load and validate a heightmap, including a nonempty thumbnail.
        加载并验证高度图文件，生成非空缩略图。

        Args:
            heightmap_path: Original image path. (高度图原始文件路径。)

        Returns:
            dict: {
                'success': bool,
                'grayscale': np.ndarray (H, W) uint8 或 None,
                'original_size': (w, h) 或 None,
                'thumbnail': np.ndarray 或 None,  # 用于 UI 缩略显示
                'warnings': list[str],
                'error': str 或 None
            }
        """
        warnings_list = []

        # 使用 np.fromfile 读取文件以支持中文路径
        try:
            img_data = np.fromfile(heightmap_path, dtype=np.uint8)
            image = cv2.imdecode(img_data, cv2.IMREAD_UNCHANGED)
        except (OSError, ValueError, cv2.error) as e:
            return {
                "success": False,
                "grayscale": None,
                "original_size": None,
                "thumbnail": None,
                "warnings": [],
                "error": f"无法读取高度图文件: {heightmap_path} ({e})",
            }

        # Fallback: cv2 can't decode HEIC/HEIF, use Pillow instead
        if image is None:
            try:
                pil_img = PILImage.open(heightmap_path)
                image = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
            except (OSError, ValueError, TypeError):
                pass

        if image is None:
            return {
                "success": False,
                "grayscale": None,
                "original_size": None,
                "thumbnail": None,
                "warnings": [],
                "error": f"无法读取高度图文件: {heightmap_path}",
            }

        orig_h, orig_w = image.shape[:2]
        log.debug(
            "Heightmap image decoded",
            extra={
                "event": "heightmap_image_decoded",
                "image_width": orig_w,
                "image_height": orig_h,
            },
        )

        # 转换为灰度图
        grayscale = HeightmapLoader._to_grayscale(image)

        # 生成缩略图用于前端预览（最大 200x200）
        max_dim = max(orig_h, orig_w)
        if max_dim > HeightmapLoader.THUMBNAIL_MAX_SIZE:
            scale = HeightmapLoader.THUMBNAIL_MAX_SIZE / max_dim
            thumb_w = max(1, int(orig_w * scale))
            thumb_h = max(1, int(orig_h * scale))
            thumbnail = cv2.resize(grayscale, (thumb_w, thumb_h), interpolation=cv2.INTER_LINEAR)
        else:
            thumbnail = grayscale.copy()

        return {
            "success": True,
            "grayscale": grayscale,
            "original_size": (orig_w, orig_h),
            "thumbnail": thumbnail,
            "warnings": warnings_list,
            "error": None,
        }

    @staticmethod
    def load_and_process(
        heightmap_path: str, target_w: int, target_h: int, max_relief_height: float, base_thickness: float
    ) -> dict:
        """加载图像并处理为 Height_Matrix。

        完整流程：加载 → 验证 → 灰度转换 → 宽高比检查 → 缩放 → 对比度检查 → 高度映射。

        Args:
            heightmap_path: 高度图文件路径。
            target_w: 目标宽度（像素）
            target_h: 目标高度（像素）
            max_relief_height: 最大浮雕高度（mm）
            base_thickness: 底板最小厚度（mm）

        Returns:
            dict: {
                'success': bool,
                'height_matrix': np.ndarray (H, W) float32 高度值 mm 或 None,
                'stats': {'min_mm': float, 'max_mm': float, 'avg_mm': float} 或 None,
                'warnings': list[str],
                'error': str 或 None
            }
        """
        warnings_list = []

        # Step 1: 加载并验证
        validate_result = HeightmapLoader.load_and_validate(heightmap_path)
        if not validate_result["success"]:
            return {
                "success": False,
                "height_matrix": None,
                "stats": None,
                "warnings": validate_result["warnings"],
                "error": validate_result["error"],
            }

        grayscale = validate_result["grayscale"]
        orig_w, orig_h = validate_result["original_size"]
        warnings_list.extend(validate_result["warnings"])

        # Step 2: 宽高比检查
        ar_warning = HeightmapLoader._check_aspect_ratio(orig_w, orig_h, target_w, target_h)
        if ar_warning:
            warnings_list.append(ar_warning)

        # Step 3: 缩放到目标尺寸
        grayscale = HeightmapLoader._resize_to_target(grayscale, target_w, target_h)

        # Step 4: 对比度检查
        contrast_warning = HeightmapLoader._check_contrast(grayscale)
        if contrast_warning:
            warnings_list.append(contrast_warning)

        # Step 5: 参数范围校验
        if max_relief_height < base_thickness:
            warnings_list.append(
                f"WARNING: max_relief_height ({max_relief_height}mm) < base_thickness ({base_thickness}mm), "
                f"clamping to base_thickness"
            )
            max_relief_height = base_thickness

        # Step 6: 灰度值映射为高度矩阵
        height_matrix = HeightmapLoader._map_grayscale_to_height(grayscale, max_relief_height, base_thickness)

        # Step 7: 统计高度信息
        stats = {
            "min_mm": float(np.min(height_matrix)),
            "max_mm": float(np.max(height_matrix)),
            "avg_mm": float(np.mean(height_matrix)),
        }

        log.info(
            f"高度图映射完成: "
            f"min={stats['min_mm']:.2f}mm, max={stats['max_mm']:.2f}mm, avg={stats['avg_mm']:.2f}mm"
        )

        return {
            "success": True,
            "height_matrix": height_matrix,
            "stats": stats,
            "warnings": warnings_list,
            "error": None,
        }
