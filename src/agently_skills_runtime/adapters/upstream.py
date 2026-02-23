"""上游适配与兼容层（集中处理与 `skills-runtime-sdk` 的扩展点对接）。"""
from __future__ import annotations

from typing import Any


def register_agent_tool(*, agent: Any, spec: Any, handler: Any, override: bool = False) -> None:
    """
    向 SDK `Agent` 注册一个“预构造的 ToolSpec + handler”。

    目标：
    - 优先使用上游公开扩展点（`Agent.register_tool(...)`）；
    - 兼容旧版本（仍暴露私有 `_extra_tools`）的最小回退路径；
    - 让 bridge 侧不必在业务逻辑中直接依赖 `_extra_tools` 的内部形态。

    参数：
    - agent：`agent_sdk.core.agent.Agent` 实例（或同形对象）
    - spec：`agent_sdk.tools.protocol.ToolSpec`
    - handler：tool handler（签名需兼容 SDK ToolRegistry）
    - override：是否允许覆盖同名工具（语义与上游对齐）

    返回：
    - None（注册失败将抛异常，供调用方转为可诊断的 FrameworkError/NodeReport）
    """

    fn = getattr(agent, "register_tool", None)
    if callable(fn):
        fn(spec, handler, override=bool(override))
        return

    # 兼容旧版本：允许通过私有字段注入（下游应尽快升级到公开扩展点）。
    extra_tools = getattr(agent, "_extra_tools", None)
    if isinstance(extra_tools, list):
        extra_tools.append((spec, handler))  # type: ignore[call-arg]
        return

    raise AttributeError("Agent has no register_tool() and no _extra_tools list for fallback injection")

