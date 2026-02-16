"""
离线 demo：scripted LLM stream → tool_calls → approvals → TriggerFlow runner。

目标：
- 不依赖外网与真实模型 key；
- 验证 SDK 的 tool_calls 闭环 + approvals gate + WAL/事件证据链；
- 复用本仓 bridge 组件（AgentlyChatBackend + TriggerFlow tool + NodeReportBuilder）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_sdk.config.defaults import load_default_config_dict
from agent_sdk.config.loader import load_config_dicts
from agent_sdk.core.agent import Agent

from agently_skills_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend
from agently_skills_runtime.adapters.triggerflow_tool import TriggerFlowRunner, TriggerFlowToolDeps, build_triggerflow_run_flow_tool


class _FakeRequestData:
    """用于 Fake requester 的最小 request_data 形态（避免触网）。"""

    def __init__(self) -> None:
        self.data = {"messages": []}
        self.request_options = {}
        self.request_url = "http://example.invalid"
        self.headers = {}
        self.client_options = {}
        self.stream = True


class _ScriptedRequester:
    """
    按“每次 request_model 调用”切换脚本。

    说明：
    - Agent 会在 tool 执行后再次请求模型以生成最终输出；
    - 因此 demo 需要至少两段脚本（tool_calls → stop）。
    """

    def __init__(self, scripts: List[List[Tuple[str, Any]]]) -> None:
        self._scripts = [list(s) for s in scripts]
        self._call_idx = 0

    def generate_request_data(self) -> _FakeRequestData:
        return _FakeRequestData()

    async def request_model(self, _request_data: Any):
        if self._call_idx >= len(self._scripts):
            # 若脚本不足，则回退为直接 stop
            yield ("message", '{"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}')
            yield ("message", "[DONE]")
            return

        script = self._scripts[self._call_idx]
        self._call_idx += 1
        for item in script:
            yield item


def build_demo_backend(*, flow_name: str = "demo_echo", input_obj: Any = None) -> AgentlyChatBackend:
    """
    构造离线 demo backend（scripted stream）。

    行为：
    - 第一次请求：要求执行 tool `triggerflow_run_flow`
    - 第二次请求：输出文本并 stop（完成）
    """

    call_id = "call_demo_1"
    # 为避免落 input 明文，这里固定把 input 设为 "<redacted>"（demo 关注闭环，不关注 payload 内容）。
    args_json = "{" + f'\\"flow_name\\":\\"{flow_name}\\",\\"input\\":\\"<redacted>\\"' + "}"

    # 为避免落 input 明文，这里不把 input_obj 的 JSON 明文塞进 arguments。
    # 真实场景下 arguments 会携带 input；demo 的关键在于验证 tool_calls + approvals + runner 闭环。
    tool_calls_chunk = (
        "message",
        (
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"'
            + call_id
            + '","type":"function","function":{"name":"triggerflow_run_flow","arguments":"'
            + args_json
            + '"}}]},"finish_reason":"tool_calls"}]}'
        ),
    )

    scripts = [
        [tool_calls_chunk, ("message", "[DONE]")],
        [
            ("message", '{"choices":[{"delta":{"content":"demo ok"},"finish_reason":"stop"}]}'),
            ("message", "[DONE]"),
        ],
    ]

    requester = _ScriptedRequester(scripts=scripts)

    def factory() -> _ScriptedRequester:
        # 重要：复用同一个 requester 实例以保留多轮脚本状态；
        # 否则每次 LLM 请求都会从第 1 段脚本重放，导致无限 tool_calls 循环。
        return requester

    return AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))


@dataclass(frozen=True)
class DemoFlow:
    name: str

    def run(self, input_obj: Any) -> Any:
        return {"flow": self.name, "input": input_obj}


class InProcessFlowRunner(TriggerFlowRunner):
    """最小可复刻 runner：用 Python 函数模拟 flow。"""

    def __init__(self) -> None:
        self._flows: Dict[str, DemoFlow] = {
            "demo_echo": DemoFlow(name="demo_echo"),
            "demo_noop": DemoFlow(name="demo_noop"),
        }

    def run_flow(
        self,
        *,
        flow_name: str,
        input: Any = None,
        timeout_sec: Optional[float] = None,
        wait_for_result: bool = True,
    ) -> Any:
        _ = timeout_sec
        if flow_name not in self._flows:
            raise ValueError(f"unknown flow_name: {flow_name!r}")
        if not wait_for_result:
            return {"scheduled": True, "flow": flow_name}
        return self._flows[flow_name].run(input)


def build_demo_agent(
    *,
    workspace_root: Path,
    sdk_config_paths: List[Path],
    human_io: Any,
    runner: TriggerFlowRunner,
) -> Agent:
    """
    构造用于 demo run 的 SDK Agent（注册 TriggerFlow tool）。

    参数：
    - workspace_root：WAL/产物根目录
    - sdk_config_paths：SDK overlays（用于 skills 配置与 preflight）
    - human_io：同步 approvals 接口（用于 TriggerFlow tool）
    - runner：宿主注入 runner（模拟 TriggerFlow flow）
    """

    default_overlay = load_default_config_dict()
    overlays: List[Dict[str, Any]] = [default_overlay]
    for p in sdk_config_paths:
        obj = {}
        try:
            import yaml

            obj = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
        except Exception:
            obj = {}
        if isinstance(obj, dict):
            overlays.append(obj)
    _ = load_config_dicts(overlays)  # 仅用于验证 overlays 形态；Agent 自身会按 config_paths 加载

    backend = build_demo_backend()
    agent = Agent(
        workspace_root=Path(workspace_root),
        config_paths=list(sdk_config_paths),
        env_vars={},
        backend=backend,
        human_io=human_io,
        approval_provider=None,
        cancel_checker=None,
    )

    spec, handler = build_triggerflow_run_flow_tool(deps=TriggerFlowToolDeps(runner=runner))
    agent._extra_tools.append((spec, handler))  # type: ignore[attr-defined]
    return agent
