# Services Directory Audit Report

**Generated**: 2026-05-14
**Scope**: All 31 `.py` files in `E:\OCRScanStruct\services\` (recursive)
**Test references**: 22 test files in `E:\OCRScanStruct\tests\` (excluding `.venv/`)

---

## 1. Overview

The `services/` directory is organized into 8 sub-packages:

| Package | Files | Primary Purpose |
|---|---|---|
| `exporter/` | 3 | Result export, callbacks, streaming |
| `layout/` | 3 | Page layout detection, reading order, table recognition |
| `ocr/` | 3 | OCR engine abstraction (PaddleOCR + Bailian) |
| `preprocessor/` | 4 | Image enhancement, PDF splitting, text extraction |
| `scan_in/` | 3 | Watch-folder ingestion, validation, upload |
| `storage/` | 1 | MinIO object storage client |
| `structurer/` | 6 | Cross-page merge, header/footer cleanup, heading parsing, list detection, paragraph grouping, quality scoring |
| `pipeline.py` | 1 | Top-level pipeline orchestrator |

---

## 2. Per-Module Assessment

### 2.1 `services/__init__.py`
- **Purpose**: Package marker. **Empty** (blank line only).
- **Code quality**: N/A
- **Type hints**: N/A
- **Error handling**: N/A
- **Stub/Incomplete**: N/A
- **Hardcoded values**: None
- **Performance concerns**: None
- **Test coverage**: No dedicated test needed.

---

### 2.2 `services/pipeline.py` — PipelineOrchestrator

- **Purpose**: Top-level pipeline orchestrator. Dispatches tasks to Celery workers.
- **Code quality**: Clean, brief. Both `run_sync` and `run_async` are near-identical wrappers.
- **Type hints**: **Moderate**. Method signatures have return annotations (`-> result`) but only for `UUID` params. The `task_id` parameter is annotated as `UUID` but `process_scan.delay(str(task_id))` requires `str`. Implicit conversion is fine but inconsistent typing.
- **Docstrings**: **Minimal**. Class and methods have short Chinese docstrings. No parameter/return descriptions.
- **Error handling**: **None**. No try/except. If the Celery worker import fails or the queue is unreachable, the exception propagates unchecked.
- **Stub/Incomplete**: `run_sync` comment mentions "MVP" and "development phase". Both methods do the same thing — `run_sync` calls `.delay()`, `run_async` calls `.apply_async()` with a queue parameter. The distinction is unclear.
- **Hardcoded values**: `queue="scanstruct"` is hardcoded. Should reference settings.
- **Performance concerns**: None (just message dispatch).
- **Test coverage**: **`tests/test_pipeline.py`** — Has a corresponding test.

---

### 2.3 `services/exporter/__init__.py`
- **Purpose**: Package marker. **Empty** (blank line only).
- Same assessment as 2.1.

---

### 2.4 `services/exporter/callback.py` — `send_callback`

- **Purpose**: POSTs structured results back to a business callback URL via HTTP.
- **Code quality**: **Good**. Single-purpose, concise. Uses `httpx.AsyncClient` with a configurable timeout.
- **Type hints**: **Partial**. `callback_url: str` and `task_data: dict` are annotated, but return type `bool` is not. No `from __future__ import annotations`.
- **Docstrings**: **Minimal** — single-line module docstring only. No function docstring.
- **Error handling**: **Broad except**. Catches `Exception` generically and logs a warning. Returns `False` on failure but the caller gets no error detail. The `raise_for_status()` call is inside the try block so HTTP errors are caught indistinguishably.
- **Stub/Incomplete**: None.
- **Hardcoded values**: None directly, but `settings.callback_timeout_seconds` is the only tuning point.
- **Performance concerns**: Creates a new `AsyncClient` per call. For high-throughput, connection pooling should be considered.
- **Test coverage**: **`tests/test_callback.py`** — Has a corresponding test.

---

### 2.5 `services/exporter/json_exporter.py` — `export_json`

- **Purpose**: Serialize a structured dict to JSON file.
- **Code quality**: **Good**. Simple, correct.
- **Type hints**: **Partial**. `structured: dict` and `output_path: Path` annotated. Return type `Path` not in signature. No `from __future__ import annotations`.
- **Docstrings**: **Minimal** — single-line module docstring only.
- **Error handling**: **None**. No try/except. If the directory creation fails or the file cannot be written, exceptions propagate.
- **Stub/Incomplete**: None.
- **Hardcoded values**: `ensure_ascii=False`, `indent=2` are hardcoded.
- **Performance concerns**: None for typical use. Large JSON could be memory-heavy but this is an exporter, not a streaming writer.
- **Test coverage**: **`tests/test_json_exporter.py`** — Has a corresponding test.

---

### 2.6 `services/exporter/stream_publisher.py` — Redis Stream Publishing

- **Purpose**: Publish structured results and progress updates to Redis Pub/Sub channels.
- **Code quality**: **Good to Excellent**. Clean helper functions, well-structured.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `dict[str, Any]`. Functions have full parameter and return type annotations.
- **Docstrings**: **Good**. Module docstring, both `publish_result` and `publish_progress` have full Args/Returns docstrings.
- **Error handling**: **Good**. Each publish operation is wrapped in try/except. Specific logging (info/warning/error at appropriate levels). Returns `bool` to indicate success. However, `r.close()` is not in a `finally` block — if `publish()` raises, the connection is leaked.
- **Stub/Incomplete**: None.
- **Hardcoded values**: Default parameter values (`channel_prefix="scanstruct:result"`, `socket_connect_timeout=2`) are reasonable defaults.
- **Performance concerns**: **Constant reconnection**. `_get_redis()` creates a new `Redis` connection on every call, and `r.close()` closes it. Batching messages through a persistent connection would be more efficient. The comment acknowledges this ("avoid long connections in worker fork").
- **Test coverage**: **`tests/test_stream_publisher.py`** — Has a corresponding test.

---

### 2.7 `services/layout/__init__.py`
- **Purpose**: Package marker. **Empty**.
- Same assessment as 2.1.

---

### 2.8 `services/layout/detector.py` — LayoutDetector

- **Purpose**: Pure-algorithm page layout analysis (text block merging, column detection, table region identification, image gap detection, title marking).
- **Code quality**: **Good**. Well-structured 10-step detection pipeline. Uses dataclasses. Modular helper functions.
- **Type hints**: **Good to Excellent**. `from __future__ import annotations` used. Dataclass typed. Method signatures annotated. Some internal dicts use untyped "dict" but this is reasonable given the data shapes.
- **Docstrings**: **Good**. Module docstring explains approach. Class and method docstrings in Chinese. Helper functions documented.
- **Error handling**: **Moderate**. `detect()` handles empty input gracefullly (returns `[]`). Internal helpers are defensive against missing bbox keys. However, `detect_all_pages` has no try/except and passes a hardcoded default page size `(2480, 3508)` if `page_dimensions` is insufficient.
- **Stub/Incomplete**: None apparent.
- **Hardcoded values**: 
  - `page_width=2480, page_height=3508` (default A4 at 300 DPI) in `detect()` and `detect_all_pages()` — duplicated in multiple places.
  - `0.05`, `0.9`, `0.1`, `0.8` in `_detect_image_gaps` — magic numbers for gap-to-image region conversion.
  - `2.5` and `0.08` in `_detect_columns` — column separation thresholds.
  - `0.15` in `_mark_titles` — centered title threshold.
  - `0.5` confidence for image regions — arbitrary.
  - `0.25` in `_is_table_row` — digit density threshold.
- **Performance concerns**: O(n) single-pass for block merging. Column detection is O(n log n). Acceptable for most document sizes. The `_mark_titles` method imports `re` inside the function repeatedly (called once per region group).
- **Test coverage**: **`tests/test_layout_detector.py`** — Has a corresponding test.

---

### 2.9 `services/layout/reading_order.py` — Reading Order

- **Purpose**: Sort page regions into reading order (single-column top-to-bottom; multi-column: grouped into Y-bands, within-band left-to-right).
- **Code quality**: **Good**. Clear algorithm, modular functions.
- **Type hints**: **Good**. Uses `from __future__ import annotations`. `page_width: int | None = None`, full parameter annotations.
- **Docstrings**: **Good**. Module and function docstrings with Args/Returns.
- **Error handling**: **Fair**. Handles empty input gracefully. Defensive `.get("bbox", [0,0,0,0])` fallbacks consistently used. No try/except for runtime errors.
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `3` — minimum regions for multi-column detection (line 27).
  - `800` — fallback page width (line 43).
  - `2.5` and `0.08` in `_detect_columns_from_regions` — duplicated from `detector.py` `_detect_columns`.
  - `overlap_threshold=0.25` — default parameter.
- **Performance concerns**: None significant. O(n log n) sorting.
- **Test coverage**: **`tests/test_reading_order.py`** — Has a corresponding test.

---

### 2.10 `services/layout/table_recognizer.py` — Table Recognizer

- **Purpose**: Pure-algorithm table structure recognition from OCR results via X/Y coordinate clustering. Builds cells grid and HTML output.
- **Code quality**: **Good**. 7-step algorithm, well-decomposed into helper functions.
- **Type hints**: **Good**. Uses `from __future__ import annotations`. Function signatures annotated. `Optional` used where appropriate.
- **Docstrings**: **Excellent**. Detailed module docstring. `recognize_table` has full docstring including algorithm description, Args, Returns with nested structure description. All helper functions documented.
- **Error handling**: **Moderate**. `recognize_table` handles empty/small input gracefully. `_get_cell_rect` has fallbacks for different bbox formats. No try/except around the main algorithm.
- **Stub/Incomplete**: The `merge_info` parameter in `_build_html_table` is accepted but **never used** (line 78: `merge_info: list[dict] | None = None`). HTML generation is very basic — no colspan/rowspan, no CSS classes for styling, no thead/tbody.
- **Hardcoded values**:
  - `font_height = 20` default (line 53).
  - `1.2` and `0.8` row/column cluster thresholds (lines 138-139).
  - `1.5` global column merge factor (line 174).
  - `200` character truncation limit for HTML display (line 96).
  - `<table class="scanstruct-table" border="1" cellpadding="4" cellspacing="0">` — inline HTML styling, no config.
- **Performance concerns**: `_cluster_1d` is O(n log n) due to sort. Grid construction is O(rows * cols * log(cols)) due to `min(range(...))` per cell. For large tables this could be slow. The global column merging uses `_cluster_1d` on potentially many X values.
- **Test coverage**: **`tests/test_table_recognizer.py`** — Has a corresponding test.

---

### 2.11 `services/ocr/__init__.py`
- **Purpose**: Package marker. **Empty**.
- Same assessment as 2.1.

---

### 2.12 `services/ocr/bailian_engine.py` — BailianOCREngine

- **Purpose**: Adapter for Alibaba Cloud Bailian Qwen-OCR model via OpenAI-compatible API.
- **Code quality**: **Good to Excellent**. Well-encapsulated with clean public API, thorough response parsing (3 fallback strategies), normalization logic.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`, `Path`. All method signatures typed.
- **Docstrings**: **Excellent**. Comprehensive module docstring with usage example. Class and method docstrings. Return format documented inline.
- **Error handling**: **Good**. `load_model()` catches exceptions and sets `_model_loaded = False`. `recognize()` validates preconditions (model loaded, file exists), catches recognition exceptions. `_parse_response` has 3 levels of fallback. However, `recognize_batch` doesn't catch errors per-image — a single failure doesn't abort the batch (pass-through from `recognize()` which returns `[]` on error).
- **Stub/Incomplete**: `recognize_batch` comment says "future optimization for concurrency" — currently sequential. `save_result` and `recognize_batch` are duplicated from `engine.py` (code duplication between engine implementations).
- **Hardcoded values**:
  - `OCR_SYSTEM_PROMPT` and `OCR_SIMPLE_PROMPT` — hardcoded system prompts (strings).
  - `confidence = 0.95` default for parsed results (line 248-250).
  - `confidence = 0.90` default for fallback parsing (line 276).
  - `mime_map` dictionary — hardcoded MIME type mapping.
