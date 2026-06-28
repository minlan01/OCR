"""Quick OCR confidence checker — runs inside worker container."""
import asyncio
import json
from config.settings import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


async def main():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT original_filename, ocr_result, file_type, ocr_status "
            "FROM evidence_materials "
            "WHERE evidence_case_id = '9950f946-1f90-4a65-a145-adf31948c44c' "
            "ORDER BY created_at"
        ))
        rows = result.fetchall()

        stats = []
        for fname, ocr_result, ftype, ocr_status in rows:
            data = ocr_result if isinstance(ocr_result, dict) else {}
            blocks = data.get("blocks", []) if isinstance(data, dict) else []
            confs = []
            total_chars = 0
            for b in blocks:
                if isinstance(b, dict):
                    c = b.get("confidence")
                    txt = b.get("text", "")
                    if c is not None:
                        confs.append(float(c))
                    total_chars += len(txt)
            avg_conf = sum(confs) / len(confs) if confs else 0
            low_count = sum(1 for c in confs if c < 0.6)
            stats.append({
                "filename": fname or "",
                "type": ftype or "?",
                "status": ocr_status or "?",
                "blocks": len(blocks),
                "avg_conf": round(avg_conf, 3),
                "low_conf_blocks": low_count,
                "total_chars": total_chars,
            })

        stats.sort(key=lambda x: x["avg_conf"])

        print(f"{'filename':36s} | {'type':5s} | blk | avg_conf | low<0.6 | chars")
        print("-" * 85)
        for s in stats:
            print(f"{s['filename'][:35]:35s} | {s['type']:5s} | {s['blocks']:3d} | {s['avg_conf']:.3f}   | {s['low_conf_blocks']:3d}     | {s['total_chars']}")

        confs_list = [s["avg_conf"] for s in stats if s["avg_conf"] > 0]
        if confs_list:
            print()
            print(f"Total: {len(stats)} files")
            print(f"With confidence: {len(confs_list)} files")
            print(f"Avg confidence: {sum(confs_list)/len(confs_list):.3f}")
            print(f"Low (<0.5): {sum(1 for c in confs_list if c < 0.5)}")
            print(f"Medium (0.5-0.7): {sum(1 for c in confs_list if 0.5 <= c < 0.7)}")
            print(f"High (>=0.7): {sum(1 for c in confs_list if c >= 0.7)}")
            print(f"No confidence data: {sum(1 for s in stats if s['blocks']==0 or s['avg_conf']==0)}")

asyncio.run(main())
