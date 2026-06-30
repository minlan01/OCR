"""真实端到端验证：分片 OCR 全链路（冒烟）

用法：python scripts/verify_shard_e2e.py <pdf_path>
依赖：docker-compose 全起 + 百炼配置 + worker 加载分片代码
不进 CI（依赖真实 PDF + 百炼密钥）。
"""
from __future__ import annotations

import sys
import time
import uuid

import requests
from pathlib import Path

API_BASE = "http://localhost:8900"
# 开发环境 .env 的 API_KEY 为空但 JWT_SECRET_KEY 非空 → 中间件不放行；
# 验证脚本通过注册接口自助拿 JWT access_token，走 Bearer 认证。
# 以下仅用于本验证脚本的临时账号（每次运行新建 tenant + user）。
VERIFY_EMAIL = f"verify+{uuid.uuid4().hex[:8]}@example.com"
VERIFY_PASSWORD = "verify-smoke-123456"
VERIFY_TENANT_NAME = "ShardVerify"
# 允许通过环境变量覆盖（便于复跑用同一账号）
import os
VERIFY_EMAIL = os.environ.get("VERIFY_EMAIL", VERIFY_EMAIL)
VERIFY_PASSWORD = os.environ.get("VERIFY_PASSWORD", VERIFY_PASSWORD)
VERIFY_TENANT_NAME = os.environ.get("VERIFY_TENANT_NAME", VERIFY_TENANT_NAME)

# 运行时填充
_ACCESS_TOKEN: str | None = None


