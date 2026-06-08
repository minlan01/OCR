"""
测试案件级并发控制器
"""
import pytest
from unittest.mock import patch, MagicMock


class TestTaskConcurrency:
    """services.utils.task_concurrency 并发控制测试"""

    def test_acquire_first_slot(self):
        """第一个案件应该获得许可"""
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 1

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import try_acquire_case
            assert try_acquire_case() is True
            mock_redis.incr.assert_called_once()

    def test_acquire_up_to_limit(self):
        """第 N 个案件（等于上限）应该获得许可"""
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 3  # _MAX_CONCURRENT_CASES = 3

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import try_acquire_case
            assert try_acquire_case() is True

    def test_reject_over_limit(self):
        """超过上限的案件应该被拒绝"""
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 4  # 超过 _MAX_CONCURRENT_CASES = 3
        mock_redis.decr.return_value = 3

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import try_acquire_case
            assert try_acquire_case() is False
            mock_redis.decr.assert_called_once()

    def test_release_decrements(self):
        """释放应该减少计数"""
        mock_redis = MagicMock()
        mock_redis.decr.return_value = 2

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import release_case
            release_case()
            mock_redis.decr.assert_called_once()

    def test_release_corrects_negative(self):
        """释放时计数器为负应该修正为 0"""
        mock_redis = MagicMock()
        mock_redis.decr.return_value = -1

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import release_case
            release_case()
            mock_redis.set.assert_called_once()

    def test_redis_error_allows_pass(self):
        """Redis 异常时应该放行（降级策略）"""
        import redis as _redis
        mock_redis = MagicMock()
        mock_redis.incr.side_effect = _redis.RedisError("connection refused")

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import try_acquire_case
            assert try_acquire_case() is True  # 降级放行

    def test_redis_error_release_silent(self):
        """Redis 异常时释放应该静默忽略"""
        import redis as _redis
        mock_redis = MagicMock()
        mock_redis.decr.side_effect = _redis.RedisError("connection refused")

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import release_case
            release_case()  # 不抛异常

    def test_first_acquire_sets_ttl(self):
        """第一个计数器应该设置 TTL"""
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 1
        mock_redis.expire.return_value = True

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import try_acquire_case
            try_acquire_case()
            mock_redis.expire.assert_called_once()

    def test_subsequent_acquire_no_ttl(self):
        """非第一个计数器不应该设置 TTL"""
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 2
        mock_redis.expire.return_value = True

        with patch("services.utils.task_concurrency._get_redis", return_value=mock_redis):
            from services.utils.task_concurrency import try_acquire_case
            try_acquire_case()
            mock_redis.expire.assert_not_called()
