"""
图像增强器
去噪、二值化、黑边裁剪、倾斜校正、自适应缩放、CLAHE对比度增强、USM锐化
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from loguru import logger

from config.settings import settings


class ImageEnhancer:
    """
    图像预处理增强器

    执行黑边裁剪 → 自适应缩放 → CLAHE对比度增强 → 快速去噪 → OTSU+形态学二值化 → USM锐化，
    提升OCR识别精度并大幅降低预处理耗时。

    Args:
        denoise: 是否启用去噪（默认 True，使用 medianBlur 替代 fastNlMeansDenoising）
        binary: 是否启用 OTSU 二值化 + 形态学去噪点（默认 True）
        crop_border: 是否裁剪黑边（默认 True）
        target_short_side: 短边归一化目标像素，0=不缩放（默认 1600）
        clahe_clip: CLAHE 对比度限制，0=不做 CLAHE（默认 2.0）
        sharpen: 是否做 USM 锐化（默认 True，二值化图自动跳过）
        morph_clean: 是否做形态学去噪点（开运算，默认 True）
    """

    def __init__(
        self,
        denoise: bool = True,
        binary: bool = True,
        crop_border: bool = True,
        target_short_side: int = 1600,
        clahe_clip: float = 2.0,
        sharpen: bool = True,
        morph_clean: bool = True,
    ):
        """
        初始化增强器

        Args:
            denoise: 是否启用去噪（默认 True）
            binary: 是否启用 OTSU 二值化 + 形态学去噪点（默认 True）
            crop_border: 是否裁剪黑边（默认 True）
            target_short_side: 短边归一化目标像素，0=不缩放（默认 1600）
            clahe_clip: CLAHE 对比度限制，0=不做 CLAHE（默认 2.0）
            sharpen: 是否做 USM 锐化（默认 True）
            morph_clean: 是否做形态学去噪点（默认 True）
        """
        self.denoise = denoise
        self.binary = binary
        self.crop_border = crop_border
        self.target_short_side = target_short_side
        self.clahe_clip = clahe_clip
        self.sharpen = sharpen
        self.morph_clean = morph_clean

    def enhance(self, image_path: Path, output_path: Path) -> Path:
        """
        对单张图片执行增强处理

        处理流程: 黑边裁剪 → 灰度化 → 自适应缩放 → CLAHE对比度增强
                  → 快速去噪(medianBlur) → OTSU+形态学二值化 → USM锐化

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

        # 3. 自适应缩放
        if self.target_short_side > 0:
            old_shape = gray.shape
            gray = self._adaptive_resize(gray)
            if gray.shape != old_shape:
                logger.debug(f"Resized: {old_shape} -> {gray.shape}")

        # 4. CLAHE对比度增强
        if self.clahe_clip > 0:
            clahe = cv2.createCLAHE(clipLimit=self.clahe_clip, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            logger.debug(f"CLAHE applied: clipLimit={self.clahe_clip}")

        # 5. 快速去噪（中值滤波替代fastNlMeansDenoising）
        if self.denoise:
            gray = cv2.medianBlur(gray, 3)
            logger.debug("Denoised (medianBlur k=3)")

        # 6. OTSU二值化 + 形态学去噪点
        if self.binary:
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            logger.debug("Binarized (OTSU)")
            if self.morph_clean:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
                gray = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
                logger.debug("Morphological clean (open)")

        # 7. USM锐化（二值化图不需要锐化）
        if self.sharpen and not self.binary:
            gray = self._unsharp_mask(gray)
            logger.debug("USM sharpened")

        cv2.imwrite(str(output_path), gray)
        return output_path

    def _adaptive_resize(self, gray: np.ndarray) -> np.ndarray:
        """
        自适应缩放：短边归一化到 target_short_side

        只在差异超过20%时才缩放（避免无意义的重采样）。
        缩小时使用 INTER_AREA（抗锯齿），放大时使用 INTER_CUBIC（平滑插值）。

        Args:
            gray: 输入灰度图

        Returns:
            缩放后的灰度图（若无需缩放则原样返回）
        """
        import cv2

        h, w = gray.shape
        short = min(h, w)
        if short == 0:
            return gray
        # 只在差异超过20%时才缩放（避免无意义的重采样）
        ratio = self.target_short_side / short
        if 0.83 < ratio < 1.2:  # 约 ±20% 内不缩放
            return gray
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        interp = cv2.INTER_AREA if ratio < 1 else cv2.INTER_CUBIC
        return cv2.resize(gray, (new_w, new_h), interpolation=interp)

    def _unsharp_mask(
        self, gray: np.ndarray, amount: float = 1.0, sigma: float = 1.0
    ) -> np.ndarray:
        """
        USM锐化：原图 + amount*(原图-高斯模糊)

        通过从原图中减去高斯模糊的版本来增强边缘细节。
        适用于非二值化的灰度图，可提升模糊文字的清晰度。

        Args:
            gray: 输入灰度图
            amount: 锐化强度（默认 1.0）
            sigma: 高斯模糊核标准差（默认 1.0）

        Returns:
            锐化后的灰度图
        """
        import cv2

        blurred = cv2.GaussianBlur(gray, (0, 0), sigma)
        sharpened = cv2.addWeighted(gray, 1.0 + amount, blurred, -amount, 0)
        return sharpened

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
