"""
日志工具模块：提供运行时错误可观测性支持。

设计要点：
- 使用标准库 logging，不引入外部依赖
- 所有静默异常记录到 DEBUG 级别
- 日志包含 exc_info=True 以保留完整堆栈
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

# 模块级 logger
_logger = logging.getLogger("capability_runtime")


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取 capability_runtime 命名空间下的 logger。

    参数：
    - name：可选子模块名，如 "runtime" → "capability_runtime.runtime"

    返回：
    - logging.Logger 实例
    """
    if name:
        return _logger.getChild(name)
    return _logger


def log_suppressed_exception(
    *,
    context: str,
    exc: BaseException,
    run_id: Optional[str] = None,
    capability_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    记录被静默处理的异常（DEBUG 级别）。

    参数：
    - context：异常发生上下文描述（如 "emit_agent_event_taps"）
    - exc：被捕获的异常实例
    - run_id：可选运行 ID
    - capability_id：可选能力 ID
    - extra：可选额外字段

    说明：
    - 使用 DEBUG 级别，避免生产日志量增加
    - 自动包含 exc_info=True 保留堆栈
    - 禁止在 extra 中包含敏感信息（密钥、凭证、完整 payload）
    """
    log_extra: Dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error_message": str(exc)[:200],  # 截断避免日志膨胀
    }
    if run_id:
        log_extra["run_id"] = run_id
    if capability_id:
        log_extra["capability_id"] = capability_id
    if extra:
        # 过滤敏感字段
        safe_extra = {k: v for k, v in extra.items() if k not in _SENSITIVE_KEYS}
        log_extra.update(safe_extra)

    _logger.debug(
        f"suppressed exception in {context}",
        exc_info=exc,
        extra=log_extra,
    )


# 敏感字段黑名单
_SENSITIVE_KEYS = frozenset([
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "authorization",
    "bearer",
    "private_key",
])


__all__ = [
    "get_logger",
    "log_suppressed_exception",
]
