"""Task 2 重试 failed material：调 retry-ocr 端点触发续传，然后轮询到完成。"""
from __future__ import annotations

import json
import sys
import time
import uuid

import requests
from sqlalchemy import create_engine, text

from config.settings import settings
from services.storage.minio_client import minio_client

API = "http://localhost:8900/api/v1"
CASE_ID = "a782f3b6-c1d7-4372-9651-69c741885d52"
MAT_ID = "27e64fc2-f960-4972-895a-61056e761207"


def _login():
    email = f"resume+{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "password": "ShardVerify123!",
            "tenant_name": "ResumeTest",
            "username": "resume",
            "display_name": "Resume Tester",
        },
        timeout=30,
    )
    if r.status_code == 201:
        return r.json()["access_token"]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "ShardVerify123!"},
        timeout=30,
    )
    return r.json()["access_token"]


def main():
    token = _login()
    H = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # 调 retry-ocr
    r = requests.post(
        f"{API}/evidence/cases/{CASE_ID}/materials/{MAT_ID}/retry-ocr",
        headers=H,
        timeout=30,
    )
    print(f"retry-ocr: {r.status_code} {r.text[:200]}")

    # 轮询到终态
    for i in range(180):
        r = requests.get(
            f"{API}/evidence/cases/{CASE_ID}/progress", headers=H, timeout=30
        )
        p = r.json()
        shard = p.get("ocr_shard_progress")
        if shard:
            cb = shard.get("completed_batches")
            done = list(range(cb)) if isinstance(cb, int) else (cb or [])
        else:
            done = []
        print(f"+{i*5}s done={done} case_st={p.get('status')}")

        eng = create_engine(settings.database_url_sync)
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT ocr_status FROM evidence_materials WHERE id = :mid"),
                {"mid": MAT_ID},
            ).fetchone()
        eng.dispose()
        mst = row[0] if row else "NF"
        if mst in ("completed", "failed"):
            print(f"MATERIAL TERMINAL: {mst}")
            break
        time.sleep(5)
    else:
        print("TIMEOUT")
        return 1

    # 校验
    print("--- verify ---")
    eng = create_engine(settings.database_url_sync)
    with eng.connect() as conn:
        row = conn.execute(
            text(
                "SELECT ocr_status, (ocr_result->>'page_count') as pgs, "
                "(ocr_result->>'storage') as storage, "
                "(ocr_result->>'source_type') as src, "
                "(ocr_result->>'full_text_length') as ft_len "
                "FROM evidence_materials WHERE id = :mid"
            ),
            {"mid": MAT_ID},
        ).fetchone()
    eng.dispose()
    print(f"DB: status={row[0]} pgs={row[1]} storage={row[2]} src={row[3]} ft_len={row[4]}")

    prefix = f"evidence/{CASE_ID}/ocr/{MAT_ID}"
    objs = list(
        minio_client.client.list_objects(
            settings.minio_bucket_result, prefix=prefix + "/", recursive=True
        )
    )
    pages = [o for o in objs if "/pages/page_" in o.object_name]
    print(f"MinIO pages: {len(pages)}")

    ok = (
        row[0] == "completed"
        and int(row[1] or 0) == 564
        and row[2] == "minio"
        and row[3] == "pdf_ocr_shard"
        and len(pages) == 564
    )
    print("RESULT:", "SUCCESS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
