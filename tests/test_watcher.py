"""
Watch Folder 监听器单元测试
覆盖 _is_file_stable、_ensure_dir、ScanWatcherHandler、start_watcher
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# 在导入被测模块前 mock watchdog（用普通类支持正常实例化）
class _FakeFileSystemEventHandler:
    pass

class _FakeObserver:
    def __init__(self): pass
    def schedule(self, *a, **kw): pass
    def start(self): pass
    def stop(self): pass
    def join(self): pass

_mock_wd = MagicMock()
_mock_wd.events = MagicMock()
_mock_wd.events.FileSystemEventHandler = _FakeFileSystemEventHandler
_mock_wd.observers = MagicMock()
_mock_wd.observers.Observer = _FakeObserver

with patch.dict(sys.modules, {
    "watchdog": _mock_wd,
    "watchdog.events": _mock_wd.events,
    "watchdog.observers": _mock_wd.observers,
}):
    import services.scan_in.watcher as _watcher_mod
    from services.scan_in.watcher import (
        _is_file_stable,
        _ensure_dir,
        ScanWatcherHandler,
        start_watcher,
    )


# ════════════════════════════════════════════════════════════
# _is_file_stable
# ════════════════════════════════════════════════════════════

class TestIsFileStable:
    """_is_file_stable 循环 3 次，需连续 2 次大小匹配才返回 True。"""

    @pytest.fixture(autouse=True)
    def _patch_sleep(self):
        with patch.object(_watcher_mod, "asyncio") as mock_aio:
            mock_aio.sleep = AsyncMock()
            yield mock_aio.sleep

    async def test_file_stable_from_start(self):
        """全部 3 轮大小一致 → 稳定"""
        sizes = [1024, 1024, 1024]
        idx = [0]
        def _stat():
            m = MagicMock(); m.st_size = sizes[min(idx[0], len(sizes)-1)]; idx[0] += 1
            return m
        with patch("pathlib.Path.stat", side_effect=_stat):
            assert await _is_file_stable(Path("/f/stable.pdf")) is True

    async def test_file_keeps_changing(self):
        """大小每轮都变 → 不稳定"""
        sizes = [100, 200, 300]
        idx = [0]
        def _stat():
            m = MagicMock(); m.st_size = sizes[min(idx[0], len(sizes)-1)]; idx[0] += 1
            return m
        with patch("pathlib.Path.stat", side_effect=_stat):
            assert await _is_file_stable(Path("/f/changing.pdf")) is False

    async def test_late_stabilization_not_detected(self):
        """前两轮不同、仅最后一轮匹配 → 仍然不稳定"""
        sizes = [512, 1024, 1024]
        idx = [0]
        def _stat():
            m = MagicMock(); m.st_size = sizes[min(idx[0], len(sizes)-1)]; idx[0] += 1
            return m
        with patch("pathlib.Path.stat", side_effect=_stat):
            assert await _is_file_stable(Path("/f/late.pdf")) is False

    async def test_access_error(self):
        with patch("pathlib.Path.stat", side_effect=OSError):
            assert await _is_file_stable(Path("/f/bad.pdf")) is False

    async def test_empty_file(self):
        sizes = [0, 0, 0]
        idx = [0]
        def _stat():
            m = MagicMock(); m.st_size = sizes[min(idx[0], len(sizes)-1)]; idx[0] += 1
            return m
        with patch("pathlib.Path.stat", side_effect=_stat):
            assert await _is_file_stable(Path("/f/empty.pdf")) is True


# ════════════════════════════════════════════════════════════
# _ensure_dir
# ════════════════════════════════════════════════════════════

class TestEnsureDir:
    def test_creates_dir(self):
        with patch("pathlib.Path.mkdir") as m:
            r = _ensure_dir("/tmp/new")
        m.assert_called_once_with(parents=True, exist_ok=True)
        assert isinstance(r, Path)

    def test_existing_dir(self):
        with patch("pathlib.Path.mkdir") as m:
            r = _ensure_dir("/tmp/old")
        m.assert_called_once()
        assert isinstance(r, Path)


# ════════════════════════════════════════════════════════════
# ScanWatcherHandler — helper: 创建已 patch _ensure_dir 的实例
# ════════════════════════════════════════════════════════════

def _make_handler(error_dir="/f/error", archive_dir="/f/archive", watch_dir="/f/watch"):
    """创建 handler 实例，同时 patch settings 和 _ensure_dir"""
    with patch.object(_watcher_mod, "settings") as s:
        s.error_dir = error_dir
        s.archive_dir = archive_dir
        s.watch_dir = watch_dir
        with patch.object(_watcher_mod, "_ensure_dir"):
            return ScanWatcherHandler()


# ════════════════════════════════════════════════════════════
# ScanWatcherHandler.__init__
# ════════════════════════════════════════════════════════════

class TestScanWatcherHandlerInit:
    def test_init(self):
        with patch.object(_watcher_mod, "settings") as s, \
             patch.object(_watcher_mod, "_ensure_dir") as m_ensuredir:
            s.error_dir = "/f/error"
            s.archive_dir = "/f/archive"
            h = ScanWatcherHandler()
            assert h._processing == set()
            assert m_ensuredir.call_count == 2
            m_ensuredir.assert_has_calls([call("/f/error"), call("/f/archive")])


# ════════════════════════════════════════════════════════════
# ScanWatcherHandler.on_created
# ════════════════════════════════════════════════════════════

class TestOnCreated:
    def _event(self, path, is_dir=False):
        e = MagicMock(); e.src_path = path; e.is_directory = is_dir
        return e

    def test_ignores_directory(self):
        h = _make_handler()
        with patch("asyncio.create_task") as m:
            h.on_created(self._event("/w/x.pdf", True))
        m.assert_not_called()

    def test_ignores_non_pdf(self):
        h = _make_handler()
        with patch("asyncio.create_task") as m:
            h.on_created(self._event("/w/x.png"))
        m.assert_not_called()

    def test_ignores_tilde(self):
        h = _make_handler()
        with patch("asyncio.create_task") as m:
            h.on_created(self._event("/w/~tmp.pdf"))
        m.assert_not_called()

    def test_ignores_dotfile(self):
        h = _make_handler()
        with patch("asyncio.create_task") as m:
            h.on_created(self._event("/w/.hid.pdf"))
        m.assert_not_called()

    def test_accepts_pdf(self):
        h = _make_handler()
        with patch("asyncio.create_task") as m:
            h.on_created(self._event("/w/doc.pdf"))
        m.assert_called_once()

    def test_dedup(self):
        h = _make_handler()
        abs_p = str(Path("/w/doc.pdf").absolute())
        h._processing.add(abs_p)
        with patch("asyncio.create_task") as m:
            h.on_created(self._event("/w/doc.pdf"))
        m.assert_not_called()

    def test_case_insensitive(self):
        h = _make_handler()
        with patch("asyncio.create_task") as m:
            h.on_created(self._event("/w/DOC.PDF"))
        m.assert_called_once()


# ════════════════════════════════════════════════════════════
# ScanWatcherHandler._handle_new_file
# ════════════════════════════════════════════════════════════

class TestHandleNewFile:
    @pytest.fixture
    def handler(self):
        return _make_handler()

    @pytest.fixture
    def fp(self):
        return Path("/f/watch/doc.pdf")

    async def test_unstable(self, handler, fp):
        """_is_file_stable → False → move to error"""
        with patch.object(_watcher_mod, "_is_file_stable", new_callable=AsyncMock) as m_stable, \
             patch.object(handler, "_move_to_error") as m_err, \
             patch.object(handler, "_move_to_archive") as m_arc, \
             patch.object(_watcher_mod, "pdf_validator") as m_val, \
             patch.object(_watcher_mod, "create_task_from_file") as m_create:
            m_stable.return_value = False
            await handler._handle_new_file(fp)

        m_stable.assert_called_once_with(fp)
        m_err.assert_called_once_with(fp, "FILE_UNSTABLE")
        m_val.validate.assert_not_called()
        m_create.assert_not_called()
        m_arc.assert_not_called()

    async def test_validation_fails(self, handler, fp):
        fail = MagicMock(is_valid=False, error_code="EMPTY_FILE")

        with patch.object(_watcher_mod, "_is_file_stable", new_callable=AsyncMock) as m_stable, \
             patch.object(handler, "_move_to_error") as m_err, \
             patch.object(handler, "_move_to_archive") as m_arc, \
             patch.object(_watcher_mod, "pdf_validator") as m_val, \
             patch.object(_watcher_mod, "create_task_from_file") as m_create:
            m_stable.return_value = True
            m_val.validate.return_value = fail
            await handler._handle_new_file(fp)

        m_val.validate.assert_called_once_with(fp)
        m_err.assert_called_once_with(fp, "EMPTY_FILE")
        m_create.assert_not_called()

    async def test_validation_none_code(self, handler, fp):
        fail = MagicMock(is_valid=False, error_code=None)
        with patch.object(_watcher_mod, "_is_file_stable", new_callable=AsyncMock) as m_stable, \
             patch.object(handler, "_move_to_error") as m_err, \
             patch.object(handler, "_move_to_archive") as m_arc, \
             patch.object(_watcher_mod, "pdf_validator") as m_val, \
             patch.object(_watcher_mod, "create_task_from_file") as m_create:
            m_stable.return_value = True
            m_val.validate.return_value = fail
            await handler._handle_new_file(fp)
        m_err.assert_called_once_with(fp, "VALIDATION_FAILED")

    async def test_success(self, handler, fp):
        ok = MagicMock(is_valid=True, file_size=2048, page_count=5, is_text_pdf=False)
        t = MagicMock(id="t-1")

        with patch.object(_watcher_mod, "_is_file_stable", new_callable=AsyncMock) as m_stable, \
             patch.object(handler, "_move_to_error") as m_err, \
             patch.object(handler, "_move_to_archive") as m_arc, \
             patch.object(_watcher_mod, "pdf_validator") as m_val, \
             patch.object(_watcher_mod, "create_task_from_file", new_callable=AsyncMock) as m_create, \
             patch.object(_watcher_mod, "settings") as s:
            m_stable.return_value = True
            m_val.validate.return_value = ok
            m_create.return_value = t
            s.watch_dir = "/f/watch"
            await handler._handle_new_file(fp)

        m_create.assert_called_once_with(file_path=fp, scanner_id="watch", file_size=2048)
        m_arc.assert_called_once_with(fp)
        m_err.assert_not_called()

    async def test_exception(self, handler, fp):
        with patch.object(_watcher_mod, "_is_file_stable", new_callable=AsyncMock) as m_stable, \
             patch.object(handler, "_move_to_error") as m_err, \
             patch.object(handler, "_move_to_archive") as m_arc:
            m_stable.side_effect = RuntimeError("boom")
            await handler._handle_new_file(fp)

        m_err.assert_called_once_with(fp, "PROCESSING_ERROR")
        m_arc.assert_not_called()


# ════════════════════════════════════════════════════════════
# ScanWatcherHandler._move_to_error
# ════════════════════════════════════════════════════════════

class TestMoveToError:
    @pytest.fixture
    def handler(self):
        return _make_handler()

    def test_moves_with_prefix(self, handler):
        fp = Path("/f/w/bad.pdf")
        with patch.object(_watcher_mod, "settings") as s, \
             patch.object(_watcher_mod, "shutil") as sh:
            s.error_dir = "/f/error"
            handler._move_to_error(fp, "EMPTY_FILE")
        sh.move.assert_called_once_with(str(fp), str(Path("/f/error/EMPTY_FILE_bad.pdf")))

    def test_silent_on_oserror(self, handler):
        fp = Path("/f/w/bad.pdf")
        with patch.object(_watcher_mod, "settings") as s, \
             patch.object(_watcher_mod, "shutil") as sh:
            s.error_dir = "/f/error"
            sh.move.side_effect = OSError
            handler._move_to_error(fp, "X")  # no raise


# ════════════════════════════════════════════════════════════
# ScanWatcherHandler._move_to_archive
# ════════════════════════════════════════════════════════════

class TestMoveToArchive:
    @pytest.fixture
    def handler(self):
        return _make_handler()

    def test_no_conflict(self, handler):
        fp = Path("/f/w/good.pdf")
        with patch.object(_watcher_mod, "settings") as s, \
             patch.object(_watcher_mod, "shutil") as sh, \
             patch("pathlib.Path.exists", return_value=False):
            s.archive_dir = "/f/archive"
            handler._move_to_archive(fp)
        sh.move.assert_called_once_with(str(fp), str(Path("/f/archive/good.pdf")))

    def test_name_conflict(self, handler):
        fp = Path("/f/w/good.pdf")
        with patch.object(_watcher_mod, "settings") as s, \
             patch.object(_watcher_mod, "shutil") as sh, \
             patch("pathlib.Path.exists", return_value=True), \
             patch.object(_watcher_mod.time, "time", return_value=1700000000.0):
            s.archive_dir = "/f/archive"
            handler._move_to_archive(fp)
        sh.move.assert_called_once_with(str(fp), str(Path("/f/archive/1700000000_good.pdf")))

    def test_silent_on_oserror(self, handler):
        fp = Path("/f/w/good.pdf")
        with patch.object(_watcher_mod, "settings") as s, \
             patch.object(_watcher_mod, "shutil") as sh, \
             patch("pathlib.Path.exists", return_value=False):
            s.archive_dir = "/f/archive"
            sh.move.side_effect = OSError
            handler._move_to_archive(fp)  # no raise


# ════════════════════════════════════════════════════════════
# start_watcher
# ════════════════════════════════════════════════════════════

class TestStartWatcher:
    def test_sets_up_and_starts(self):
        obs_cls = MagicMock()
        obs_inst = MagicMock()
        obs_cls.return_value = obs_inst

        sleeps = []
        def _sleep(s):
            sleeps.append(s)
            if len(sleeps) >= 1:
                raise KeyboardInterrupt()

        with patch.object(_watcher_mod, "Observer", obs_cls), \
             patch.object(_watcher_mod, "_ensure_dir", return_value=Path("/f/w")), \
             patch.object(_watcher_mod.time, "sleep", side_effect=_sleep), \
             patch.object(_watcher_mod, "settings") as s:
            s.watch_dir = "/f/w"; s.error_dir = "/f/e"; s.archive_dir = "/f/a"
            start_watcher()

        obs_cls.assert_called_once()
        obs_inst.schedule.assert_called_once()
        obs_inst.start.assert_called_once()
        obs_inst.stop.assert_called_once()
        obs_inst.join.assert_called_once()

    def test_ensures_all_dirs(self):
        obs_cls = MagicMock(return_value=MagicMock())
        with patch.object(_watcher_mod, "Observer", obs_cls), \
             patch.object(_watcher_mod, "_ensure_dir", return_value=Path("/f/w")) as m_ed, \
             patch.object(_watcher_mod.time, "sleep", side_effect=KeyboardInterrupt), \
             patch.object(_watcher_mod, "settings") as s:
            s.watch_dir = "/f/w"; s.error_dir = "/f/e"; s.archive_dir = "/f/a"
            start_watcher()

        # start_watcher 本身调用 3 次 + handler.__init__ 调用 2 次 = 5 次
        assert m_ed.call_count >= 3
        m_ed.assert_has_calls([call("/f/w"), call("/f/e"), call("/f/a")], any_order=True)
