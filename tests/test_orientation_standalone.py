"""
独立测试内容旋转检测 — 行/列均值方差方法
关键设计：
- "不需要旋转": 文字水平排列的图片（竖版 w<h 或横版文档）
- "需要旋转": 横版图片但文字垂直排列（模拟竖版文档横放扫描）
"""
import io
import random
import numpy as np
from PIL import Image as PILImage, ImageDraw, ImageFont


def _detect_orientation_by_content(img_bytes: bytes, w: int, h: int) -> bool:
    if w <= h:
        return False
    ratio = h / w
    if not (0.68 <= ratio <= 0.82):
        return False
    try:
        img = PILImage.open(io.BytesIO(img_bytes))
        target_w = 300
        target_h = max(80, int(target_w * ratio))
        img_small = img.resize((target_w, target_h), PILImage.LANCZOS).convert("L")
        arr = np.array(img_small, dtype=np.float64)
        row_means = arr.mean(axis=1)
        row_std = np.std(row_means)
        col_means = arr.mean(axis=0)
        col_std = np.std(col_means)
        if row_std < 0.5 or col_std < 0.5:
            return False
        return (row_std / col_std) < 0.85
    except:
        return False


def _find_font(size: int = 16) -> ImageFont.FreeTypeFont | None:
    for fp in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc",
               "C:/Windows/Fonts/simhei.ttf"]:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return None