- **Performance concerns**: `recognize_batch` is **sequential** — for large documents this is a significant bottleneck. Each page also reads the entire image file into memory for base64 encoding. `_image_to_base64_url` reads the entire file synchronously with `open(image_path, "rb").read()`.
- **Test coverage**: **`tests/test_bailian_ocr.py`** and `scripts/test_bailian_ocr.py` — Has corresponding tests.

---

### 2.13 `services/ocr/batch_processor.py` — OCRBatchProcessor

- **Purpose**: Batch process OCR across pages, saving per-page results.
- **Code quality**: **Good**. Clean, straightforward logic.
- **Type hints**: **Good**. Uses `from __future__ import annotations`. All parameters typed.
- **Docstrings**: **Good**. Method docstring includes Returns with nested structure description.
- **Error handling**: **Minimal**. No try/except. If `ocr_engine.recognize_batch` fails, the entire batch fails with no partial recovery. No validation that `page_images` list is non-empty.
- **Stub/Incomplete**: None.
- **Hardcoded values**: `batch_size=10` default. `page_{page_num:04d}.json` filename format.
- **Performance concerns**: Calls `ocr_engine.recognize_batch` which is sequential internally.
- **Test coverage**: **`tests/test_ocr_batch_processor.py`** — Has a corresponding test.

