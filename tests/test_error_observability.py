"""测试日志可观测性工具。"""

import logging
from io import StringIO

import pytest

from capability_runtime.logging_utils import get_logger, log_suppressed_exception


class TestGetLogger:
    """测试 get_logger 函数。"""

    def test_root_logger(self):
        """返回根 logger。"""
        logger = get_logger()
        assert logger.name == "capability_runtime"

    def test_child_logger(self):
        """返回子 logger。"""
        logger = get_logger("runtime")
        assert logger.name == "capability_runtime.runtime"


class TestLogSuppressedException:
    """测试 log_suppressed_exception 函数。"""

    def test_basic_logging(self):
        """基本日志记录。"""
        logger = get_logger()
        logger.setLevel(logging.DEBUG)

        # 捕获日志
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        stream = StringIO()
        handler.stream = stream

        try:
            raise ValueError("test error")
        except ValueError as e:
            log_suppressed_exception(
                context="test_context",
                exc=e,
            )

        output = stream.getvalue()
        assert "suppressed exception in test_context" in output
        assert "ValueError" in output
        assert "test error" in output

        logger.removeHandler(handler)

    def test_with_run_id_and_capability_id(self):
        """包含 run_id 和 capability_id。"""
        logger = get_logger()
        logger.setLevel(logging.DEBUG)

        # 使用自定义 handler 捕获 LogRecord
        class RecordHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records = []

            def emit(self, record):
                self.records.append(record)

        handler = RecordHandler()
        logger.addHandler(handler)

        try:
            raise RuntimeError("runtime error")
        except RuntimeError as e:
            log_suppressed_exception(
                context="agent_adapter",
                exc=e,
                run_id="run-123",
                capability_id="my_agent",
            )

        assert len(handler.records) == 1
        record = handler.records[0]
        assert record.__dict__.get("run_id") == "run-123"
        assert record.__dict__.get("capability_id") == "my_agent"

        logger.removeHandler(handler)

    def test_filters_sensitive_keys(self):
        """过滤敏感字段。"""
        logger = get_logger()
        logger.setLevel(logging.DEBUG)

        # 使用自定义 handler 捕获 LogRecord
        class RecordHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records = []

            def emit(self, record):
                self.records.append(record)

        handler = RecordHandler()
        logger.addHandler(handler)

        try:
            raise ValueError("test")
        except ValueError as e:
            log_suppressed_exception(
                context="test",
                exc=e,
                extra={
                    "password": "secret123",  # 应被过滤
                    "api_key": "key123",  # 应被过滤
                    "safe_field": "visible",  # 应保留
                },
            )

        assert len(handler.records) == 1
        record = handler.records[0]
        # 敏感字段不应出现在 extra 中
        assert "password" not in record.__dict__
        assert "api_key" not in record.__dict__
        # 安全字段应保留
        assert record.__dict__.get("safe_field") == "visible"

        logger.removeHandler(handler)