def _make_portrait_doc(w: int, h: int, num_lines: int, font_size: int = 16) -> bytes:
    """生成竖版文档图片（文字水平排列，白底黑字）"""
    font = _find_font(font_size)
    img = PILImage.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    random.seed(42)

    line_h = max(font_size + 6, h // (num_lines + 2))
    sample_text = "这是一段模拟扫描文档的文字内容用于测试图片方向检测算法"

    for i in range(num_lines):
        y = line_h * (i + 1) + random.randint(-1, 1)
        x = random.randint(10, 50)
        chars_per_seg = random.randint(4, 10)
        seg_gap = random.randint(8, 20)
        segs_in_line = 0

        while x < w - 30 and segs_in_line < 12:
            seg = sample_text[:chars_per_seg]
            if font:
                draw.text((x, y), seg, fill=(20, 20, 20), font=font)
                bbox = font.getbbox(seg)
                x += bbox[2] - bbox[0] + seg_gap
            else:
                for cx in range(x, min(x + chars_per_seg * 8, w - 10)):
                    for cy_off in range(0, font_size, random.randint(2, 3)):
                        draw.point((cx, y + cy_off),
                                   fill=(random.randint(0, 60), 0, 0))
                x += chars_per_seg * 8 + seg_gap
            segs_in_line += 1
            chars_per_seg = random.randint(4, 10)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_correct_image(w: int, h: int, num_lines: int, font_size: int = 16) -> bytes:
    """生成正确方向的图片（文字水平）"""
    return _make_portrait_doc(w, h, num_lines, font_size)


def make_rotated_image(orig_w: int, orig_h: int, num_lines: int, font_size: int = 16) -> bytes:
    """
    生成模拟"竖版文档横放扫描"的图片：
    1. 先按正确方向生成竖版文档 (orig_w < orig_h, 文字水平)
    2. 旋转 90° → 得到横版图片 (w>h, 文字垂直)
    """
    # 先生成正确方向的竖版文档
    portrait_bytes = _make_portrait_doc(orig_w, orig_h, num_lines, font_size)
    img = PILImage.open(io.BytesIO(portrait_bytes))

    # 旋转 90° 顺时针 → 文字变垂直，图片变横版
    img_rotated = img.rotate(90, expand=True)

    buf = io.BytesIO()
    img_rotated.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def run_test(name: str, w: int, h: int, lines: int, expect: bool,
             is_rotated: bool = False, font_size: int = 16):
    if is_rotated:
        img_bytes = make_rotated_image(h, w, lines, font_size)
        # make_rotated_image takes (portrait_w, portrait_h) = (h, w) since h<w for landscape
        actual_w, actual_h = w, h
    else:
        img_bytes = make_correct_image(w, h, lines, font_size)
        actual_w, actual_h = w, h

    result = _detect_orientation_by_content(img_bytes, actual_w, actual_h)
    ratio = actual_h / actual_w if actual_w > 0 else 1.0
    label = "ROTATE" if result else "skip"
    exp_label = "ROTATE" if expect else "skip"
    status = "✅" if result == expect else "❌"

    try:
        img = PILImage.open(io.BytesIO(img_bytes))
        target_w = 300
        target_h = max(80, int(target_w * ratio))
        img_small = img.resize((target_w, target_h), PILImage.LANCZOS).convert("L")
        arr = np.array(img_small, dtype=np.float64)
        row_std = np.std(arr.mean(axis=1))
        col_std = np.std(arr.mean(axis=0))
        ratio_str = f"{row_std/col_std:.3f}" if col_std > 0.5 else "N/A"
    except:
        ratio_str = "ERR"

    in_range = "√" if 0.68 <= ratio <= 0.82 else "×"
    print(f"  {status} {name:20s} {actual_w}x{actual_h:<5} r={ratio:.3f}[{in_range}] "
          f"row/col={ratio_str:>7s}  detect={label:6s} expect={exp_label}")
    return result == expect


print("=" * 82)
print("内容旋转检测 — 行/列均值方差方法 (ratio 0.68-0.82)")
print(f"字体: {'可用' if _find_font() else '未找到'}")
print("行/列: row_std/col_std < 0.85 → 文字垂直 → 需旋转")
print("=" * 82)

all_pass = True

# === 需旋转: 竖版文档横放扫描 → 横版+文字垂直 ===
print("\n[应检测旋转 — 竖版文档横放: 文字垂直排列, 行均值平稳]")
all_pass &= run_test("A4横放(0.707)", 842, 595, 20, True, is_rotated=True)
all_pass &= run_test("Letter横放(0.773)", 1000, 773, 20, True, is_rotated=True)
all_pass &= run_test("近A4横放(0.72)", 1000, 720, 18, True, is_rotated=True)

# === 不需旋转: 竖版正确方向 ===
print("\n[不应旋转 — 竖版正确 (w<h, 文字水平)]")
all_pass &= run_test("竖版A4", 595, 842, 22, False)
all_pass &= run_test("竖版图片", 1240, 1754, 25, False)

# === 不需旋转: 比例不触发 ===
print("\n[不应旋转 — 比例不触发 (非文档比例)]")
all_pass &= run_test("16:9横版", 1600, 900, 12, False)
all_pass &= run_test("超窄横版", 2000, 900, 10, False)
all_pass &= run_test("正方形", 800, 800, 12, False)

# === 不需旋转: 横版文档文字水平 ===
print("\n[不应旋转 — 横版文档文字水平排列]")
all_pass &= run_test("4:3横版文档", 1200, 900, 14, False, font_size=14)
all_pass &= run_test("5:4横版文档", 1200, 960, 14, False, font_size=14)
all_pass &= run_test("A4横版文档", 1000, 707, 10, False, font_size=14)
all_pass &= run_test("Letter横版文档", 1000, 773, 10, False, font_size=14)

# === 边缘 ===
print("\n[边缘情况]")
white_img = PILImage.new("RGB", (842, 595), (255, 255, 255))
buf = io.BytesIO()
white_img.save(buf, format="JPEG", quality=90)
result = _detect_orientation_by_content(buf.getvalue(), 842, 595)
s = "✅" if not result else "❌"
print(f"  {s} {'全白图片':20s} {'N/A':>22s}  detect={'ROTATE' if result else 'skip':6s} expect=skip")
all_pass &= (not result)

all_pass &= run_test("少文字横放(3行)", 1000, 720, 3, True, is_rotated=True, font_size=14)

print("\n" + "=" * 82)
if all_pass:
    print("所有 15 项测试全部通过! ✅")
else:
    print("有测试失败! ❌")
print("=" * 82)
