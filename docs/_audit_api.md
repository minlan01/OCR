# OCR Scan Struct — API Audit Report

> Generated: 2026-05-14 | Scope: `api/` directory (all `.py` files)

---

## 1. API Endpoints Inventory

### 1.1 Health Routes (`api/routes/health.py`)

| # | Method | Path | Function | Status Codes | Auth |
|---|--------|------|----------|-------------|------|
| 1 | `GET` | `/api/v1/health` | `health_check()` | 200 | Public (exempt) |
| 2 | `GET` | `/api/v1/ping` | `ping()` | 200 | Public (exempt) |

**Details:**
- `health_check` — Full system health: checks DB (SELECT 1), Redis (PING), MinIO (ping). Returns `HealthResponse` with status `"ok"` or `"degraded"`.
- `ping` — Lightweight: returns `{"ping": "pong", "time": ..., "host": ...}`. No response model.

---

### 1.2 Scan Routes (`api/routes/scan.py`)

| # | Method | Path | Function | Status Codes | Auth |
|---|--------|------|----------|-------------|------|
| 3 | `POST` | `/api/v1/scans/upload` | `upload_scan()` | 202, 400, 500 | Required |
| 4 | `GET` | `/api/v1/scans` | `list_scans()` | 200, 400 | Required |
| 5 | `GET` | `/api/v1/scans/{task_id}` | `get_scan_detail()` | 200, 404 | Required |
| 6 | `GET` | `/api/v1/scans/{task_id}/result` | `get_scan_result()` | 200, 400, 404, 500 | Required |
| 7 | `POST` | `/api/v1/scans/{task_id}/retry` | `retry_scan()` | 202, 400, 404, 500 | Required |
| 8 | `DELETE` | `/api/v1/scans/{task_id}` | `delete_scan()` | 200, 404 | Required |

**Details:**
- **upload_scan** — Multipart form upload (PDF). Validates extension, size (100MB max), empty check, MD5 dedup. Stores raw PDF to MinIO, creates ScanTask + ScanFile records. Uses `ScanUploadResponse` response model.
- **list_scans** — Paginated list with sort/filter. Validates page ≥1, size 1–100, sort field whitelist, sort order regex. Uses `PaginatedResponse[ScanTaskSummary]`.
- **get_scan_detail** — Full task detail with steps, files, optional presigned URLs. Uses `ScanTaskDetail` response model.
- **get_scan_result** — Fetches result JSON from MinIO. Supports download (attachment) or inline mode. Validates task is `completed` and `result_path` exists. No response model for inline mode.
- **retry_scan** — Resets failed task to pending, dispatches Celery. State-gated: only `failed` by default; `force=true` allows `failed/completed/pending/received`. Uses `MessageResponse`.
- **delete_scan** — Revokes Celery task, cleans MinIO objects, cascading DB delete. `keep_raw=true` preserves original PDF. Uses `MessageResponse`.

---

### 1.3 Admin Routes (`api/routes/admin.py`)

| # | Method | Path | Function | Status Codes | Auth |
|---|--------|------|----------|-------------|------|
| 9 | `GET` | `/api/v1/admin/stats` | `admin_stats()` | 200 | Required (admin) |
| 10 | `GET` | `/api/v1/admin/queue` | `admin_queue()` | 200 | Required (admin) |

**Details:**
- **admin_stats** — Returns total tasks, today's tasks, failed count, avg confidence, breakdown by status. No response model — returns raw dict.
- **admin_queue** — Returns top 50 pending/received/retrying tasks ordered by priority desc, created_at asc. No response model — returns raw dict.

---

## 2. Request/Response Model Validation Completeness

### 2.1 Response Models

| Endpoint | Response Model | Status |
|---|---|---|
| `GET /health` | `HealthResponse` | Defined |
| `GET /ping` | **None** | **Missing** — raw dict |
| `POST /scans/upload` | `ScanUploadResponse` | Defined |
| `GET /scans` | `PaginatedResponse[ScanTaskSummary]` | Defined |
| `GET /scans/{id}` | `ScanTaskDetail` | Defined |
| `GET /scans/{id}/result` | **None** | **Missing** — raw dict / Response |
| `POST /scans/{id}/retry` | `MessageResponse` | Defined |
| `DELETE /scans/{id}` | `MessageResponse` | Defined |
| `GET /admin/stats` | **None** | **Missing** — raw dict |
| `GET /admin/queue` | **None** | **Missing** — raw dict |

### 2.2 Request Body Validation

