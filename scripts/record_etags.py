"""Task 2 crash 注入辅助：记录崩溃前 etag 快照 + DB 状态。"""
from __future__ import annotations

import json

from sqlalchemy import create_engine, text

from config.settings import settings
from services.storage.minio_client import minio_client

CASE_ID = "44f45d77-959c-4260-b73b-2e9653f68173"
MAT_ID = "6f2c4d95-a6e6-402e-af45-ac78244d875b"
prefix = f"evidence/{CASE_ID}/ocr/{MAT_ID}"

objs = list(
    minio_client.client.list_objects(
        settings.minio_bucket_result, prefix=prefix + "/", recursive=True
    )
)
pages = [o for o in objs if "/pages/page_" in o.object_name]
etags = {o.object_name: o.etag for o in pages}
with open("etags_before_crash.json", "w") as f:
    json.dump(etags, f)
print("pages before crash:", len(pages))
print("saved etags to etags_before_crash.json")

eng = create_engine(settings.database_url_sync)
with eng.connect() as conn:
    row = conn.execute(
        text("SELECT ocr_status FROM evidence_materials WHERE id = :mid"),
        {"mid": MAT_ID},
    ).fetchone()
    print("ocr_status before crash:", row[0] if row else "NOT FOUND")
eng.dispose()
