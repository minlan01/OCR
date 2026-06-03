# ScanStruct Configuration & Infrastructure Audit Report

**Date**: 2026-05-14  
**Scope**: `config/`, `db/`, Dockerfiles, `.env`, `requirements.txt`  
**Severity Scale**: CRITICAL > HIGH > MEDIUM > LOW > INFO

---

## 1. Security of Default Credentials

### 1.1 Database Credentials — CRITICAL

Hardcoded default credentials `scanstruct:scanstruct123` appear in 5 locations:

| File | Line(s) | Context |
|---|---|---|
| `config/settings.py` | 41-42 | Pydantic field defaults for `database_url` and `database_url_sync` |
| `.env` | 14-15 | Actual runtime values |
| `.env.example` | 14-15 | Template for new deployments |
| `docker-compose.yml` | 11-12, 74-75, 109-110, 148-149 | `POSTGRES_USER`/`POSTGRES_PASSWORD` and connection URLs for all services |

**Risks**:
- Password `scanstruct123` is trivially guessable.
- No mechanism exists to enforce password change in production.
- Identical credentials in settings defaults AND docker-compose means a deployer who forgets to override the env var gets the weak default silently.

**Recommendation**:
- Remove hardcoded defaults from `settings.py` for sensitive fields; require explicit configuration or fail fast.
- Use `SecretStr` from Pydantic for passwords so they do not leak into logs or `repr()`.
- In `docker-compose.yml`, read database password from a `.env` file or Docker secrets instead of embedding.
- Enforce minimum password length/entropy for production via a validator.

### 1.2 MinIO Credentials — HIGH

Hardcoded `minioadmin:minioadmin123` in:

| File | Line(s) |
|---|---|
| `config/settings.py` | 51-52 |
| `.env` | 24-25 |
| `.env.example` | 24-25 |
| `docker-compose.yml` | 48-49, 80-81, 115-116 |

**Risks**:
- These are MinIO's publicly documented default credentials.
- An open MinIO console (port 9001 exposed in docker-compose line 46) with default creds is an easy attack vector.

**Recommendation**:
- Same as database: remove defaults, use `SecretStr`, enforce production override.

### 1.3 Redis — MEDIUM

No password configured anywhere:

- `settings.py` line 47: `redis://localhost:6379/0` (no auth)
- `docker-compose.yml` lines 27-41: Redis container has no `requirepass` config, no `REDIS_PASSWORD` env var.
- Port 6379 is exposed on the host (line 31).

**Risks**:
- Unauthenticated Redis allows anyone on the network to read/write all data, inject tasks, or use the instance for SSRF attacks.

**Recommendation**:
- Add `REDIS_PASSWORD` environment variable support to settings and docker-compose.
- Set `requirepass` in Redis configuration or via `--requirepass` CLI flag.
- Consider not exposing Redis port on the host in production (`6379:6379` → only internal).

### 1.4 Bailian API Key — CRITICAL

`.env` line 48 contains a real API key: `sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

**Risks**:
- While `.env` is listed in `.gitignore`, it exists on disk with a live credential.
- If `.env` is ever accidentally committed, rotated, or if this machine is compromised, the key is exposed.
- The `.env.example` file does NOT include a placeholder for `BAILIAN_API_KEY`, making it likely that developers accidentally commit their real keys.

**Recommendation**:
- Rotate the exposed key immediately.
- Add `BAILIAN_API_KEY=your-key-here` to `.env.example`.
- Never store real credentials in `.env` files within the project directory; use a dedicated secrets store or OS-level env vars.

### 1.5 API Authentication — MEDIUM

`settings.py` line 38: `api_key: str = ""` — no authentication by default.

**Risks**:
- If deployed without explicitly setting `API_KEY`, the entire API is unauthenticated.
- There is no check in settings that requires `api_key` when `app_env=production`.

**Recommendation**:
- Add a validator: if `app_env == "production"` and `api_key` is empty or too short, raise a `ValidationError`.
- Consider using `SecretStr` for `api_key`.

---

## 2. Missing Configuration Validations

`config/settings.py` uses Pydantic but has only **one custom validator** (`parse_retry_delays`). All other fields rely on type coercion alone, which is insufficient for production safety.

### 2.1 Required-When Conditionals — HIGH

No cross-field validation. Example:

```python
# When ocr_engine_type == "bailian", bailian_api_key MUST be set
# Currently: silently fails if bailian_api_key is empty
```

**Recommendation**:
```python
@field_validator("bailian_api_key")
@classmethod
def require_bailian_key_if_selected(cls, v, info):
    if info.data.get("ocr_engine_type") == "bailian" and not v:
        raise ValueError("bailian_api_key is required when ocr_engine_type='bailian'")
    return v