| Endpoint | Request Type | Validation |
|---|---|---|
| `POST /scans/upload` | Multipart form | Extension + size validated in code; no content-type validation despite `ALLOWED_CONTENT_TYPES` being defined |
| All others | Query params / path params | FastAPI validates types; `list_scans` has additional constraints (page ge, size le, sort order regex) |

### 2.3 Unused Schemas

- **`ScanUploadRequest`** (`api/schemas/scan.py`): Defined but never imported or used anywhere.
- **`ScanListQuery`** (`api/schemas/scan.py`): Defined but never imported or used anywhere.
- **`ErrorResponse`** (`api/schemas/common.py`): Defined but never used — all errors are raised via `HTTPException` directly.

### 2.4 Pydantic Field Constraints

The Pydantic models are generally **weakly constrained**:

| Model | Missing Constraints |
|---|---|
| `ScanUploadResponse.filename` | No min/max length. |
| `ScanUploadResponse.message` | No min/max length, no enum. |
| `ScanTaskSummary.status` | No regex/enum for valid status values. |
| `ScanTaskSummary.filename` | No length constraints. |
| `TaskStepOut.step_name` | No length constraints. |
| `TaskStepOut.status` | No valid status enum. |
| `ScanFileOut.file_type` | No valid file type enum. |
| `ScanFileOut.object_key` | No length constraints. |
| `ScanTaskDetail.filename` | No length constraints. |
| `ScanTaskDetail.callback_url` | Not validated as URL. |
| `ScanTaskDetail.error_code` | No valid error code enumeration. |
| `ScanTaskDetail.priority` | No min/max bounds. |

---

## 3. Error Handling Patterns

### 3.1 Current Patterns (Positive)

- **Layered try/except** in `upload_scan`: File read → metadata parse → MinIO upload, each with specific handling.
- **Graceful partial failure** in `delete_scan`: Celery revocation and MinIO cleanup errors are logged but don't block the delete. `cleanup_errors` are tracked but not exposed to the caller (good).
- **Graceful degradation** in `health_check`: Individual dependency failures lower status to `"degraded"` without crashing.
- **Conditional retry gating** in `retry_scan`: Explicit status validation prevents invalid state transitions.
- **Consistent use of `_get_task_or_404()` helper**: Eliminates duplicate 404 logic across 4 endpoints.
- **loguru logger** used consistently at appropriate levels (`info`, `warning`, `error`).

### 3.2 Issues

- **Exception message leakage to HTTP responses**:
  - `get_scan_result` line 405: `f"Failed to retrieve result from storage: {e}"` — exposes internal MinIO error details.
  - `get_scan_result` line 415: `f"Result file is corrupted: {e}"` — exposes internal JSON parse error details.
  - `health_check` lines 38, 49, 62: Exposes internal error messages (DB, Redis, MinIO) in health response.
  - `upload_scan` line 160: `f"Failed to read file: {e}"` — exposes file I/O error details.
  - `retry_scan` line 508: `f"Failed to dispatch retry: {e}"` — exposes Celery/Redis error details.

- **Missing global exception handler**: No `@app.exception_handler` for unhandled exceptions — any unexpected exception will be caught by FastAPI's default handler and may leak tracebacks.

- **No error response standardization**: Some errors use HTTPException directly, some use JSONResponse in middleware. No consistent `error_code` across all error responses despite `ErrorResponse` schema being defined.

- **`health_check` creates a new Redis connection per request** (line 44): `Redis.from_url()` without reusing connections. Inefficient and not aligned with the Redis client usage pattern.

---

## 4. Authentication Implementation Details

### 4.1 Middleware (`api/middleware.py`)

**Class:** `APIKeyMiddleware(BaseHTTPMiddleware)`

**Flow:**

```
1. Check if path is in PUBLIC_PATHS → allow
2. Check if API_KEY is not configured → allow (dev mode)
3. If path starts with /api/v1/admin/ or contains /callback → require auth
4. All other /api/v1/* paths → require auth (when API_KEY is set)
```

**Header:** `X-API-Key` (case-insensitive: checks both `X-API-Key` and `x-api-key`)

**Public paths (always exempt):**
- `/api/v1/health`
- `/api/v1/ping`
- `/api/docs`
- `/api/redoc`
- `/api/openapi.json`
- `/api/docs/*` (prefix match)
- `/api/redoc/*` (prefix match)

**Response codes:**
- `401` — Missing API key (`"Missing API key"`, `error_code: "UNAUTHORIZED"`)
- `403` — Invalid API key (`"Invalid API key"`, `error_code: "FORBIDDEN"`)

### 4.2 Security Concerns