---

### 2.14 `services/ocr/engine.py` — OCREngine & Factory

- **Purpose**: OCR engine abstraction. Wraps PaddleOCR 3.x with EasyOCR fallback. Factory function `get_ocr_engine()` allows switching to Bailian.
- **Code quality**: **Good**. Clean PaddleOCR 3.x adaptation, proper fallback handling.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`. Method signatures typed.
- **Docstrings**: **Good**. Module, class, and factory function docstrings. Usage example in factory function.
- **Error handling**: **Good**. `load_model()` has try/except for ImportError and general exceptions with fallback. `recognize()` checks model readiness, handles exceptions gracefully. Confidence filtering respects `settings.ocr_confidence_threshold`.
- **Stub/Incomplete**: None apparent.
- **Hardcoded values**: 
  - `["ch_sim", "en"]` — hardcoded EasyOCR languages (line 70). Should reference settings.
  - `enable_mkldnn=False` logic is correct but uses a comment about "oneDNN PIR attribute conversion error" — workaround for a specific PaddleOCR bug.
- **Performance concerns**: `recognize_batch` is sequential (same as Bailian engine). Model loading is deferred but permanent once loaded (good).
- **Test coverage**: **No dedicated `test_ocr_engine.py`** found. The engine is tested indirectly through `test_ocr_batch_processor.py` and `test_e2e_workflows.py`.

---

### 2.15 `services/preprocessor/__init__.py`
- **Purpose**: Package marker. **Empty**.
- Same assessment as 2.1.

---

### 2.16 `services/preprocessor/deskew.py` — Deskew Wrapper

- **Purpose**: Thin convenience module that imports `Deskewer` from `image_enhancer.py` and creates a global singleton.
- **Code quality**: **Trivial**. 4 lines of effective code.
- **Type hints**: **None**.
- **Docstrings**: **Minimal** — one-line module docstring.
- **Error handling**: **None**.
- **Stub/Incomplete**: This is essentially a re-export. The module exists only for backward compatibility.
- **Hardcoded values**: None.
- **Performance concerns**: Creates a `Deskewer()` at module level — eager initialization.
- **Test coverage**: No dedicated test. Covered indirectly by image enhancement tests.

---

### 2.17 `services/preprocessor/image_enhancer.py` — ImageEnhancer & Deskewer

- **Purpose**: Image preprocessing (denoising, binarization, black border cropping, deskew/skew correction).
- **Code quality**: **Good**. Two classes with clear responsibilities. Uses OpenCV effectively.
- **Type hints**: **Fair**. Uses `from __future__ import annotations`. Some parameters typed but `enhance()` returns `Path` unannotated. `_crop_black_border` parameter `img: np.ndarray` is typed but return is not.
- **Docstrings**: **Moderate**. Module docstring explains purpose. No per-method docstrings.
- **Error handling**: **Moderate**. `enhance()` checks if image loaded successfully (returns original on failure). `deskew()` similarly handles None image. No try/except for OpenCV operations that could fail on corrupt images.
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `h=10, templateWindowSize=7, searchWindowSize=21` — denoising parameters (line 52).
  - `15` — black border threshold (line 73).
  - `0.02` — crop margin ratio (lines 83-84).
  - `0.3` — minimum deskew angle (line 120).
  - `-45` — angle adjustment threshold (line 117).
  - `INTER_CUBIC, BORDER_REPLICATE` — hardcoded interpolation/border modes.
- **Performance concerns**: OpenCV operations are generally fast. No batch processing.
- **Test coverage**: **No dedicated `test_image_enhancer.py`** found. Covered indirectly.

---

### 2.18 `services/preprocessor/pdf_classifier.py` — PDFClassifier

- **Purpose**: Classify PDFs as text-based or scan-based (image-based).
- **Code quality**: **Good**. Clean dataclass, clear logic.
- **Type hints**: **Good**. Uses `from __future__ import annotations`. `PDFInfo` dataclass typed. Method signatures annotated.
- **Docstrings**: **Moderate**. Module and class docstrings. `classify` has a brief Chinese description.
- **Error handling**: **Good**. Catches `ImportError` for PyMuPDF and provides a reasonable fallback. Catches per-page extraction errors gracefully (logs debug). Catches general exceptions around PyMuPDF operations.
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `5` — max pages to check for text detection (line 44).
  - `100` — character threshold per page (line 52).
  - `0.8` — text ratio threshold for classification (line 59).
- **Performance concerns**: Opens and reads only first 5 pages — efficient.
- **Test coverage**: No dedicated test file. Covered indirectly by end-to-end tests.

---

### 2.19 `services/preprocessor/pdf_splitter.py` — PDFSplitter

- **Purpose**: Split PDF into per-page PNG images at specified DPI.
- **Code quality**: **Good**. Clean API, consistent patterns.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`. Method signatures annotated.
- **Docstrings**: **Moderate**. Module and class docstrings. `split_to_images` has a brief docstring. `split_to_bytes` has no docstring.
- **Error handling**: **Minimal**. No try/except. If PyMuPDF fails to open the PDF, the exception propagates. Page range validation is basic (min/max clamping).
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `dpi=300` default (line 19).
  - `72.0` — base DPI for zoom calculation (PyMuPDF base) — line 46.
  - `page_{page_num + 1:04d}.png` — filename format.
