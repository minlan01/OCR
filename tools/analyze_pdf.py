"""分析人工版和系统版PDF布局差异"""
import fitz
import sys

# 人工参考版
ref_path = r"C:\Users\Administrator\Desktop\赵小艳起诉材料\（已压缩）证据材料（赵小艳）.pdf"
ref = fitz.open(ref_path)
print(f"=== 人工参考版 PDF ===")
print(f"页数: {len(ref)}")
for i in range(len(ref)):
    page = ref[i]
    text = page.get_text().strip()
    rect = page.rect
    imgs = page.get_images()
    text_preview = text[:80].replace('\n', ' ') if text else "(无文本)"
    print(f"第{i+1}页: {rect.width:.0f}x{rect.height:.0f}pt | 图片数:{len(imgs)} | {text_preview}")
ref.close()

print()

# 系统生成版
gen_path = sys.argv[1] if len(sys.argv) > 1 else None
if gen_path:
    try:
        gen = fitz.open(gen_path)
        print(f"=== 系统生成版 PDF ===")
        print(f"页数: {len(gen)}")
        for i in range(len(gen)):
            page = gen[i]
            text = page.get_text().strip()
            rect = page.rect
            imgs = page.get_images()
            text_preview = text[:80].replace('\n', ' ') if text else "(无文本)"
            print(f"第{i+1}页: {rect.width:.0f}x{rect.height:.0f}pt | 图片数:{len(imgs)} | {text_preview}")
        gen.close()
    except Exception as e:
        print(f"无法打开生成版: {e}")
