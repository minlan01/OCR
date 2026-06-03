"""
图像增强器单元测试
覆盖 ImageEnhancer（去噪/二值化/黑边裁剪）和 Deskewer（倾斜校正）
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from services.preprocessor.image_enhancer import ImageEnhancer, Deskewer

# 使用项目目录避免 Windows 沙箱 temp 权限问题
TEST_OUT_DIR = Path("E:/OCRScanStruct/scan_output")


# ── Helpers ────────────────────────────────────────────────

def _make_test_image(w=200, h=100):
    """创建白色背景的BGR测试图像"""
    return np.ones((h, w, 3), dtype=np.uint8) * 255


def _make_test_image_with_black_border(w=200, h=100, border=20):
    """创建带黑边的BGR测试图像"""
    img = _make_test_image(w, h)
    img[:border, :] = 0
    img[-border:, :] = 0
    img[:, :border] = 0
    img[:, -border:] = 0
    return img


def _ensure_test_dir():
    TEST_OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── ImageEnhancer 基础 ─────────────────────────────────────

class TestImageEnhancerInit:
    def test_default_settings(self):
        enhancer = ImageEnhancer()
        assert enhancer.denoise is True
        assert enhancer.binary is False
        assert enhancer.crop_border is True

    def test_custom_settings(self):
        enhancer = ImageEnhancer(denoise=False, binary=True, crop_border=False)
        assert enhancer.denoise is False
        assert enhancer.binary is True
        assert enhancer.crop_border is False


# ── ImageEnhancer.enhance ──────────────────────────────────

class TestImageEnhancerEnhance:
    def test_enhance_basic(self):
        """基本增强流程 — 灰度化 + 去噪"""
        import cv2
        _ensure_test_dir()
        input_path = TEST_OUT_DIR / "_test_enhance_input.png"
        output_path = TEST_OUT_DIR / "_test_enhance_output.png"
        try:
            img = _make_test_image()
            cv2.imwrite(str(input_path), img)

            enhancer = ImageEnhancer(denoise=True, binary=False, crop_border=False)
            result = enhancer.enhance(input_path, output_path)

            assert result == output_path
            assert output_path.exists()
            loaded = cv2.imread(str(output_path), cv2.IMREAD_GRAYSCALE)
            assert loaded is not None
        finally:
            for p in [input_path, output_path]:
                if p.exists():
                    os.remove(p)

    def test_enhance_with_binarization(self):
        """启用二值化"""
        import cv2
        _ensure_test_dir()
        input_path = TEST_OUT_DIR / "_test_bin_input.png"
        output_path = TEST_OUT_DIR / "_test_bin_output.png"
        try:
            img = _make_test_image()
            cv2.imwrite(str(input_path), img)

            enhancer = ImageEnhancer(denoise=False, binary=True, crop_border=False)
            result = enhancer.enhance(input_path, output_path)

            assert output_path.exists()
            loaded = cv2.imread(str(output_path), cv2.IMREAD_GRAYSCALE)
            unique_vals = np.unique(loaded)
            assert all(v in (0, 255) for v in unique_vals)
        finally:
            for p in [input_path, output_path]:
                if p.exists():
                    os.remove(p)

    def test_enhance_with_crop(self):
        """黑边裁剪"""
        import cv2
        _ensure_test_dir()
        input_path = TEST_OUT_DIR / "_test_crop_input.png"
        output_path = TEST_OUT_DIR / "_test_crop_output.png"
        try:
            img = _make_test_image_with_black_border(w=200, h=100, border=20)
            cv2.imwrite(str(input_path), img)

            enhancer = ImageEnhancer(denoise=False, binary=False, crop_border=True)
            result = enhancer.enhance(input_path, output_path)

            loaded = cv2.imread(str(output_path))
            assert loaded.shape[0] < 100 or loaded.shape[1] < 200
        finally:
            for p in [input_path, output_path]:
                if p.exists():
                    os.remove(p)

    def test_enhance_invalid_image(self):
        """无效图像文件 — 返回原路径"""
        _ensure_test_dir()
        bad_path = TEST_OUT_DIR / "_test_bad.png"
        out_path = TEST_OUT_DIR / "_test_bad_out.png"
        try:
            bad_path.write_text("not an image", encoding="utf-8")
            enhancer = ImageEnhancer()
            result = enhancer.enhance(bad_path, out_path)
            assert result == bad_path
        finally:
            for p in [bad_path, out_path]:
                if p.exists():
                    os.remove(p)

    def test_enhance_already_grayscale(self):
        """已为灰度图的输入"""
        import cv2
        _ensure_test_dir()
        input_path = TEST_OUT_DIR / "_test_gray_input.png"
        output_path = TEST_OUT_DIR / "_test_gray_output.png"
        try:
            gray = np.ones((100, 200), dtype=np.uint8) * 200
            cv2.imwrite(str(input_path), gray)

            enhancer = ImageEnhancer(denoise=True, binary=False, crop_border=False)
            result = enhancer.enhance(input_path, output_path)
            assert output_path.exists()
        finally:
            for p in [input_path, output_path]:
                if p.exists():
                    os.remove(p)


# ── ImageEnhancer._crop_black_border ───────────────────────

class TestCropBlackBorder:
    def test_crop_reduces_size(self):
        img = _make_test_image_with_black_border(w=200, h=100, border=15)
        enhancer = ImageEnhancer(crop_border=True)
        cropped = enhancer._crop_black_border(img)
        assert cropped.shape[0] < img.shape[0] or cropped.shape[1] < img.shape[1]

    def test_crop_all_black_returns_original(self):
        """全黑图不裁剪"""
        black = np.zeros((100, 200), dtype=np.uint8)
        enhancer = ImageEnhancer(crop_border=True)
        result = enhancer._crop_black_border(black)
        np.testing.assert_array_equal(result, black)

    def test_crop_no_border_preserves_size(self):
        img = _make_test_image()
        enhancer = ImageEnhancer(crop_border=True)
        cropped = enhancer._crop_black_border(img)
        assert abs(cropped.shape[0] - img.shape[0]) <= 4
        assert abs(cropped.shape[1] - img.shape[1]) <= 4


# ── Deskewer ───────────────────────────────────────────────

class TestDeskewer:
    def test_deskew_small_angle_skips(self):
        """倾斜<0.3°时跳过校正，返回原图路径"""
        import cv2
        _ensure_test_dir()
        input_path = TEST_OUT_DIR / "_test_deskew_input.png"
        output_path = TEST_OUT_DIR / "_test_deskew_output.png"
        try:
            img = _make_test_image(200, 100)
            cv2.imwrite(str(input_path), img)

            deskewer = Deskewer()
            result = deskewer.deskew(input_path, output_path)
            # 小角度跳过校正，返回原图路径
            assert result == input_path
        finally:
            for p in [input_path, output_path]:
                if p.exists():
                    os.remove(p)

    def test_deskew_rotated_image(self):
        """有倾斜的图像应被校正"""
        import cv2
        _ensure_test_dir()
        input_path = TEST_OUT_DIR / "_test_tilted_input.png"
        output_path = TEST_OUT_DIR / "_test_tilted_output.png"
        try:
            img = np.ones((200, 300), dtype=np.uint8) * 255
            center = (150, 100)
            for length in range(0, 100):
                x = int(center[0] + length * 0.985)
                y = int(center[1] + length * 0.174)
                if 0 <= x < 300 and 0 <= y < 200:
                    img[y, x] = 0

            cv2.imwrite(str(input_path), img)

            deskewer = Deskewer()
            result = deskewer.deskew(input_path, output_path)
            assert result == output_path
            assert output_path.exists()
        finally:
            for p in [input_path, output_path]:
                if p.exists():
                    os.remove(p)

    def test_deskew_invalid_image_returns_original(self):
        """无效图像 → 返回原路径"""
        _ensure_test_dir()
        bad_path = TEST_OUT_DIR / "_test_bad_deskew.png"
        out_path = TEST_OUT_DIR / "_test_bad_deskew_out.png"
        try:
            bad_path.write_text("invalid", encoding="utf-8")

            deskewer = Deskewer()
            result = deskewer.deskew(bad_path, out_path)
            assert result == bad_path
        finally:
            for p in [bad_path, out_path]:
                if p.exists():
                    os.remove(p)