```

### 2.2 Range / Bounds Checks — MEDIUM

| Field | Current Default | Issue |
|---|---|---|
| `api_port` | `8900` | No min/max check (0-65535) |
| `api_workers` | `1` | No minimum (could be 0 or negative) |
| `ocr_confidence_threshold` | `0.70` | No 0.0-1.0 range enforcement |
| `preprocess_dpi` | `300` | No practical range (e.g., 72-1200) |
| `retention_days` | `30` | Negative values accepted |
| `ocr_max_pages` | `200` | No upper bound |
| `callback_timeout_seconds` | `10` | Zero or negative accepted |

### 2.3 URL Format Validation — MEDIUM

`database_url`, `database_url_sync`, `redis_url`, `redis_broker_url`, `redis_result_backend`, `minio_endpoint`, `bailian_ocr_base_url` — none have format validation. A malformed URL will cause runtime crashes deep in asyncpg / redis-py / minio client.

**Recommendation**: Add `AnyUrl` or at minimum a `@field_validator` that attempts URL parsing and raises a clear error.

### 2.4 Robust Error Handling in `parse_retry_delays` — LOW

`config/settings.py` lines 99-106: the `int(x.strip())` call will raise `ValueError` on non-numeric input with an unhelpful crash. Wrap in try/except and re-raise with context.

### 2.5 enum validation for `app_env` and `ocr_engine_type` — LOW

`app_env` accepts any string. `ocr_engine_type` accepts any string. Use `Literal["development", "production"]` and `Literal["paddle", "bailian"]` to catch typos at startup.

---

## 3. Docker Best Practices Compliance

### 3.1 Multi-Stage Builds — CRITICAL

Both `Dockerfile` and `Dockerfile.worker` are **single-stage** builds.

**Issues**:
- System build dependencies (`libgl1-mesa-glx`, `libglib2.0-0`, etc.) remain in the final image, increasing attack surface and image size.
- Build tools (gcc headers included transitively) stay in runtime.
- No separation between build-time and runtime environments.

**Recommendation**:
```dockerfile
# Stage 1: builder
FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
COPY . .
...
```

### 3.2 Non-root User — CRITICAL

Neither Dockerfile creates a non-root user. Both containers run as **root (uid 0)**.

**Risks**:
- Container escape vulnerabilities are amplified.
- Any file written to mounted volumes (`scan_input`, etc.) is owned by root.
- Violates Docker and Kubernetes security best practices.

**Recommendation**:
```dockerfile
RUN groupadd -r scanstruct && useradd -r -g scanstruct scanstruct
RUN chown -R scanstruct:scanstruct /app
USER scanstruct
```
Ensure volume mounts are also owned by the non-root user, or set appropriate permissions at runtime.

### 3.3 HEALTHCHECK in Dockerfiles — MEDIUM

Neither `Dockerfile` nor `Dockerfile.worker` includes a `HEALTHCHECK` instruction. The `docker-compose.yml` service-level `healthcheck` is good but a Dockerfile-level check provides defense-in-depth.

**Recommendation**:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8900/health')" || exit 1
```

### 3.4 Image Tag Pinning — MEDIUM

- `minio/minio:latest` (docker-compose line 44) — floating tag, non-reproducible.
- `postgres:16-alpine`, `redis:7-alpine` — minor versions float but major pinned (acceptable).
- `python:3.12-slim` — will get 3.12.x patch updates (acceptable).

**Recommendation**: Pin MinIO to a specific version, e.g., `minio/minio:RELEASE.2024-XX-XX...`.

### 3.5 `.dockerignore` Gaps — LOW

- `*.env` exclusion (line 33) also blocks `.env.example` — intentional?
- Docker compose files are preserved (`!docker-compose.yml` line 33) — good.
- No explicit exclusion of `.env` (relies on `*.env` pattern, but `.env` has no extension prefix — this works because it matches `*.env` as `*` matches zero chars).

