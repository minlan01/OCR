"""
图像增强器
去噪、二值化、黑边裁剪、倾斜校正
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from loguru import logger

from config.settings import settings


class ImageEnhancer:
    """
    图像预处理增强器

    执行去噪、二值化、黑边裁剪等预处理操作，提升 OCR 识别精度。

    Args:
        denoise: 是否启用去噪（默认 True）
        binary: 是否启用手动二值化（默认 False，PaddleOCR 自带二值化）
        crop_border: 是否裁剪黑边（默认 True）
    """

    def __init__(
        self,
        denoise: bool = True,
        binary: bool = False,
        crop_border: bool = True,
    ):
        """
        初始化增强器

        Args:
            denoise: 是否启用去噪（默认 True）
            binary: 是否启用手动二值化（默认 False，PaddleOCR 自带二值化）
            crop_border: 是否裁剪黑边（默认 True）
        """
        self.denoise = denoise
        self.binary = binary
        self.crop_border = crop_border

    def enhance(self, image_path: Path, output_path: Path) -> Path:
        """
        对单张图片执行增强处理

        处理流程: 黑边裁剪 → 灰度化 → 去噪 → 二值化(可选)

        Args:
            image_path: 输入图片路径
            output_path: 输出图片路径

        Returns:
            增强后的图片路径
        """
        import cv2

        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Failed to load image: {image_path}")
            return image_path

        original_shape = img.shape

        # 1. 黑边裁剪
        if self.crop_border:
            img = self._crop_black_border(img)
            logger.debug(f"Cropped: {original_shape} -> {img.shape}")

        # 2. 灰度化
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # 3. 去噪
        if self.denoise:
            gray = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
            logger.debug("Denoised")

        # 4. 二值化（可选，默认不做）
        if self.binary:
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            logger.debug("Binarized (OTSU)")

        cv2.imwrite(str(output_path), gray)
        return output_path

    def _crop_black_border(self, img: np.ndarray) -> np.ndarray:
        """
        裁剪图像黑边

        通过二值化检测非黑区域，保留内容区域并添加 2% 边距。

        Args:
            img: 输入图像（BGR 或灰度）

        Returns:
            裁剪后的图像（全黑图则原样返回）
        """
        import cv2

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # 二值化找边界
        _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)

        # 找非黑区域
        coords = cv2.findNonZero(thresh)
        if coords is None:
            return img  # 全黑图，不裁剪

        x, y, w, h = cv2.boundingRect(coords)

        # 留 2% 边距
        margin_x = int(w * 0.02)
        margin_y = int(h * 0.02)
        x = max(0, x - margin_x)
        y = max(0, y - margin_y)
        w = min(img.shape[1] - x, w + 2 * margin_x)
        h = min(img.shape[0] - y, h + 2 * margin_y)

        return img[y:y+h, x:x+w]


class Deskewer:
    """
    倾斜校正器

    通过最小外接矩形检测文本倾斜角度，旋转校正图片。
    倾斜小于 0.3° 时跳过处理以避免质量损失。
    """

    def deskew(self, image_path: Path, output_path: Path) -> Path:
        """
        检测并校正图片倾斜

        Args:
            image_path: 输入图片路径
            output_path: 输出图片路径

        Returns:
            校正后的图片路径（倾斜 < 0.3° 时返回原图）
        """
        import cv2

        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return image_path

        # 二值化
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 找所有非零点
        coords = np.column_stack(np.where(binary > 0))
        if len(coords) == 0:
            return image_path

        # 最小外接矩形
        rect = cv2.minAreaRect(coords.astype(np.float32))
        angle = rect[2]

        # 调整角度
        if angle < -45:
            angle = 90 + angle

        if abs(angle) < 0.3:
            # 倾斜小于 0.3 度，不处理
            cv2.imwrite(str(output_path), img)
            return output_path

        # 旋转校正
        h, w = img.shape
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            img, matrix, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

        cv2.imwrite(str(output_path), rotated)
        logger.debug(f"Deskewed: angle={angle:.1f}°")
        return output_path
