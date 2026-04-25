"""AgentAdapter 单元测试（以统一 Runtime + mock/bridge 语义为真相源）。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

import pytest

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentIOSchema, AgentSpec
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime

from capability_runtime.adapters.agent_adapter import AgentAdapter


def _mk_runtime(*, cfg: RuntimeConfig) -> Runtime:
    rt = Runtime(cfg)
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_mock_handler_can_return_capability_result() -> None:
    def handler(_spec: AgentSpec, _input: Dict[str, Any]) -> CapabilityResult:
        return CapabilityResult(status=CapabilityStatus.PENDING, output={"needs": "approval"})

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.PENDING
    assert out.output == {"needs": "approval"}


@pytest.mark.asyncio
async def test_mock_handler_can_be_async() -> None:
    async def handler(_spec: AgentSpec, input_dict: Dict[str, Any], _ctx: ExecutionContext) -> Dict[str, Any]:
        return {"ok": True, "x": input_dict.get("x")}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", input={"x": 1}, context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.SUCCESS
    assert out.output["ok"] is True
    assert out.output["x"] == 1


@pytest.mark.asyncio
async def test_mock_handler_typeerror_inside_body_not_swallowed() -> None:
    """问题 1：handler 内部的 TypeError 应该被捕获并返回 FAILED，而不是被吞掉。"""

    def handler(_spec: AgentSpec, _input: Dict[str, Any]) -> Dict[str, Any]:
        # 故意触发 TypeError
        return {"result": len(None)}  # type: ignore[arg-type]

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.FAILED
    assert "mock_handler error" in out.error
    assert "TypeError" in out.error or "NoneType" in out.error


@pytest.mark.asyncio
async def test_mock_handler_two_param_works() -> None:
    """问题 1：2 参数 handler 应该正常工作。"""

    def handler(_spec: AgentSpec, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        return {"x": input_dict.get("x", 0) + 1}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", input={"x": 10}, context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.SUCCESS
    assert out.output == {"x": 11}


def test_build_task_includes_output_schema_and_skills_mentions() -> None:
    rt = _mk_runtime(
        cfg=RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="off",
            skills_config={
                "roots": [],
                "mode": "explicit",
                "max_auto": 3,
                "spaces": [
                    {
                        "id": "sp1",
                        "account": "acct",
                        "domain": "dm",
                        "sources": ["mem1"],
                        "enabled": True,
                    }
                ],
                "sources": [
                    {
                        "id": "mem1",
                        "type": "in-memory",
                        "options": {"namespace": "ns"},
                    }
                ],
                "injection": {"max_bytes": None},
            },
        )
    )

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="做一件事"),
        output_schema=AgentIOSchema(fields={"score": "int"}),
        skills=["topic-scorer"],
    )

    task = rt._agent_adapter._build_task(spec=spec, input={"x": 1})  # type: ignore[attr-defined]
    assert "## 任务" in task
    assert "做一件事" in task
    assert "## 输入" in task
    assert "## 输出要求" in task
    assert "score" in task
    assert "$[acct:dm].topic-scorer" in task


def test_build_task_strips_runtime_prompt_control_envelope_from_structured_input() -> None:
    """Prompt Rendering v1：`_runtime_prompt` 是控制面，默认 structured task 不得渲染它。"""

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock"))
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="处理主题"),
    )

    task = rt._agent_adapter._build_task(  # type: ignore[attr-defined]
        spec=spec,
        input={
            "_runtime_prompt": {
                "mode": "structured_task",
                "trace": {"prompt_hash": "sha256:" + "a" * 64},
            },
            "topic": "火星基地",
        },
    )

    assert "## 输入" in task
    assert "topic: 火星基地" in task
    assert "_runtime_prompt" not in task
    assert "prompt_hash" not in task


def test_build_task_structured_output_contract_mentions_json_object_and_required_fields() -> None:
    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock"))
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="输出结构化结果"),
        output_schema=AgentIOSchema(
            fields={"title": "str", "summary": "str", "score": "int"},
            required=["title", "summary"],
        ),
    )

    task = rt._agent_adapter._build_task(spec=spec, input={"topic": "x"})  # type: ignore[attr-defined]
    assert "JSON object" in task
    assert "不要 Markdown" in task
    assert "必填字段" in task
    assert "title" in task
    assert "summary" in task


def test_build_task_prefers_skills_mention_map_when_provided() -> None:
    rt = _mk_runtime(cfg=RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        skills=["s1"],
        skills_mention_map={"s1": "$[x:y].s1"},
    )
    task = rt._agent_adapter._build_task(spec=spec, input={})  # type: ignore[attr-defined]
    assert "$[x:y].s1" in task


def test_build_task_sections_use_constants() -> None:
    """问题 5：_build_task 应使用模块级常量，而非硬编码字符串。"""
    from capability_runtime.adapters import agent_adapter

    # 验证常量存在且可访问
    assert hasattr(agent_adapter, "_SECTION_SYSTEM")
    assert hasattr(agent_adapter, "_SECTION_TASK")
    assert hasattr(agent_adapter, "_SECTION_INPUT")
    assert hasattr(agent_adapter, "_SECTION_OUTPUT_PREFIX")
    assert hasattr(agent_adapter, "_SECTION_SKILLS")

    # 验证常量值正确
    assert agent_adapter._SECTION_SYSTEM == "## 系统指令"
    assert agent_adapter._SECTION_TASK == "## 任务"
    assert agent_adapter._SECTION_INPUT == "## 输入"
    assert agent_adapter._SECTION_OUTPUT_PREFIX == "## 输出要求"
    assert agent_adapter._SECTION_SKILLS == "## 使用以下 Skills"

    # 验证 _build_task 使用了这些常量（通过 monkeypatch 替换验证）
    original_section_task = agent_adapter._SECTION_TASK
    try:
        agent_adapter._SECTION_TASK = "## PATCHED_TASK"
        rt = _mk_runtime(cfg=RuntimeConfig(mode="mock"))
        spec = AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="test desc")
        )
        task = rt._agent_adapter._build_task(spec=spec, input={})  # type: ignore[attr-defined]
        assert "## PATCHED_TASK" in task
        assert "test desc" in task
    finally:
        agent_adapter._SECTION_TASK = original_section_task


@pytest.mark.asyncio
async def test_agent_adapter_can_run_in_mock_mode_with_fake_runtime_services() -> None:
    """task 6.3：AgentAdapter 可在不构造 Runtime 的情况下单测（mock RuntimeServices）。"""

    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))

    def handler(_spec: AgentSpec, input_dict: Dict[str, Any], _ctx: ExecutionContext) -> Dict[str, Any]:
        return {"ok": True, "x": input_dict.get("x")}

    cfg = RuntimeConfig(mode="mock", mock_handler=handler)

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg  # Protocol: @property config

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    items = []
    async for it in adapter.execute_stream(spec=spec, input={"x": 1}, context=ExecutionContext(run_id="r1")):
        items.append(it)

    assert len(items) == 1
    assert isinstance(items[0], CapabilityResult)
    assert items[0].status == CapabilityStatus.SUCCESS
    assert items[0].output == {"ok": True, "x": 1}


@pytest.mark.asyncio
async def test_agent_adapter_can_run_in_sdk_native_mode_with_fake_runtime_services() -> None:
    """task 6.3：sdk_native 路径下也可用 fake services 驱动事件流与最终 CapabilityResult。"""

    from skills_runtime.core.contracts import AgentEvent

    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeSdkAgent:
        async def run_stream_async(self, task: str, *, run_id: str, initial_history=None):  # type: ignore[no-untyped-def]
            _ = (task, initial_history)
            yield AgentEvent(type="run_started", timestamp="t0", run_id=run_id, payload={})
            yield AgentEvent(type="run_completed", timestamp="t1", run_id=run_id, payload={"final_output": "ok"})

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg
            self.taps: list[str] = []

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, *, llm_config=None):  # type: ignore[no-untyped-def]
            _ = llm_config
            return _FakeSdkAgent()

        def get_host_meta(self, *, context: ExecutionContext):  # type: ignore[no-untyped-def]
            _ = context
            return {}

        def emit_agent_event_taps(self, *, ev, context: ExecutionContext, capability_id: str) -> None:  # type: ignore[no-untyped-def]
            _ = (context, capability_id)
            self.taps.append(ev.type)

        def call_callback(self, cb, *args) -> None:  # type: ignore[no-untyped-def]
            _ = (cb, args)

        def apply_output_validation(  # type: ignore[no-untyped-def]
            self,
            *,
            final_output: str,
            report,
            context: Dict[str, Any],
            output_schema=None,
        ) -> None:
            _ = (final_output, report, context, output_schema)

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            raise AssertionError("not expected in preflight_mode=off path")

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"issue": str(issue)}

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    seen = []
    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(spec=spec, input={}, context=ExecutionContext(run_id="r1")):
        seen.append(it)
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.SUCCESS
    assert terminal.output == "ok"


@pytest.mark.asyncio
async def test_mock_handler_error_result_has_error_code_mock_handler_error() -> None:
    """验证 mock_handler 抛异常时 error_code 为 MOCK_HANDLER_ERROR。"""

    def handler(_spec: AgentSpec, _input: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("intentional error")

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.FAILED
    assert "mock_handler error" in out.error
    assert out.error_code == "MOCK_HANDLER_ERROR"
    assert out.node_report is not None
    assert out.node_report.reason == "mock_handler_error"
    assert out.node_report.completion_reason == "mock_handler_error"


@pytest.mark.asyncio
async def test_mock_handler_cancelled_error_returns_cancelled_terminal() -> None:
    """回归：mock handler 抛 `CancelledError` 不得抛穿 public API。"""

    def handler(_spec: AgentSpec, _input: Dict[str, Any]) -> Dict[str, Any]:
        raise asyncio.CancelledError()

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.CANCELLED
    assert out.error == "execution cancelled"
    assert out.error_code == "RUN_CANCELLED"
    assert out.node_report is not None
    assert out.node_report.status == "incomplete"
    assert out.node_report.reason == "cancelled"
    assert out.node_report.completion_reason == "run_cancelled"


@pytest.mark.asyncio
async def test_preflight_failure_result_has_error_code_preflight_failed() -> None:
    """验证 preflight 失败时 error_code 为 PREFLIGHT_FAILED。"""
    from skills_runtime.core.errors import FrameworkIssue

    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="error")

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg

        def preflight(self):  # type: ignore[no-untyped-def]
            return [FrameworkIssue(code="TEST_ISSUE", message="test issue", details={})]

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            return {"status": status, "reason": reason}

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"code": issue.code, "message": issue.message}

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(spec=spec, input={}, context=ExecutionContext(run_id="r1")):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.FAILED
    assert "preflight failed" in terminal.error.lower()
    assert terminal.error_code == "PREFLIGHT_FAILED"


@pytest.mark.asyncio
async def test_engine_error_result_has_error_code_engine_error() -> None:
    """验证 SDK Agent 执行异常时 error_code 为 ENGINE_ERROR。"""

    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeSdkAgent:
        async def run_stream_async(self, task: str, *, run_id: str, initial_history=None):  # type: ignore[no-untyped-def]
            _ = (task, run_id, initial_history)
            raise RuntimeError("engine crashed")
            yield  # type: ignore[unreachable]

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, *, llm_config=None):  # type: ignore[no-untyped-def]
            _ = llm_config
            return _FakeSdkAgent()

        def get_host_meta(self, *, context: ExecutionContext):  # type: ignore[no-untyped-def]
            _ = context
            return {}

        def emit_agent_event_taps(self, *, ev, context: ExecutionContext, capability_id: str) -> None:  # type: ignore[no-untyped-def]
            pass

        def call_callback(self, cb, *args) -> None:  # type: ignore[no-untyped-def]
            pass

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            return {"status": status, "reason": reason}

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(spec=spec, input={}, context=ExecutionContext(run_id="r1")):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.FAILED
    assert "engine crashed" in terminal.error
    assert terminal.error_code == "ENGINE_ERROR"


@pytest.mark.asyncio
async def test_bridge_cancelled_error_result_has_error_code_run_cancelled() -> None:
    """回归：SDK Agent 抛 `CancelledError` 时必须返回 CANCELLED terminal。"""

    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeSdkAgent:
        async def run_stream_async(self, task: str, *, run_id: str, initial_history=None):  # type: ignore[no-untyped-def]
            _ = (task, run_id, initial_history)
            raise asyncio.CancelledError()
            yield  # type: ignore[unreachable]

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, *, llm_config=None):  # type: ignore[no-untyped-def]
            _ = llm_config
            return _FakeSdkAgent()

        def get_host_meta(self, *, context: ExecutionContext):  # type: ignore[no-untyped-def]
            _ = context
            return {}

        def emit_agent_event_taps(self, *, ev, context: ExecutionContext, capability_id: str) -> None:  # type: ignore[no-untyped-def]
            pass

        def call_callback(self, cb, *args) -> None:  # type: ignore[no-untyped-def]
            pass

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            return {
                "run_id": run_id,
                "status": status,
                "reason": reason,
                "completion_reason": completion_reason,
                "meta": dict(meta),
            }

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(spec=spec, input={}, context=ExecutionContext(run_id="r1")):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.CANCELLED
    assert terminal.error == "execution cancelled"
    assert terminal.error_code == "RUN_CANCELLED"
    assert terminal.node_report == {
        "run_id": "r1",
        "status": "incomplete",
        "reason": "cancelled",
        "completion_reason": "run_cancelled",
        "meta": {"capability_id": "A", "source": "sdk_agent"},
    }


@pytest.mark.asyncio
async def test_runtime_execute_agent_when_adapter_stream_has_no_terminal_returns_fail_closed_result() -> None:
    """Agent 路径若只产出事件不产出 terminal，Runtime 必须 fail-closed。"""

    from skills_runtime.core.contracts import AgentEvent

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock"))

    async def _events_only(*, spec, input, context):  # type: ignore[no-untyped-def]
        _ = (spec, input)
        yield AgentEvent(type="run_started", timestamp="t0", run_id=context.run_id, payload={})

    original = rt._agent_adapter.execute_stream  # type: ignore[attr-defined]
    rt._agent_adapter.execute_stream = _events_only  # type: ignore[attr-defined]
    try:
        out = await rt.run("A", context=ExecutionContext(run_id="r-agent-no-terminal"))
    finally:
        rt._agent_adapter.execute_stream = original  # type: ignore[attr-defined]

    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "ENGINE_ERROR"
    assert out.node_report is not None
    assert out.node_report.reason == "engine_error"
    assert out.node_report.completion_reason == "missing_terminal_result"


@pytest.mark.asyncio
async def test_mock_handler_var_positional_receives_all_args() -> None:
    """
    回归护栏：handler 带 `*args` 时必须接收全部三个参数。

    约束：
    - 若 handler 签名含 VAR_POSITIONAL（`*args`），应传入 `(spec, input, context)`。
    - 这是参数探测的边界情况测试。
    """

    received: List[Any] = []

    def handler(*args: Any) -> Dict[str, Any]:
        received.extend(args)
        return {"count": len(args)}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", input={"x": 1}, context=ExecutionContext(run_id="r1"))

    assert out.status == CapabilityStatus.SUCCESS
    assert out.output == {"count": 3}
    assert len(received) == 3
    # 验证参数顺序：spec, input, context
    assert isinstance(received[0], AgentSpec)
    assert isinstance(received[1], dict)
    assert isinstance(received[2], ExecutionContext)


@pytest.mark.asyncio
async def test_mock_handler_mixed_positional_and_var_positional() -> None:
    """
    回归护栏：handler 带 POSITIONAL_ONLY + VAR_POSITIONAL 时行为正确。

    签名：`def fn(spec, /, *args)` 或类似形式。
    预期：传入 `(spec, input, context)`，handler 内部可访问所有参数。
    """

    received_spec: Any = None
    received_args: List[Any] = []

    def handler(spec, /, *args):  # type: ignore[no-untyped-def]
        nonlocal received_spec, received_args
        received_spec = spec
        received_args = list(args)
        return {"spec_id": spec.base.id, "args_count": len(args)}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", input={"x": 1}, context=ExecutionContext(run_id="r1"))

    assert out.status == CapabilityStatus.SUCCESS
    assert out.output["spec_id"] == "A"
    assert out.output["args_count"] == 2  # input, context
    assert isinstance(received_spec, AgentSpec)
    assert len(received_args) == 2


@pytest.mark.asyncio
async def test_mock_handler_single_param_works() -> None:
    """
    回归护栏：单参数 handler 只接收 spec。

    约束：
    - 若 handler 只有 1 个位置参数，应只传入 spec。
    """

    def handler(spec: AgentSpec) -> Dict[str, Any]:
        return {"spec_id": spec.base.id}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))

    assert out.status == CapabilityStatus.SUCCESS
    assert out.output == {"spec_id": "A"}


@pytest.mark.asyncio
async def test_mock_handler_zero_param_works() -> None:
    """
    回归护栏：零参数 handler 也能工作（边缘情况）。

    约束：
    - 若 handler 没有位置参数，应无参调用。
    """

    def handler() -> Dict[str, Any]:
        return {"no_params": True}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))

    assert out.status == CapabilityStatus.SUCCESS
    assert out.output == {"no_params": True}


@pytest.mark.asyncio
async def test_direct_task_text_mode_passes_host_task_without_structured_wrapping() -> None:
    """Prompt Rendering v1：direct_task_text 必须把 host 文本原样作为 SDK task。"""

    from skills_runtime.core.contracts import AgentEvent

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="默认描述不应进入 task"),
        prompt_render_mode="direct_task_text",
        prompt_profile="generation_direct",
    )
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeSdkAgent:
        def __init__(self) -> None:
            self.last_task: str | None = None

        async def run_stream_async(self, task: str, *, run_id: str, initial_history=None):  # type: ignore[no-untyped-def]
            _ = initial_history
            self.last_task = task
            yield AgentEvent(type="run_started", timestamp="t0", run_id=run_id, payload={})
            yield AgentEvent(type="run_completed", timestamp="t1", run_id=run_id, payload={"final_output": "ok"})

    fake_agent = _FakeSdkAgent()

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg
            self.create_kwargs: Dict[str, Any] = {}

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, **kwargs):  # type: ignore[no-untyped-def]
            self.create_kwargs = dict(kwargs)
            return fake_agent

        def get_host_meta(self, *, context: ExecutionContext):  # type: ignore[no-untyped-def]
            _ = context
            return {}

        def emit_agent_event_taps(self, *, ev, context: ExecutionContext, capability_id: str) -> None:  # type: ignore[no-untyped-def]
            _ = (ev, context, capability_id)

        def call_callback(self, cb, *args) -> None:  # type: ignore[no-untyped-def]
            _ = (cb, args)

        def apply_output_validation(self, *, final_output, report, context, output_schema=None) -> None:  # type: ignore[no-untyped-def]
            _ = (final_output, report, context, output_schema)

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            raise AssertionError("not expected")

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"issue": str(issue)}

    services = _FakeServices()
    adapter = AgentAdapter(services=services)  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(
        spec=spec,
        input={
            "_runtime_prompt": {
                "task_text": "FINAL TASK TEXT",
                "trace": {
                    "prompt_hash": "sha256:" + "b" * 64,
                    "composer_version": "composer@1",
                },
            },
            "ignored": "不能进入 task",
        },
        context=ExecutionContext(run_id="r-direct"),
    ):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert fake_agent.last_task == "FINAL TASK TEXT"
    assert "## 输入" not in fake_agent.last_task
    assert terminal is not None
    assert terminal.node_report is not None
    assert terminal.node_report.meta["prompt_render_mode"] == "direct_task_text"
    assert terminal.node_report.meta["prompt_profile"] == "generation_direct"
    assert terminal.node_report.meta["prompt_hash"] == "sha256:" + "b" * 64
    assert terminal.node_report.meta["prompt_composer_version"] == "composer@1"
    assert services.create_kwargs["prompt_profile"] == "generation_direct"


@pytest.mark.asyncio
async def test_invalid_precomposed_messages_fail_fast_before_sdk_agent_runs() -> None:
    """Prompt Rendering v1：非法 precomposed messages 必须返回 INVALID_PROMPT_MESSAGES。"""

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        prompt_render_mode="precomposed_messages",
    )
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg
            self.created = False

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            self.created = True
            raise AssertionError("SDK agent must not be created for invalid prompt messages")

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            from capability_runtime.reporting.node_report import build_fail_closed_report

            return build_fail_closed_report(
                run_id=run_id,
                status=status,
                reason=reason,
                completion_reason=completion_reason,
                meta=meta,
            )

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"issue": str(issue)}

    services = _FakeServices()
    adapter = AgentAdapter(services=services)  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(
        spec=spec,
        input={"_runtime_prompt": {"messages": [{"role": "alien", "content": "x"}]}},
        context=ExecutionContext(run_id="r-invalid"),
    ):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.FAILED
    assert terminal.error_code == "INVALID_PROMPT_MESSAGES"
    assert terminal.node_report is not None
    assert terminal.node_report.completion_reason == "invalid_prompt_messages"
    assert services.created is False


@pytest.mark.asyncio
async def test_invalid_prompt_trace_fail_fast_before_sdk_agent_runs() -> None:
    """Prompt Rendering v1：`trace` 若存在必须是 dict，不能把 falsey 非 dict 当缺省值。"""

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        prompt_render_mode="direct_task_text",
    )
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg
            self.created = False

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            self.created = True
            raise AssertionError("SDK agent must not be created for invalid prompt trace")

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            from capability_runtime.reporting.node_report import build_fail_closed_report

            return build_fail_closed_report(
                run_id=run_id,
                status=status,
                reason=reason,
                completion_reason=completion_reason,
                meta=meta,
            )

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"issue": str(issue)}

    services = _FakeServices()
    adapter = AgentAdapter(services=services)  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(
        spec=spec,
        input={"_runtime_prompt": {"task_text": "x", "trace": []}},
        context=ExecutionContext(run_id="r-invalid-trace"),
    ):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.FAILED
    assert terminal.error_code == "INVALID_PROMPT_MESSAGES"
    assert terminal.node_report is not None
    assert terminal.node_report.meta["prompt_error"] == "_runtime_prompt.trace must be a dict"
    assert services.created is False


@pytest.mark.asyncio
async def test_invalid_prompt_profile_fail_fast_before_sdk_agent_runs() -> None:
    """Prompt Rendering v1：非法 prompt profile 必须在 Adapter 层 fail-fast。"""

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        prompt_render_mode="direct_task_text",
    )
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg
            self.created = False

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            self.created = True
            raise AssertionError("SDK agent must not be created for invalid prompt profile")

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            from capability_runtime.reporting.node_report import build_fail_closed_report

            return build_fail_closed_report(
                run_id=run_id,
                status=status,
                reason=reason,
                completion_reason=completion_reason,
                meta=meta,
            )

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"issue": str(issue)}

    services = _FakeServices()
    adapter = AgentAdapter(services=services)  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(
        spec=spec,
        input={"_runtime_prompt": {"task_text": "x", "profile": "not_a_real_profile"}},
        context=ExecutionContext(run_id="r-invalid-profile"),
    ):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.FAILED
    assert terminal.error_code == "INVALID_PROMPT_MESSAGES"
    assert terminal.node_report is not None
    assert "unsupported prompt profile" in terminal.node_report.meta["prompt_error"]
    assert services.created is False


@pytest.mark.asyncio
async def test_sdk_agent_creation_error_returns_fail_closed_engine_error_with_prompt_evidence() -> None:
    """Prompt Rendering v1：SDK Agent 创建期错误也必须返回 terminal，不得从 stream 冒泡。"""

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        prompt_render_mode="direct_task_text",
        prompt_profile="generation_direct",
    )
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            raise ValueError("SDK config rejected prompt profile")

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            from capability_runtime.reporting.node_report import build_fail_closed_report

            return build_fail_closed_report(
                run_id=run_id,
                status=status,
                reason=reason,
                completion_reason=completion_reason,
                meta=meta,
            )

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"issue": str(issue)}

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(
        spec=spec,
        input={
            "_runtime_prompt": {
                "task_text": "FINAL",
                "trace": {"prompt_hash": "sha256:" + "e" * 64},
            }
        },
        context=ExecutionContext(run_id="r-create-error"),
    ):
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.FAILED
    assert terminal.error_code == "ENGINE_ERROR"
    assert terminal.node_report is not None
    assert terminal.node_report.completion_reason == "engine_exception"
    assert terminal.node_report.meta["source"] == "sdk_agent_create"
    assert terminal.node_report.meta["engine_exception"] == "ValueError"
    assert terminal.node_report.meta["prompt_render_mode"] == "direct_task_text"
    assert terminal.node_report.meta["prompt_profile"] == "generation_direct"
    assert terminal.node_report.meta["prompt_hash"] == "sha256:" + "e" * 64
