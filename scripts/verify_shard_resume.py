"""Task 2 断点续传验证 v3：触发 process → 等 15s → 记录 etag → stop workers。

策略：触发 process 后等 15 秒（dispatch 已派发批次 + 批次可能跑了一部分），
记录当前 page json 的 etag，然后 stop 两个 docker worker。
重启后 Celery acks_late redeliver 未完成的批次 task，checkpoint 幂等跳过已写页。

用法：python scripts/verify_shard_resume.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid

import requests

API = "http://localhost:8900/api/v1"


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
        token = r.json()["access_token"]
    else:
        r = requests.post(
            f"{API}/auth/login",
            json={"email": email, "password": "ShardVerify123!"},
            timeout=30,
        )
        token = r.json()["access_token"]
    return token, email


def main():
    pdf = r"E:\诉状生成系统\诉状生成系统·测试素材\余世贵（死亡）\余世贵病历.pdf"
    token, email = _login()
    H = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    r = requests.post(
        f"{API}/evidence/cases",
        json={"case_name": f"断点续传v3-{uuid.uuid4().hex[:6]}", "case_type": "death"},
        headers=H,
        timeout=30,
    )
    case_id = r.json()["id"]
    print(f"case: {case_id}")

    with open(pdf, "rb") as f:
        r = requests.post(
            f"{API}/evidence/cases/{case_id}/upload",
            files={"files": ("余世贵病历.pdf", f, "application/pdf")},
            headers=H,
            timeout=600,
        )
    mat_id = r.json()[0]["id"]
    print(f"material: {mat_id}")

    r = requests.post(
        f"{API}/evidence/cases/{case_id}/process", json={}, headers=H, timeout=30
    )
    print(f"process: {r.status_code}")

    # 等 15 秒让 dispatch 派发批次 + 批次开始跑一部分
    print("waiting 15s for batches to start...")
    time.sleep(15)

    # 记录当前 progress + page json etag
    r = requests.get(
        f"{API}/evidence/cases/{case_id}/progress", headers=H, timeout=30
    )
    p = r.json()
    shard = p.get("ocr_shard_progress")
    print(f"progress at crash: {shard}")

    # 记录 page json etag 快照
    from config.settings import settings
    from services.storage.minio_client import minio_client

    prefix = f"evidence/{case_id}/ocr/{mat_id}"
    objs = list(
        minio_client.client.list_objects(
            settings.minio_bucket_result, prefix=prefix + "/", recursive=True
        )
    )
    pages = [o for o in objs if "/pages/page_" in o.object_name]
    etags = {o.object_name: o.etag for o in pages}
    with open("etags_before_crash.json", "w") as f:
        json.dump(etags, f)
    print(f"pages before crash: {len(pages)}")

    # stop workers
    res = subprocess.run(
        ["docker", "stop", "scanstruct-worker", "scanstruct-worker-backup"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print("docker stop exit:", res.returncode)
    print("CRASH INJECTED")
    print(f"CASE_ID={case_id}")
    print(f"MAT_ID={mat_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
