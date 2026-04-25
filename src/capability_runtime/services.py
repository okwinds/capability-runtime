from __future__ import annotations

"""Runtime 内部服务协议与可复用辅助函数。"""

import inspect
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from skills_runtime.core.errors import FrameworkIssue

from .config import RuntimeConfig
from .logging_utils import log_suppressed_exception
from .protocol.capability import CapabilityResult, CapabilityStatus
from .protocol.context import ExecutionContext
from .registry import CapabilityRegistry
from .types import NodeReport


@runtime_checkable
class RuntimeServices(Protocol):
    """Runtime 对内服务协议（供 adapters/engines 依赖）。"""

    @property
    def config(self) -> RuntimeConfig:
        """运行时配置。"""

    @property
    def registry(self) -> CapabilityRegistry:
        """能力注册表。"""

    async def execute_capability(
        self,
        *,
        spec: Any,
        input: Dict[str, Any],
        context: ExecutionContext,
    ) -> CapabilityResult:
        """执行能力（Runtime 内部分发）。"""

    def create_sdk_agent(
        self,
        *,
        llm_config: Optional[Dict[str, Any]] = None,
        prompt_profile: Optional[str] = None,
        precomposed_messages: Optional[list[dict[str, Any]]] = None,
    ) -> Any:
        """
        创建 per-run SDK Agent。

        参数：
        - llm_config：可选 LLM 覆写配置
        - prompt_profile：可选 SDK prompt profile
        - precomposed_messages：可选最终 provider messages 覆写
        """

    def preflight(self) -> list[FrameworkIssue]:
        """执行 skills preflight。"""

    def build_fail_closed_report(
        self,
        *,
        run_id: str,
        status: str,
        reason: Optional[str],
        completion_reason: str,
        meta: Dict[str, Any],
    ) -> NodeReport:
        """构造 fail-closed NodeReport。"""

    def redact_issue(self, issue: Any) -> Dict[str, Any]:
        """把 FrameworkIssue 做最小披露归一。"""

    def get_host_meta(self, *, context: ExecutionContext) -> Dict[str, Any]:
        """读取 host 保留元数据。"""

    def call_callback(self, cb: Any, *args: Any) -> None:
        """兼容调用 callback。"""

    def emit_agent_event_taps(self, *, ev: Any, context: ExecutionContext, capability_id: str) -> None:
        """分发 AgentEvent taps。"""

    def apply_output_validation(
        self,
        *,
        final_output: Any,
        report: NodeReport,
        context: Dict[str, Any],
        output_schema: Optional[Any] = None,
    ) -> None:
        """执行输出校验并写入 NodeReport.meta。"""


def redact_issue(issue: FrameworkIssue) -> Dict[str, Any]:
    """
    把 FrameworkIssue 归一为"可诊断但最小披露"的 dict。

    说明：
    - 避免把 details 原样透传导致泄露或膨胀；
    - 当前仅保留 code/message，并在 details 里保留常见定位字段（若存在）。
    """

    code = str(getattr(issue, "code", "") or "")
    message = str(getattr(issue, "message", "") or "")
    details = getattr(issue, "details", None)
    out: Dict[str, Any] = {"code": code, "message": message}
    if isinstance(details, dict):
        slim: Dict[str, Any] = {}
        for k in ("path", "source", "kind"):
            v = details.get(k)
            if isinstance(v, str) and v:
                slim[k] = v
        if slim:
            out["details"] = slim
    return out


def get_host_meta(*, context: ExecutionContext) -> Dict[str, Any]:
    """
    从 ExecutionContext.bag 中读取 host-meta（保留字段）。

    约定：
    - 该字段为框架保留键，不应与业务输入冲突；
    - 结构：{"session_id": str, "host_turn_id": str, "initial_history": list[dict]}
    """

    raw = context.bag.get("__host_meta__")
    return raw if isinstance(raw, dict) else {}


def call_callback(cb: Any, *args: Any) -> None:
    """
    以"尽量兼容"的方式调用 callback。

    说明：
    - 支持 VAR_POSITIONAL（*args）handler：全量传入；
    - 统计 POSITIONAL_ONLY + POSITIONAL_OR_KEYWORD 类型参数（不含 KEYWORD_ONLY、VAR_KEYWORD）；
    - 若签名/调用失败，抛异常由调用方决定是否吞掉。
    """

    try:
        sig = inspect.signature(cb)
    except Exception as exc:
        # 无法获取签名时回退：尝试全量传入
        log_suppressed_exception(
            context="callback_signature_inspection",
            exc=exc,
            extra={"callback": getattr(cb, "__name__", repr(cb))},
        )
        cb(*args)
        return

    # 检查是否有 VAR_POSITIONAL（*args）
    has_var_positional = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
    if has_var_positional:
        cb(*args)
        return

    # 统计 POSITIONAL 类型参数（POSITIONAL_ONLY + POSITIONAL_OR_KEYWORD）
    positional_params = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]

    # 根据 positional 参数数量决定传入参数
    if len(positional_params) >= len(args):
        cb(*args)
    elif len(positional_params) > 0:
        cb(*args[: len(positional_params)])
    else:
        cb()


def map_node_status(report: NodeReport) -> CapabilityStatus:
    """
    将 NodeReport 控制面状态映射为 CapabilityStatus。

    约束：
    - needs_approval / incomplete 不得折叠为 failed（避免编排误判）。
    """

    if report.status == "success":
        return CapabilityStatus.SUCCESS
    if report.status == "failed":
        return CapabilityStatus.FAILED
    if report.status == "needs_approval":
        return CapabilityStatus.PENDING
    if report.status == "incomplete":
        return CapabilityStatus.CANCELLED if report.reason == "cancelled" else CapabilityStatus.PENDING
    return CapabilityStatus.FAILED