### 3.6 Security Hardening — MEDIUM

- No `--no-install-recommends` on Python pip (already used for apt, but not pip).
- No `COPY --chown` to ensure file ownership.
- Docker socket not mounted (good — not doing DinD unnecessarily).
- No `SYS_ADMIN` or other dangerous capabilities requested (good).

---

## 4. Database Model Design Quality

### 4.1 Strengths

| Aspect | Details |
|---|---|
| UUID PKs | `scan_tasks.id` uses `UUID` — good for distributed systems, avoids enumeration. |
| JSONB | `metadata_` / `step_metadata` / `file_metadata` use JSONB — flexible schema evolution. |
| CASCADE deletes | `ondelete="CASCADE"` on foreign keys — proper referential cleanup. |
| Server defaults | `gen_random_uuid()`, `NOW()` — consistent, avoids application-side timestamp drift. |
| Indexing strategy | Conditional unique index on `file_md5 WHERE NOT NULL`, descending time index, status/scanner/priority indexes. |
| Connection pooling | `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=3600` — production-ready defaults. |
| Async session | Proper commit/rollback/close lifecycle in `get_db()` generator. |

### 4.2 Issues

#### 4.2.1 Numeric Precision — MEDIUM

`confidence_avg` and `structure_score` use `Numeric(5,4)` (max 9.9999). A 0.0-1.0 confidence score needs only `Numeric(3,2)` or a `CHECK` constraint. `Numeric(5,4)` allows values > 1.0.

#### 4.2.2 Missing Unique Constraint on Task Steps — MEDIUM

`task_steps` has no unique constraint on `(task_id, step_name)`. A bug could insert duplicate "ocr" or "preprocess" steps for the same task.

**Recommendation**:
```python
UniqueConstraint("task_id", "step_name", name="uq_task_step"),
```

#### 4.2.3 Status Fields Are Free-Text — MEDIUM

`status` column on `scan_tasks` and `task_steps` accepts arbitrary strings. Invalid statuses pass through. Consider a `CHECK` constraint or application-level enum validation.

#### 4.2.4 Missing Updated-At on `scan_files` — LOW

`scan_files` has `created_at` but no `updated_at`. If file records are ever updated (e.g., size correction), the modification time is lost.

#### 4.2.5 No Composite Index on `(task_id, file_type)` — LOW

`scan_files` queries commonly filter by `task_id` AND `file_type`. A composite index would be more efficient than two single-column indexes.

#### 4.2.6 `file_md5` Uniqueness — LOW

The conditional unique index `idx_scan_tasks_md5` uses `postgresql_where=file_md5.isnot(None)`, which is PostgreSQL-specific. If multi-database support is ever needed, this won't port.

#### 4.2.7 `db/session.py` Exposes Destructive Operations — LOW

`init_db()` and `drop_db()` are publicly callable. `drop_db()` should be guarded (e.g., only in development, or require an explicit confirmation parameter).

---

## 5. Environment Management Practices

### 5.1 Exposed Secrets in `.env` — CRITICAL

The `.env` file at the project root contains real secrets (Bailian API key). While .gitignore excludes it, the file exists on disk and could be leaked through backups, screen sharing, logs, or accidental commits.

### 5.2 `.env.example` Is Incomplete — HIGH

`.env.example` is missing **8 fields** that exist in `.env`:

| Missing Field | `.env` Line |
|---|---|
| `OCR_ENGINE_TYPE` | 39 |
| `BAILIAN_API_KEY` | 48 |
| `BAILIAN_OCR_BASE_URL` | 49 |
| `BAILIAN_OCR_MODEL` | 50 |
| `BAILIAN_OCR_MAX_PIXELS` | (settings default) |
| `BAILIAN_OCR_MIN_PIXELS` | (settings default) |
| `BAILIAN_OCR_TIMEOUT` | (settings default) |
| `OCR_CONFIDENCE_THRESHOLD` | (settings default) |

**Impact**: New developers cannot discover all available configuration options from `.env.example`. They may set `OCR_ENGINE_TYPE=bailian` without knowing `BAILIAN_API_KEY` is required.

### 5.3 Secrets in docker-compose.yml — HIGH

All secrets are hardcoded inline in `docker-compose.yml` (database password, MinIO credentials). There is no support for:
- Docker Compose `.env` file for variable substitution
- Docker Secrets (`secrets:` top-level key)
- External secret injection