- **Performance concerns**: Sequential page rendering. For large PDFs, this is I/O bound. No parallelization.
- **Test coverage**: **`tests/test_pdf_splitter.py`** — Has a corresponding test.

---

### 2.20 `services/preprocessor/text_pdf_extractor.py` — TextPDFExtractor

- **Purpose**: Fast text extraction from text-based PDFs (bypasses OCR).
- **Code quality**: **Good**. Two extraction modes: plain text and structured (with layout info).
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`. Return types annotated.
- **Docstrings**: **Moderate**. Module and class docstrings. Method docstrings describe purpose.
- **Error handling**: **Minimal**. No try/except. If PyMuPDF fails, the exception propagates. No validation of input `pdf_path`.
- **Stub/Incomplete**: `all_text` in `extract_structured` is accumulated but only used after the loop — could be computed from `pages_data` directly.
- **Hardcoded values**: 
  - `12` — default font size (line 78).
  - `0.8` — heading threshold ratio (line 122).
  - `[:10]` — limit font size distribution to top 10 (line 111).
  - `"bold"`, `"black"` — hardcoded bold detection substrings (line 80).
- **Performance concerns**: Reads all pages into memory. For very large text PDFs, this could be memory-heavy.
- **Test coverage**: No dedicated test. Covered indirectly.

---

### 2.21 `services/scan_in/__init__.py`
- **Purpose**: Package marker. **Empty**.
- Same assessment as 2.1.

---

### 2.22 `services/scan_in/uploader.py` — Task Creation & Upload

- **Purpose**: Compute MD5, deduplicate, upload to MinIO, create DB task record.
- **Code quality**: **Good**. Clean async function with clear flow.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`. All parameters typed. Return type `ScanTask` annotated.
- **Docstrings**: **Moderate**. Module docstring. Function has a numbered-step docstring.
- **Error handling**: **Good**. MD5 deduplication handled. MinIO upload failure sets task status to "failed" with error details and raises. DB commits properly.
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `"watch_folder"` — default scanner_id (line 34).
  - `8192` — MD5 chunk size (line 27).
  - `"raw/{today}/{task_id}_{quote(filename)}"` — object key format (line 62).
  - `"%Y-%m-%d"` — date format (line 61).
  - `"application/pdf"` content type (line 84).
- **Performance concerns**: MD5 computation reads the entire file. For large PDFs this is I/O bound but necessary for deduplication.
- **Test coverage**: **`tests/test_scan_api.py`** — Covered by API tests.

---

### 2.23 `services/scan_in/validator.py` — PDFValidator

