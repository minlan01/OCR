import fitz

# Analyze new generated PDF
gen = fitz.open("/tmp/new_case123.pdf")
print(f"=== NEW Generated PDF: {len(gen)} pages ===")
for i in range(len(gen)):
    page = gen[i]
    text = page.get_text().strip().replace('\n',' ')[:100]
    imgs = page.get_images()
    # Only count images larger than tiny (real content vs stamps)
    real_imgs = 0
    for img in imgs:
        xref = img[0]
        base_image = gen.extract_image(xref)
        w, h = base_image.get("width", 0), base_image.get("height", 0)
        if w > 50 and h > 50:
            real_imgs += 1
    print(f"  P{i+1}: {real_imgs}imgs | {text}")
gen.close()

print()

# Compare with reference
ref = fitz.open(r"C:/Users/Administrator/Desktop/赵小艳起诉材料/（已压缩）证据材料（赵小艳）.pdf")
print(f"=== Reference PDF: {len(ref)} pages ===")
for i in range(len(ref)):
    page = ref[i]
    text = page.get_text().strip().replace('\n',' ')[:100]
    imgs = page.get_images()
    real_imgs = 0
    for img in imgs:
        xref = img[0]
        base_image = ref.extract_image(xref)
        w, h = base_image.get("width", 0), base_image.get("height", 0)
        if w > 50 and h > 50:
            real_imgs += 1
    print(f"  P{i+1}: {real_imgs}imgs | {text}")
ref.close()
