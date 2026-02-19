"""
reporting/

执行报告（ExecutionReport）与构建器（ReportBuilder）。

说明：
- v0.2.0 主线以 protocol/runtime 的可复用与可测试为优先；
- reporting 提供最小的“可观测形态”，用于后续与上游 SDK 的事件系统对接；
- 本目录不依赖上游包。
"""

from .builder import ReportBuilder
from .report import ExecutionEvent, ExecutionReport

__all__ = ["ExecutionReport", "ExecutionEvent", "ReportBuilder"]

