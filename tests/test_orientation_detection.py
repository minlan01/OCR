"""
测试内容旋转检测逻辑
验证 _detect_orientation_by_content 对正确方向和旋转图片的判断
"""
import io
import sys
sys.path.insert(0, "E:/OCRScanStruct")

from PIL import Image as PILImage, ImageDraw, ImageFont
from services.evidence.pdf_generator import _detect_orientation_by_content


def create_test_image(text_lines: int, w: int, h: int) -> bytes:
    """创建包含模拟文字的测试图片（白底黑"字"）"""
    img = PILImage.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    line_height = h // (text_lines + 2)
    for i in range(text_lines):
        y = line_height * (i + 1)
        # 画模拟文字行（水平黑色条纹）
        for x in range(20, w - 20, 8):
            draw.rectangle([x, y, x + 4, y + 12], fill=(0, 0, 0))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test():
    print("=" * 60)
    print("测试内容旋转检测 (Content-Based Orientation Detection)")
    print("=" * 60)

    # 测试1: A4 竖版文档 — 尺寸正确，w < h，不应旋转
    print("\n[Test 1] 竖版 A4 (正确方向)")
    img_bytes = create_test_image(20, 595, 842)
    needs_rot = _detect_orientation_by_content(img_bytes, 595, 842)
    print(f"  w=595, h=842, w<h={595<842}")
    print(f"  检测为 {'需要旋转' if needs_rot else '无需旋转'}")
    assert not needs_rot, "竖版正确方向不应旋转"
    print("  ✅ PASS")

    # 测试2: A4 横版文档（可能是旋转后的竖版） — w > h
    print("\n[Test 2] 横版 A4 (可能是旋转后的竖版)")
    img_bytes = create_test_image(20, 842, 595)
    needs_rot = _detect_orientation_by_content(img_bytes, 842, 595)
    print(f"  w=842, h=595, ratio(h/w)={595/842:.3f}")
    print(f"  检测为 {'需要旋转' if needs_rot else '无需旋转'}")
    assert needs_rot, "旋转后的竖版文档应检测到需要旋转"
    print("  ✅ PASS")

    # 测试3: 真正横版文档（如宽表格） — 比例不应触发检测
    print("\n[Test 3] 超宽横版 (16:9 表格)")
    img_bytes = create_test_image(10, 1600, 900)
    needs_rot = _detect_orientation_by_content(img_bytes, 1600, 900)
    print(f"  w=1600, h=900, ratio(h/w)={900/1600:.3f}")
    print(f"  检测为 {'需要旋转' if needs_rot else '无需旋转'}")
    assert not needs_rot, "超宽横版不应旋转"
    print("  ✅ PASS")

    # 测试4: 照片比例横版 — 比例不在文档范围
    print("\n[Test 4] 4:3 横版照片")
    img_bytes = create_test_image(10, 1200, 900)
    needs_rot = _detect_orientation_by_content(img_bytes, 1200, 900)
    print(f"  w=1200, h=900, ratio(h/w)={900/1200:.3f}")
    print(f"  检测为 {'需要旋转' if needs_rot else '无需旋转'}")
    assert not needs_rot, "4:3 照片不应旋转"
    print("  ✅ PASS")

    # 测试5: A4 竖版已正确，w < h — 直接跳过
    print("\n[Test 5] 竖版 A4 正确方向 (w < h, 快速返回)")
    img_bytes = create_test_image(25, 1240, 1754)
    needs_rot = _detect_orientation_by_content(img_bytes, 1240, 1754)
    print(f"  w=1240, h=1754, w<h={1240<1754} → 直接返回 False")
    print(f"  检测为 {'需要旋转' if needs_rot else '无需旋转'}")
    assert not needs_rot, "竖版应快速返回 False"
    print("  ✅ PASS")

    # 测试6: 边界情况 — 旋转后 A4 (比例接近上限)
    print("\n[Test 6] 旋转后 A4 边界 (比例 0.707)")
    img_bytes = create_test_image(20, 1000, 707)
    needs_rot = _detect_orientation_by_content(img_bytes, 1000, 707)
    print(f"  w=1000, h=707, ratio(h/w)={707/1000:.3f}")
    print(f"  检测为 {'需要旋转' if needs_rot else '无需旋转'}")
    assert needs_rot, "旋转后 A4 应检测到需要旋转"
    print("  ✅ PASS")

    print("\n" + "=" * 60)
    print("所有测试通过! 🎉")
    print("=" * 60)


if __name__ == "__main__":
    test()