| Issue | Severity | Details |
|---|---|---|
| **No constant-time comparison** | Medium | `api_key != settings.api_key` uses standard string comparison, vulnerable to timing attacks. Use `secrets.compare_digest()`. |
| **No rate limiting** | Medium | No protection against brute-force API key guessing. Could be mitigated with fail2ban or middleware-level rate limiter. |
| **No key rotation/expiration** | Low | API key is static, configured via settings. No mechanism for rotation without restart. |
| **No key scoping** | Low | Single API key for all operations. No distinction between read/write/admin scopes. |
| **Dev mode bypass** | Info | When `API_KEY` is not set, all routes are public. Intentional for development but could be accidentally deployed. |

---

## 5. Input Constraints and Edge Cases

### 5.1 File Upload (`POST /scans/upload`)

| Constraint | Implementation | Status |
|---|---|---|
| File extension | Whitelist: `.pdf` only (case-insensitive) | Done |
| Max file size | 100 MB (code-level check) | Done |
| Empty file | Checked (len(content) == 0) | Done |
| Content type | `ALLOWED_CONTENT_TYPES` defined but **not enforced** | **Missing** |
| MD5 dedup | Computes MD5, checks for existing task | Done |
| metadata JSON | Parsed via `json.loads()`, error on invalid | Done |
| Filename injection | Uses `quote(filename)` for MinIO key; `uuid4()` prefix | Done |

### 5.2 Task Listing (`GET /scans`)

| Constraint | Implementation | Status |
|---|---|---|
| Page bounds | `ge=1`, default=1 | Done |
| Page size bounds | `ge=1, le=100`, default=20 | Done |
| Sort field | Whitelist `ALLOWED_SORT_FIELDS` | Done |
| Sort order | Regex `^(asc\|desc)$` | Done |
| Status filter value | **No validation** — accepts any string | **Missing** |
| Scanner ID filter | Accepts any string (no format check) | Acceptable |

### 5.3 Task Detail (`GET /scans/{task_id}`)

| Edge Case | Handling | Status |
|---|---|---|
| Missing task | `_get_task_or_404` → 404 | Done |
| Non-UUID path param | FastAPI automatic 422 | Done |
| Presigned URL failure | Per-file try/except, sets `None` | Done |
| No files attached | `for f_obj in (task.files or [])` | Done |

### 5.4 Task Retry (`POST /scans/{task_id}/retry`)

| Edge Case | Handling | Status |
|---|---|---|
| Not failed & not forced | 400 with clear message | Done |
| Invalid status for retry | 400 blocks `processing`, `cancelled`, etc. | Done |
| Celery unavailable | 500 with check for `process_scan is None` | Done |
| Celery dispatch failure | Rolls back status to "failed" | Done |

### 5.5 Task Deletion (`DELETE /scans/{task_id}`)

| Edge Case | Handling | Status |
|---|---|---|
| Celery unavailable | Logged as debug, skip revocation | Done |
| MinIO cleanup error | Per-object error tracking, logged | Done |
| keep_raw=true | Skips raw bucket only | Done |
| Orphaned MinIO objects | Uses `minio_client.delete_task_objects()` with `str(task_id)` prefix | Done |

### 5.6 Health Check (`GET /health`)

| Edge Case | Handling | Status |
|---|---|---|
| DB unavailable | Try/except, sets status="degraded" | Done |
| Redis unavailable | Try/except with 2s timeout, status="degraded" | Done |
| MinIO unavailable | Try/except, status="degraded" | Done |
| **New Redis connection per call** | Creates `Redis.from_url()` each time | **Inefficient** |

### 5.7 Admin Endpoints

| Issue | Details |
|---|---|
| No pagination on `/admin/queue` | Returns up to 50 items with no pagination params |
| No auth on stats/queue within route | Relies entirely on middleware |
| Raw dict return | No response model validation |

---

## 6. Security Concerns

### 6.1 Injection Risks

| Vector | Assessment | Risk |
|---|---|---|
| SQL injection | SQLAlchemy ORM throughout; no raw SQL | **None** |
| sort_by injection | Whitelist-validated before `getattr()` | **None** |
| Path traversal (upload) | Object key = `raw/{date}/{uuid}_{quote(filename)}` | **Low** — UUID prefix prevents traversal |
| Path traversal (download) | Uses `task.result_path` from DB | **Low** — if DB is trusted |
| Path traversal (delete) | Uses `str(task_id)` as MinIO prefix | **None** — UUID is safe |
| JSON injection | metadata parsed with `json.loads()` | **None** |

### 6.2 File Upload Security