def _login_or_register() -> str:
    """注册一个验证专用账号拿 JWT access_token（注册接口公开）。"""
    r = requests.post(
        f"{API_BASE}/api/v1/auth/register",
        json={
            "tenant_name": VERIFY_TENANT_NAME,
            "email": VERIFY_EMAIL,
            "password": VERIFY_PASSWORD,
            "display_name": "Shard Verify",
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if r.status_code == 409:
        # 已存在 → 登录
        r = requests.post(
            f"{API_BASE}/api/v1/auth/login",
            json={"email": VERIFY_EMAIL, "password": VERIFY_PASSWORD},
            headers={"Accept": "application/json"},
            timeout=30,
        )
    r.raise_for_status()
    token = r.json()["access_token"]
    return token


def _headers():
    h = {"Accept": "application/json"}
    if _ACCESS_TOKEN:
        h["Authorization"] = f"Bearer {_ACCESS_TOKEN}"
    return h


def main(pdf_path: str) -> int:
    global _ACCESS_TOKEN
    pdf = Path(pdf_path)
    assert pdf.exists() and pdf.is_file(), f"PDF not found: {pdf_path}"

    import fitz
    doc = fitz.open(str(pdf))
    total_pages = doc.page_count
    doc.close()
    print(f"[1/6] PDF: {pdf} ({total_pages} pages)")
    assert total_pages > 500, f"页数 {total_pages} 未超分片阈值 500"

    # 1.5 获取 JWT token（开发环境 JWT_SECRET 非空 → 中间件不放行，需 Bearer 认证）
    _ACCESS_TOKEN = _login_or_register()
    print(f"      auth: logged in as {VERIFY_EMAIL}")

    # 2. 建 case（字段：case_name / case_type=death，余世贵死亡案件素材）
    r = requests.post(
        f"{API_BASE}/api/v1/evidence/cases",
        json={
            "case_name": f"分片验证-{uuid.uuid4().hex[:8]}",
            "case_type": "death",
        },
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    case_id = r.json()["id"]
    print(f"[2/6] case created: {case_id}")

    # 3. 上传 PDF
    with pdf.open("rb") as f:
        files = {"files": (pdf.name, f, "application/pdf")}
        r = requests.post(
            f"{API_BASE}/api/v1/evidence/cases/{case_id}/upload",
            files=files,
            headers=_headers(),
            timeout=600,
        )
    r.raise_for_status()
    materials = r.json()
    assert len(materials) == 1, f"上传应返回 1 个 material，实际 {len(materials)}"
    material_id = materials[0]["id"]
    print(f"[3/6] material uploaded: {material_id}")

    # 4. 触发 process
    r = requests.post(
        f"{API_BASE}/api/v1/evidence/cases/{case_id}/process",
        json={},
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    print(f"[4/6] process triggered: {r.json()}")

    # 5. 轮询 progress（completed_batches 已是 int，无需 len）
    deadline = time.time() + 1800  # 30 分钟上限
    last_batches = None
    case_status = None
    batch_timeline = []  # 记录批次完成时刻
    poll_start = time.time()
    while time.time() < deadline:
        r = requests.get(
            f"{API_BASE}/api/v1/evidence/cases/{case_id}/progress",
            headers=_headers(),
            timeout=30,
        )
        r.raise_for_status()
        prog = r.json()
        case_status = prog.get("status") or prog.get("case_status")
        shard = prog.get("ocr_shard_progress")
        if shard:
            completed = shard.get("completed_batches")
            if isinstance(completed, list):
                completed = len(completed)
            completed = completed or 0
            total_b = shard.get("total_batches") or 0
            if completed != last_batches:
                elapsed = int(time.time() - poll_start)
                print(f"      分片进度: {completed}/{total_b} 批, case_status={case_status}, +{elapsed}s")
                batch_timeline.append((completed, total_b, elapsed, case_status))
                last_batches = completed
        if case_status in ("catalog_ready", "analyzing", "analysis_done", "completed"):
            print(f"[5/6] case advanced to {case_status}")
            break
        time.sleep(5)
    else:
        print(f"[FAIL] 轮询超时，case_status={case_status}")
        return 1

    # 6. 校验产物
    ok = _verify_artifacts(case_id, material_id, total_pages)
    if ok:
        print("[6/6] 产物校验通过")
        print(f"\n冒烟验证 SUCCESS — case_id={case_id} material_id={material_id}")
        return 0
    else:
        print(f"\n冒烟验证 FAIL — case_id={case_id} material_id={material_id}")
        return 1


def _verify_artifacts(case_id: str, material_id: str, total_pages: int) -> bool:
    import json

    from sqlalchemy import create_engine, text

    from config.settings import settings
    from services.storage.minio_client import minio_client

    ok = True
    bucket = settings.minio_bucket_result
    prefix = f"evidence/{case_id}/ocr/{material_id}"

    # DB 校验
    eng = create_engine(settings.database_url_sync)
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT ocr_status, ocr_result FROM evidence_materials WHERE id = :mid"),
                {"mid": material_id},
            ).fetchone()
    finally:
        eng.dispose()
    if not row:
        print(f"  [FAIL] material {material_id} 不存在")
        return False
    ocr_status, ocr_result_raw = row[0], row[1]
    ocr_result = ocr_result_raw if isinstance(ocr_result_raw, dict) else json.loads(ocr_result_raw or "{}")
    print(
        f"  DB: ocr_status={ocr_status}, storage={ocr_result.get('storage')}, "
        f"source_type={ocr_result.get('source_type')}, page_count={ocr_result.get('page_count')}"
    )
    if ocr_status != "completed":
        print(f"  [FAIL] ocr_status 应为 completed，实际 {ocr_status}")
        ok = False
    if ocr_result.get("storage") != "minio":
        print("  [FAIL] storage 应为 minio")
        ok = False
    if ocr_result.get("source_type") != "pdf_ocr_shard":
        print("  [FAIL] source_type 应为 pdf_ocr_shard")
        ok = False
    if ocr_result.get("page_count") != total_pages:
        print(f"  [FAIL] page_count 应为 {total_pages}")
        ok = False

    # MinIO 校验
    page_objs = []
    cp_objs = []
    if hasattr(minio_client, "list_objects"):
        for obj in minio_client.list_objects(bucket, prefix=f"{prefix}/"):
            if "/pages/page_" in obj.object_name:
                page_objs.append(obj.object_name)
            elif "/checkpoints/batch_" in obj.object_name:
                cp_objs.append(obj.object_name)
    print(f"  MinIO: pages={len(page_objs)} (期望 {total_pages}), checkpoints={len(cp_objs)}")
    if len(page_objs) != total_pages:
        print(f"  [FAIL] page json 数应为 {total_pages}，实际 {len(page_objs)}")
        ok = False

    # full_text + manifest 存在
    for key in [f"{prefix}/full_text.txt", f"{prefix}/manifest.json"]:
        try:
            minio_client.download_bytes(bucket, key)
            print(f"  MinIO: {key.split('/')[-1]} 存在")
        except Exception as e:
            print(f"  [FAIL] {key} 不存在: {e}")
            ok = False

    # full_text 非空
    try:
        ft = minio_client.download_bytes(bucket, f"{prefix}/full_text.txt").decode("utf-8")
        print(f"  full_text 长度: {len(ft)} 字符, 前 100 字: {ft[:100]!r}")
        if len(ft.strip()) == 0:
            print("  [FAIL] full_text 为空")
            ok = False
    except Exception as e:
        print(f"  [FAIL] 读 full_text 失败: {e}")
        ok = False

    return ok


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python scripts/verify_shard_e2e.py <pdf_path>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