### 5.4 Strengths

- `.env` correctly excluded in `.gitignore`.
- `.dockerignore` excludes `.env` from Docker builds.
- `pydantic-settings` with `case_sensitive=False` allows flexible env var naming.
- Settings use `extra="ignore"` to prevent unknown env vars from crashing.

---

## 6. Documentation Gaps

### 6.1 `.env.example` — HIGH (see 5.2)

Missing 8 configuration fields. No comments indicating which fields are required vs. optional, or safe defaults for production.

### 6.2 Setup / Deployment Guide — MEDIUM

- No `README.md` referenced in the project root.
- No documentation on:
  - How to generate secure passwords for production
  - How to provision the database
  - How to set up MinIO buckets
  - Migration from development to production configuration
- `docs/` directory only contains an empty `__init__.py`.

### 6.3 Configuration Reference — LOW

No single document describes all configuration keys, their types, defaults, and constraints. While `settings.py` type annotations serve as partial documentation, a human-readable reference is missing.

---

## Summary of Findings by Severity

| # | Finding | Severity | Section |
|---|---|---|---|
| 1 | Hardcoded database password `scanstruct123` in 5+ locations | CRITICAL | 1.1 |
| 2 | Real Bailian API key exposed in `.env` | CRITICAL | 1.4 |
| 3 | No multi-stage Docker builds — build deps in runtime image | CRITICAL | 3.1 |
| 4 | Containers run as root — no non-root user | CRITICAL | 3.2 |
| 5 | MinIO uses well-known default credentials | HIGH | 1.2 |
| 6 | No cross-field validation (bailian key required when engine=bailian) | HIGH | 2.1 |
| 7 | `.env.example` missing 8 configuration fields | HIGH | 5.2 |
| 8 | Secrets hardcoded inline in `docker-compose.yml` | HIGH | 5.3 |
| 9 | Redis has no authentication configured | MEDIUM | 1.3 |
| 10 | No API authentication enforcement in production mode | MEDIUM | 1.5 |
| 11 | Missing range/bounds validators on numeric fields | MEDIUM | 2.2 |
| 12 | Missing URL format validators | MEDIUM | 2.3 |
| 13 | No HEALTHCHECK in Dockerfiles | MEDIUM | 3.3 |
| 14 | MinIO uses `:latest` floating tag | MEDIUM | 3.4 |
| 15 | `Numeric(5,4)` precision inappropriate for confidence scores | MEDIUM | 4.2.1 |
| 16 | Missing `UNIQUE(task_id, step_name)` on task_steps | MEDIUM | 4.2.2 |
| 17 | No CHECK constraints on status fields | MEDIUM | 4.2.3 |
| 18 | No setup/deployment documentation | MEDIUM | 6.2 |
| 19 | `parse_retry_delays` validator lacks error context | LOW | 2.4 |
| 20 | `app_env` / `ocr_engine_type` not constrained to enums | LOW | 2.5 |
| 21 | `scan_files` missing `updated_at` timestamp | LOW | 4.2.4 |
| 22 | No composite index on `(task_id, file_type)` | LOW | 4.2.5 |
| 23 | `file_md5` unique index uses PostgreSQL-specific syntax | LOW | 4.2.6 |
| 24 | `drop_db()` publicly callable without guard | LOW | 4.2.7 |

**Totals**: 4 CRITICAL, 4 HIGH, 9 MEDIUM, 7 LOW = **24 findings**

---

## Priority Action Items (Top 10)

1. **Rotate the exposed Bailian API key** and remove it from `.env`.
2. **Remove hardcoded database defaults** from `settings.py`; fail fast if not configured.
3. **Add non-root user** to both Dockerfiles.
4. **Implement multi-stage Docker builds** to reduce attack surface.
5. **Add `SecretStr`** for all credential fields in settings.
6. **Add cross-field validation**: bailian API key required when bailian engine is selected.
7. **Complete `.env.example`** with all configuration keys and required/optional annotations.
8. **Move secrets out of `docker-compose.yml`** into a `.env` file or Docker Secrets.
9. **Add Redis password** support to settings and compose.
10. **Add range validators** for numeric fields (`api_port`, `confidence_threshold`, `retention_days`, etc.).