| Concern | Details | Risk |
|---|---|---|
| Extension-only validation | File content is not validated as actual PDF. Attacker can upload any file with `.pdf` extension. | **Medium** |
| Content-type not validated | `ALLOWED_CONTENT_TYPES = {"application/pdf"}` is defined in code but never checked. | **Medium** |
| No virus scanning | Uploaded files are not scanned for malware. | **Medium** |
| No filename sanitization (DB) | Original filename stored as-is in DB. | **Low** |

### 6.3 Information Leakage

| Leak | Location | Risk |
|---|---|---|
| Internal exception messages in HTTP responses | `scan.py` lines 160, 405, 415, 508, 515 | **Medium** |
| Internal service errors in health response | `health.py` lines 38, 49, 62 | **Low** — health endpoint should be internal |
| Filename exposure | Normal for this application type | **Acceptable** |
| Internal server structure | Object key patterns reveal date/UUID structure | **Acceptable** |

### 6.4 Authentication

| Concern | Risk |
|---|---|
| No constant-time comparison | **Medium** |
| No rate limiting on auth failures | **Medium** |
| No brute-force protection | **Medium** |

### 6.5 Missing Security Headers

No evidence of the following being configured in the files reviewed:
- CORS headers (CORS middleware not seen in `api/`)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy`
- Rate limiting headers

### 6.6 Other

| Concern | Details |
|---|---|
| `task_id` exposed in error messages | `f"Task not found: {task_id}"` — UUIDs are not sensitive, acceptable |
| MD5 used for dedup | MD5 is cryptographically broken but acceptable for file deduplication (not security) |
| `quote()` from `urllib.parse` for filename in object key | Proper URL encoding prevents S3 key injection |

---

## 7. Summary of Findings

### Critical: 0
### High: 0
### Medium: 5
### Low: 8
### Info: 6

### Medium Severity

| # | Finding | File | Line |
|---|---|---|---|
| M1 | No constant-time API key comparison (timing attack) | `middleware.py` | 61 |
| M2 | No rate limiting on API endpoints | `middleware.py` | — |
| M3 | File content type not validated (only extension) | `scan.py` | 150 |
| M4 | Internal exception messages exposed to HTTP responses | `scan.py` | 160, 405, 415, 508, 515 |
| M5 | Internal error details exposed in health response | `health.py` | 38, 49, 62 |

### Low Severity

| # | Finding |
|---|---|
| L1 | Admin endpoints return raw dicts — no response model validation |
| L2 | `GET /ping` has no response model |
| L3 | `GET /scans/{id}/result` has no response model for inline mode |
| L4 | `ScanUploadRequest` and `ScanListQuery` schemas defined but unused |
| L5 | `ErrorResponse` schema defined but unused |
| L6 | Pydantic models lack length/format constraints (filename, callback_url, status, etc.) |
| L7 | No status value validation on `list_scans` filter |
| L8 | `health_check` creates new Redis connection per request |

### Informational

| # | Finding |
|---|---|
| I1 | Single API key for all operations — no scope separation |
| I2 | No key rotation mechanism |
| I3 | Dev mode (no API_KEY) bypasses all auth |
| I4 | `/admin/queue` lacks pagination |
| I5 | No global exception handler for unexpected errors |
| I6 | No CORS configuration visible in api/ directory |

---

## 8. Recommendations (Prioritized)

1. **Fix M4 (exception leakage):** Replace `f"...{e}"` patterns in error responses with generic user-facing messages. Log the full exception instead.
2. **Fix M1 (timing attack):** Replace `api_key != settings.api_key` with `not secrets.compare_digest(api_key, settings.api_key)`.
3. **Fix M2 (rate limiting):** Add `slowapi` or similar middleware for rate limiting on auth-protected endpoints.
4. **Fix M3 (content validation):** Validate `file.content_type` against `ALLOWED_CONTENT_TYPES` or validate via `python-magic`.
5. **Fix M5 (health info leak):** Return `"unhealthy"` instead of the full exception string for DB/Redis/MinIO failures.
6. **Fix L1-L3 (missing response models):** Define Pydantic models for `ping`, `admin_stats`, `admin_queue`, and `get_scan_result` inline mode.
7. **Fix L4-L5 (dead code):** Remove unused schemas or wire them into endpoints.
8. **Fix L6 (field constraints):** Add `min_length`, `max_length`, URL validation, and status enums to Pydantic models.
9. **Fix L7 (status filter):** Validate `status` query param against known status values.
10. **Fix L8 (Redis connection pooling):** Use shared Redis connection or inject via dependency.
