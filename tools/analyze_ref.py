import fitz
ref = fitz.open(r"C:/Users/Administrator/Desktop/赵小艳起诉材料/（已压缩）证据材料（赵小艳）.pdf")
print(f"Reference PDF: {len(ref)} pages")
for i in range(len(ref)):
    page = ref[i]
    text = page.get_text().strip().replace('\n',' ')[:120]
    imgs = page.get_images()
    print(f"P{i+1}: {len(imgs)}imgs | {text}")
ref.close()