- **Purpose**: Multi-stage PDF validation: existence, extension, size, encryption, page count, corruption check, text PDF detection.
- **Code quality**: **Excellent**. Well-structured dataclass for results, clear sequential validation. Early return pattern.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`, `dataclass`. Field types annotated.
- **Docstrings**: **Moderate**. Module and class docstrings. Method has brief description.
- **Error handling**: **Excellent**. Each validation stage has specific error codes and messages. Graceful fallback when PyMuPDF is not installed. Corruption check uses try/except. Top-level try catches unexpected errors.
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `ALLOWED_EXTENSIONS = {".pdf"}` (line 31).
  - `MAX_FILE_SIZE = 100 * 1024 * 1024` — 100MB (line 32).
  - `MAX_PAGES = 500` (line 33).
  - `100` — large document warning threshold (line 121).
  - `3` — pages to check for text PDF (line 151).
  - `50` — character threshold for text PDF check (line 155).
- **Performance concerns**: Opens entire PDF for validation. For very large files, this could be slow.
- **Test coverage**: No dedicated `test_validator.py`. Covered by `test_scan_api.py`.

---

### 2.24 `services/scan_in/watcher.py` — Watch Folder Watcher

- **Purpose**: Filesystem watcher that detects new PDFs, validates them, creates tasks, and moves files to archive/error directories.
- **Code quality**: **Good**. Clear state machine, reasonable file stability check.
- **Type hints**: **Fair**. Uses `from __future__ import annotations`. Some method signatures annotated. `_move_to_error` and `_move_to_archive` params untyped. `on_created` event untyped.
- **Docstrings**: **Moderate**. Module and class docstrings. Helper functions documented.
- **Error handling**: **Good**. `_handle_new_file` has full try/except. `_move_to_error` and `_move_to_archive` catch move failures. `_is_file_stable` catches OSError. File deduplication via `_processing` set.
- **Stub/Incomplete**: `on_created` uses `asyncio.create_task()` but if no event loop is running, this will fail — the watcher should ensure a loop context.
- **Hardcoded values**: 
  - `STABLE_CHECK_INTERVAL = 2.0` seconds (line 23).
  - `STABLE_CHECK_COUNT = 2` (line 24).
  - `sleep(1)` — main loop polling interval (line 164).
  - `watch_dir` scanner_id extraction uses path manipulation (line 109).
- **Performance concerns**: `time.sleep(STABLE_CHECK_INTERVAL)` is a **blocking** call inside an async handler (line 43-44). This will block the event loop. Should use `asyncio.sleep`. The main loop uses `time.sleep(1)` which is acceptable since it's the main blocking thread.
- **Test coverage**: No dedicated `test_watcher.py`. Covered indirectly.

---

### 2.25 `services/storage/__init__.py`
- **Purpose**: Package marker. **Empty**.
- Same assessment as 2.1.

---

### 2.26 `services/storage/minio_client.py` — MinioClient

- **Purpose**: MinIO object storage client wrapper (upload, download, delete, presigned URLs, bucket management).
- **Code quality**: **Good to Excellent**. Clean encapsulation, lazy initialization, comprehensive operation set.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`. All method signatures typed.
- **Docstrings**: **Moderate**. Module docstring. Methods have brief single-line descriptions. No detailed Args/Returns docs.
- **Error handling**: **Good**. Each operation catches `S3Error` (MinIO's exception class). Upload/download methods raise on failure. `delete_object` logs warning (non-critical). `object_exists` returns bool. `delete_task_objects` uses per-bucket try/except.
- **Stub/Incomplete**: None.
- **Hardcoded values**: `expires=3600` default for presigned URLs.
- **Performance concerns**: Lazy client initialization is correct. No connection pooling configuration. `delete_task_objects` uses `list_objects` with `recursive=True` which could be slow for many objects.
- **Test coverage**: No dedicated `test_minio_client.py`. Covered by integration/API tests.

---

### 2.27 `services/structurer/__init__.py`
- **Purpose**: Package marker. **Empty**.
- Same assessment as 2.1.

---

### 2.28 `services/structurer/cross_page_merger.py` — Cross-Page Merger

- **Purpose**: Detect and merge paragraphs that span page boundaries.
- **Code quality**: **Good**. Regex-based detection, two API surfaces (paged and flat).
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`, `| None` syntax. All function signatures typed.
- **Docstrings**: **Good**. Module docstring explains the approach. Both merge functions have full Args/Returns docstrings.
- **Error handling**: **Minimal**. No try/except. Guards against empty input. No validation of `page_boundaries` consistency in `merge_cross_page_flat`.
- **Stub/Incomplete**: None apparent.
- **Hardcoded values**: 
  - Regex patterns (`TERMINAL_PUNCTUATION`, `PAGE_NUMBER_PATTERN`, etc.) are hardcoded class-level constants — acceptable for NLP patterns.
  - `setdefault("cross_page", [])` key name should be a module-level constant.
- **Performance concerns**: `merge_cross_page_flat` modifies a list in-place with `.pop()` which is O(n). When multiple pages merge, accumulated pop operations add O(n^2) worst case.
- **Test coverage**: **`tests/test_cross_page_merger.py`** — Has a corresponding test.

---

### 2.29 `services/structurer/header_footer_cleaner.py` — Header/Footer Cleaner

- **Purpose**: Detect and remove repeating headers, footers, and page numbers across pages.
- **Code quality**: **Good**. Well-structured three-pass algorithm. Uses sequence matching for fuzzy text comparison.
- **Type hints**: **Good**. Uses `from __future__ import annotations`. All function signatures typed.
- **Docstrings**: **Good**. Module and function docstrings. `clean_headers_footers` has full strategy description, Args, Returns.
- **Error handling**: **Moderate**. Guards against empty input and small page counts. No try/except for SequenceMatcher or regex operations. Dictionary keys may change during iteration (`list(header_candidates.keys())`) — this is handled but subtly.
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `3508` — default A4 height at 300dpi (line 102).
  - `0.05` — header position ratio (line 51).
  - `0.92` — footer position ratio (line 63).
  - `80` — header absolute position pixels (line 55).
  - `120` — footer absolute position pixels (line 66).
  - `3` — minimum pages for pattern detection (line 97).
  - `0.3` — minimum page ratio for cleanup (line 165).
  - `0.7` — default similarity threshold (line 75).
- **Performance concerns**: O(pages * blocks) per pass. Three passes. Fuzzy string matching via `SequenceMatcher` is O(n*m) per comparison. Could be slow for very large documents (>100 pages with many blocks per page).
- **Test coverage**: **`tests/test_header_footer_cleaner.py`** — Has a corresponding test.

---

### 2.30 `services/structurer/heading_parser.py` — Heading Parser

- **Purpose**: Detect heading levels based on regex pattern matching (Chinese numbering conventions).
- **Code quality**: **Fair**. Very short (27 lines). Two functions.
- **Type hints**: **Partial**. `parse_headings` accepts `list[dict]` and returns `list[dict]`. `detect_heading_level` returns `int | None` — good. No `from __future__ import annotations`.
- **Docstrings**: **Minimal** — one-line module docstring only. No function docstrings.
- **Error handling**: **None**. No try/except. No input validation. If `re.match` raises, it propagates.
- **Stub/Incomplete**: **Significantly incomplete**. The heading detection is **regex-only** — it doesn't use font size, bold status, or document position, even though the text PDF extractor provides this information. The `HEADING_PATTERNS` dictionary covers Chinese document conventions but has no support for:
  - Western heading patterns (e.g., "Chapter 1", "Section 1.1")
  - Font-size-based detection (available from PDF extraction)
  - Centered text detection 
  - Bold text heuristics
  - Position-based heuristics (first line of page, after page break)
- **Hardcoded values**: All `HEADING_PATTERNS` regex patterns are hardcoded class-level constants.
- **Performance concerns**: O(blocks * patterns) — negligible.
- **Test coverage**: **`tests/test_heading_parser.py`** — Has a corresponding test.

---

### 2.31 `services/structurer/list_detector.py` — List Detector

- **Purpose**: Detect numbered, bulleted, lettered, and circled-number lists from text blocks.
- **Code quality**: **Good**. Well-structured detection with continuation handling, indent level calculation, and bounding box extension.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`. Functions annotated. `_match_list_item` has a good union return type.
- **Docstrings**: **Good**. Module, function docstrings with Args descriptions.
- **Error handling**: **Moderate**. Handles empty input. Defensive `.get()` accessors throughout. No try/except. The `_extend_bbox` function mutates `list_bbox` in-place via `.clear() + .extend()` which is fragile.
- **Stub/Incomplete**: None.
- **Hardcoded values**: 
  - `20` — indent threshold for level 0 (line 86).
  - `40` — indent pixels per level (line 88).
  - `3` — max indent level (line 88).
  - `10` — continuation alignment tolerance (line 217).
  - All `LIST_PATTERNS` and `CONTINUATION_PATTERN` regexes are hardcoded.
  - Terminal punctuation characters: `('。', '！', '？', '.', '!', '?')` (line 207).
- **Performance concerns**: `_match_list_item` loops through all patterns for each block — O(blocks * patterns). Acceptable for typical documents.
- **Test coverage**: **`tests/test_list_detector.py`** — Has a corresponding test.

---

### 2.32 `services/structurer/paragraph_grouper.py` — Paragraph Grouper

- **Purpose**: Group text blocks into paragraphs under heading hierarchy. Builds structured document tree.
- **Code quality**: **Good**. Three-pass algorithm: paragraph merging, heading-aware grouping, hierarchy construction. Helper functions for paragraph splitting and tree building.
- **Type hints**: **Good**. Uses `from __future__ import annotations`, `Optional`. Most function signatures annotated.
- **Docstrings**: **Good**. Module docstring. `group_paragraphs` has full Args/Returns docstring. Internal helpers have brief descriptions.
- **Error handling**: **Moderate**. Handles empty input gracefully. Defensive `.get()` accessors consistently used. No try/except for runtime issues.
- **Stub/Incomplete**: The heading nesting logic (`_build_hierarchy`) only supports a single pass — deeply nested structures with interspersed siblings may not be correctly handled. The `headings` parameter in `group_paragraphs` duplicates functionality from `heading_parser.py` (blocks can already carry `heading_level`).
- **Hardcoded values**:
  - `80` — paragraph merge gap threshold in pixels (line 85). Assumes 300dpi but not configurable.
  - `\d{1,4}` and regex patterns for page number detection duplicated from `header_footer_cleaner.py` and `cross_page_merger.py`.
  - `max()` divisions for confidence averaging — reimplements logic found elsewhere.
- **Performance concerns**: `_split_into_paragraphs` sorts all blocks O(n log n). `_build_hierarchy` uses a stack-based approach O(n). Acceptable.
- **Test coverage**: **`tests/test_paragraph_grouper.py`** — Has a corresponding test.

---

### 2.33 `services/structurer/quality_scorer.py` — Quality Scorer

- **Purpose**: Multi-dimensional quality scoring of structured documents (OCR confidence, structure completeness, heading quality, data quality, anomaly detection).
- **Code quality**: **Good**. Well-structured 5-dimensional weighted scoring system. Uses nested functions for tree traversal.
- **Type hints**: **Good**. Uses `from __future__ import annotations`. All functions and parameters typed.
- **Docstrings**: **Good**. Module, function docstrings with Args/Returns. Weight documentation inline.
- **Error handling**: **Moderate**. Default parameter values `{}` and `[]` handle None inputs. `_score_anomaly_detection` catches exceptions in stdev calculation (line 242). No try/except around other scoring functions.
- **Stub/Incomplete**: None.
- **Hardcoded values**:
  - Dimension weights: `0.35, 0.25, 0.20, 0.10, 0.10` (lines 312-317).
  - `0.6` — low confidence threshold (line 26).
  - `0.2` — penalty multiplier (line 28).
  - `0.4, 0.3, 0.2, 0.1` — structure scoring increments (lines 55-67).
  - `0.2` — paragraph scoring (line 74).
  - `5` — minimum paragraphs for bonus (line 78).
  - `0.2, 0.5` — orphan ratio thresholds (lines 86-92).
  - `0.8, 0.6` — orphan penalty multipliers (lines 89, 91).
  - `0.7` — base heading quality score (line 113).
  - `0.05` — level skip penalty (line 126).
  - `0.1` — uniform level penalty (line 152).
  - `0.5` — base data quality score (line 168).
  - `0.15, 0.1` — list/table score increments (lines 173-193).
  - `0.3, 0.1` — anomaly penalties (lines 227-230, 248).
  - `0.2` — high confidence variance threshold (line 239).
  - `0.3` — very low confidence threshold (line 246).
  - `0.3` — empty page ratio threshold (line 226).
  - `0.5, 0.3` — overall quality warning thresholds (lines 362-366).
- **Performance concerns**: `_score_heading_quality` uses nested functions `check_levels` and `collect_levels` that traverse the tree twice. `_max_heading_depth` traverses the tree once more. Could be combined into a single pass.
- **Test coverage**: **`tests/test_quality_scorer.py`** — Has a corresponding test.

---

## 3. Cross-Cutting Findings

### 3.1 Test Coverage Summary

| Service File | Test File | Coverage |
|---|---|---|
| `pipeline.py` | `tests/test_pipeline.py` | Yes |
| `exporter/callback.py` | `tests/test_callback.py` | Yes |
| `exporter/json_exporter.py` | `tests/test_json_exporter.py` | Yes |
| `exporter/stream_publisher.py` | `tests/test_stream_publisher.py` | Yes |
| `layout/detector.py` | `tests/test_layout_detector.py` | Yes |
| `layout/reading_order.py` | `tests/test_reading_order.py` | Yes |
| `layout/table_recognizer.py` | `tests/test_table_recognizer.py` | Yes |
| `ocr/bailian_engine.py` | `tests/test_bailian_ocr.py` | Yes |
| `ocr/batch_processor.py` | `tests/test_ocr_batch_processor.py` | Yes |
| `ocr/engine.py` | No dedicated test | **MISSING** |
| `preprocessor/deskew.py` | No dedicated test | **MISSING** |
| `preprocessor/image_enhancer.py` | No dedicated test | **MISSING** |
| `preprocessor/pdf_classifier.py` | No dedicated test | **MISSING** |
| `preprocessor/pdf_splitter.py` | `tests/test_pdf_splitter.py` | Yes |
| `preprocessor/text_pdf_extractor.py` | No dedicated test | **MISSING** |
| `scan_in/uploader.py` | `tests/test_scan_api.py` (indirect) | Partial |
| `scan_in/validator.py` | No dedicated test | **MISSING** |
| `scan_in/watcher.py` | No dedicated test | **MISSING** |
| `storage/minio_client.py` | No dedicated test | **MISSING** |
| `structurer/cross_page_merger.py` | `tests/test_cross_page_merger.py` | Yes |
| `structurer/header_footer_cleaner.py` | `tests/test_header_footer_cleaner.py` | Yes |
| `structurer/heading_parser.py` | `tests/test_heading_parser.py` | Yes |
| `structurer/list_detector.py` | `tests/test_list_detector.py` | Yes |
| `structurer/paragraph_grouper.py` | `tests/test_paragraph_grouper.py` | Yes |
| `structurer/quality_scorer.py` | `tests/test_quality_scorer.py` | Yes |

Plus integration tests: `tests/test_e2e_workflows.py`, `tests/test_api.py`, `tests/test_scan_api.py`.

**Summary**: 15/25 service modules have dedicated tests. 8 are missing (notably OCR engine, preprocessor/image pipeline, MinIO client, watch dir watcher). 2 are covered only indirectly.

### 3.2 Type Hints Completeness

| Rating | Count | Files |
|---|---|---|
| Excellent | 0 | — |
| Good | 20 | Most files use `from __future__ import annotations` and typed signatures |
| Partial/Fair | 8 | `callback.py`, `json_exporter.py`, `image_enhancer.py`, `deskew.py`, `heading_parser.py`, `watcher.py` (partial) |
| None | 3 | All 3 `__init__.py` files (expected) |

### 3.3 Docstrings Completeness

| Rating | Count | Files |
|---|---|---|
| Excellent | 3 | `bailian_engine.py`, `engine.py`, `table_recognizer.py` |
| Good | 10 | Stream publisher, layout detector, reading order, cross_page_merger, header_footer_cleaner, list_detector, paragraph_grouper, quality_scorer, batch_processor, structurer modules |
| Minimal | 15 | Pipeline, callback, json_exporter, image_enhancer, deskew, pdf_classifier, pdf_splitter, text_pdf_extractor, heading_parser, uploader, validator, watcher, minio_client |
| None | 3 | All `__init__.py` files |

### 3.4 Error Handling Robustness

| Rating | Count | Files |
|---|---|---|
| Excellent | 1 | `validator.py` (specific error codes, graceful degradation) |
| Good | 11 | `bailian_engine.py`, `stream_publisher.py`, `pdf_classifier.py`, `uploader.py`, `watcher.py`, `minio_client.py`, `engine.py` (load), `callback.py` (partial), `layout/detector.py` (partial) |
| Moderate | 5 | `table_recognizer.py`, `header_footer_cleaner.py`, `list_detector.py`, `quality_scorer.py`, `img_enhancer.py` |
| Minimal/None | 4 | `pipeline.py`, `json_exporter.py`, `deskew.py`, `heading_parser.py`, `text_pdf_extractor.py`, `cross_page_merger.py` |

**Notable gap**: `pipeline.py` (the top-level orchestrator) has **zero** error handling.

### 3.5 Hardcoded Values / Magic Numbers

Widespread issue. Common patterns of hardcoded values:
- **Page dimensions**: `2480 x 3508` (A4 at 300dpi) appears in layout `detector.py`, `reading_order.py`, `header_footer_cleaner.py`
- **DPI-related thresholds**: `300` DPI, `72` base DPI in `pdf_splitter.py`, `80` pixel gap thresholds assuming 300dpi in multiple files
- **Page number regex patterns**: Duplicated across `cross_page_merger.py`, `header_footer_cleaner.py`, `paragraph_grouper.py`
- **Confidence defaults**: `0.95` (Bailian), `0.90` (fallback), `0.5` (image regions) — scattered across engine implementations
- **Structural thresholds**: `0.8`, `0.25`, `2.5`, `0.05`, `0.92` — dozens of undocumented magic numbers in scoring and detection algorithms

**Recommendation**: Extract to a `services/constants.py` or `config/thresholds.py` module.

### 3.6 Performance Concerns (ranked by severity)

1. **Sequential OCR batching** (`engine.py`, `bailian_engine.py`): All `recognize_batch` methods process pages sequentially. For Bailian (API), this adds latency proportional to page count. For PaddleOCR (local), GPU utilization is wasted.
2. **Redis connection per publish** (`stream_publisher.py`): Creates and closes a Redis connection for each `publish_result`/`publish_progress` call. A connection pool should be used.
3. **Blocking sleep in async handler** (`watcher.py` line 43): `time.sleep(2.0)` blocks the event loop. Should use `asyncio.sleep()`.
4. **O(n^2) pop operations** (`cross_page_merger.py`): List pop inside a loop creates quadratic worst case.
5. **Full-image base64 encoding** (`bailian_engine.py`): Entire page image read into memory for encoding.
6. **Sequential PDF rendering** (`pdf_splitter.py`): Pages rendered one at a time with no parallelism.

### 3.7 Incomplete / Stub Implementations

1. **`heading_parser.py`** — Most significant stub. Relies entirely on regex patterns with no font-size, bold, or position heuristics, despite this data being available from the PDF/text extraction pipeline.
2. **`pipeline.py`** — `run_sync` and `run_async` are functionally identical aside from config; the sync/async distinction is unclear.
3. **`table_recognizer.py`** — `merge_info` parameter in `_build_html_table` accepted but never used. No colspan/rowspan support. No CSS styling.
4. **`deskew.py`** — Exists solely to re-export `Deskewer` from `image_enhancer.py`. Could be removed.
5. **Image detection in `layout/detector.py`** — Returns regions with hardcoded `confidence=0.5`. No actual image content detection — purely gap-based heuristics.
6. **`bailian_engine.py`** `recognize_batch` — Marked "future optimization for concurrency" in a comment. Currently sequential.

### 3.8 Code Duplication

- **`save_result`**: Identical implementations in both `OCREngine` (engine.py:153-158) and `BailianOCREngine` (bailian_engine.py:175-180).
- **`recognize_batch`**: Identical sequential loop pattern in both OCR engine classes.
- **Page number regex**: `r'^\d{1,4}$'` repeated in `cross_page_merger.py`, `header_footer_cleaner.py`, `paragraph_grouper.py`.
- **Bbox format handling**: `isinstance(bbox[0], list)` logic duplicated across `layout/detector.py`, `reading_order.py`, `table_recognizer.py`, `header_footer_cleaner.py`, `list_detector.py`, `paragraph_grouper.py`. Should be a shared utility (`services/utils/bbox.py`).
- **`_get_cell_rect`** / **`_bbox_to_rect`**: Similar but not identical bounding box conversion in `table_recognizer.py` and `layout/detector.py`.
- **Column detection**: `_detect_columns` (detector.py:67) and `_detect_columns_from_regions` (reading_order.py:90) have near-identical gap-based column detection logic.

### 3.9 Import Patterns

- **Lazy imports**: Several files use lazy imports inside functions (`import cv2`, `import fitz`, `import re`). This is a good pattern for optional dependencies (PyMuPDF, OpenCV) but inconsistent — `re` and `statistics` are standard library and should be at module level.
- **Circular dependency risk**: `pipeline.py` imports from `worker.tasks` inside a function (lazy), which avoids import-time circularity. `engine.py` imports from `bailian_engine.py` inside `get_ocr_engine()` — also correct lazy pattern for avoiding import loops.
- **`import re`** inside functions: `layout/detector.py` line 302, `quality_scorer.py` line 236 — should be at module level.

---

## 4. Module-Level Singleton Pattern

Many modules create global singletons at module level:

```python
ocr_engine = get_ocr_engine()          # engine.py:190
bailian_ocr_engine = BailianOCREngine() # bailian_engine.py:282
minio_client = MinioClient()            # minio_client.py:172
pdf_validator = PDFValidator()          # validator.py:163
layout_detector = LayoutDetector()      # detector.py:355
text_extractor = TextPDFExtractor()     # text_pdf_extractor.py:137
deskewer = Deskewer()                   # deskew.py:6
```

This pattern creates module import-time side effects (e.g., `get_ocr_engine()` reads settings at import time). It's convenient but:
- Makes testing harder (can't easily inject mocks)
- Forces initialization at import time even if unused
- Can cause initialization order issues

**Recommendation**: Replace with a dependency injection container or at minimum a `get_*()` factory pattern with singleton caching (like `get_ocr_engine()` already does).

---

## 5. Summary Statistics

| Metric | Value |
|---|---|
| Total service files | 31 |
| Non-empty source files | 23 |
| Empty `__init__.py` files | 8 |
| Total ~lines of code | ~3,500 |
| Files with `from __future__ import annotations` | 18 (78% of non-empty) |
| Files with dedicated tests | 15 (65% of non-empty) |
| Files with NO test coverage | 8 (35%) |
| Files with excellent docstrings | 3 (13%) |
| Files with good docstrings | 10 (43%) |
| Files with good error handling | 11 (48%) |
| Files with minimal/no error handling | 6 (26%) |

---

## 6. Priority Recommendations

### High Priority

1. **Add error handling to `pipeline.py`** — the orchestrator should catch and report failures gracefully.
2. **Add dedicated tests for `ocr/engine.py`** — the core OCR engine has no direct test.
3. **Add dedicated tests for `storage/minio_client.py`** — all file persistence depends on this.
4. **Complete `heading_parser.py`** — it's currently regex-only and misses most real-world headings.
5. **Fix blocking `time.sleep()` in `watcher.py`** — replace with `asyncio.sleep()`.

### Medium Priority

6. **Extract duplicate bbox handling** into a shared utility module.
7. **Consolidate hardcoded numeric thresholds** into a config file.
8. **Implement concurrent OCR batching** for Bailian engine.
9. **Add Redis connection pooling** in `stream_publisher.py`.
10. **Add dedicated tests for preprocessor modules** (image_enhancer, pdf_classifier, text_pdf_extractor, validator, watcher).

### Low Priority

11. Replace module-level singletons with a DI container.
12. Remove `deskew.py` re-export wrapper.
13. Move `import re` and `import statistics` to module level.
14. Upgrade `_build_html_table` in `table_recognizer.py` to support colspan/rowspan.
15. Add full docstrings to all modules currently rated "Minimal".
