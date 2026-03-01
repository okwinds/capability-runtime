"""
invoke_capability：宿主侧“能力委托工具”（CustomTool）公共 API。

定位：
- 保持协议层二元：对外可寻址的能力仍只有 Agent/Workflow（capability_id）。
- 把“委托子能力”的发生过程纳入 tool evidence（WAL + NodeReport.tool_calls）。
- 遵守上游现实约束：tool handler 为同步函数；当子能力为 async API 时，使用“后台线程 + 常驻 event loop runner”执行。

对齐规格（delta）：
- `openspec/specs/host-lifecycle-toolkit/spec.md`
- `openspec/specs/examples-coding-agent-pack/spec.md`
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from skills_runtime.tools.protocol import ToolCall, ToolResult, ToolSpec
from skills_runtime.tools.registry import ToolExecutionContext

from ..config import CustomTool, RuntimeConfig
from ..protocol.context import ExecutionContext
from ..registry import AnySpec

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime import Runtime


_ARTIFACT_SCHEMA_ID = "capability-runtime.invoke_capability.v1"


class InvokeCapabilityArgs(BaseModel):
    """
    invoke_capability 的 tool args（最小集合）。

    字段：
    - capability_id：目标能力 ID（Agent/Workflow）
    - input：输入参数（JSON object；敏感/大 payload 建议以 artifact 指针方式传递）
    """

    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(min_length=1)
    input: Dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class InvokeCapabilityAllowlist:
    """
    invoke_capability 的能力白名单（fail-closed 由调用方选择是否启用）。

    约束：
    - 若同时提供 allowed_ids 与 allowed_prefixes，则任一命中即可允许。
    """

    allowed_ids: Sequence[str] = ()
    allowed_prefixes: Sequence[str] = ()

    def is_allowed(self, capability_id: str) -> bool:
        """
        判断 capability_id 是否在允许范围内。

        参数：
        - capability_id：能力 ID

        返回：
        - True 表示允许；False 表示拒绝
        """

        cid = str(capability_id or "").strip()
        if not cid:
            return False

        for x in self.allowed_ids:
            if str(x).strip() == cid:
                return True
        for p in self.allowed_prefixes:
            pp = str(p).strip()
            if pp and cid.startswith(pp):
                return True
        return False


def _sha256_bytes(data: bytes) -> str:
    """计算 bytes 的 sha256 hex。"""

    return hashlib.sha256(data).hexdigest()


def _write_json_artifact(*, path: Path, obj: Dict[str, Any]) -> tuple[str, int]:
    """
    将 JSON artifact 写入 path，并返回（sha256, bytes）。

    参数：
    - path：artifact 绝对路径（必须位于 workspace_root 下）
    - obj：可 JSON 序列化的 dict

    返回：
    - (sha256_hex, bytes_count)
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return _sha256_bytes(raw), len(raw)


class _AsyncRunner:
    """
    后台 event loop runner（daemon thread）。

    背景：
    - 上游 tool handler 为同步函数；
    - 但 Runtime.run(...) 为 async API；
    - 因此需要一个后台 event loop 来承载 async 子调用，并用 `asyncio.run_coroutine_threadsafe`
      在同步 handler 内“阻塞等待结果”（不会死锁主 Agent Loop）。
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    def ensure_started(self) -> None:
        if self._thread is not None and self._loop is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name="caprt-invoke-capability-runner", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if self._loop is None:
            raise RuntimeError("invoke_capability runner loop failed to start")

    def run(self, coro: Any, *, timeout_s: float | None) -> Any:
        self.ensure_started()
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout_s)


_INVOKE_CAPABILITY_RUNNER = _AsyncRunner()


def make_invoke_capability_tool(
    *,
    child_runtime_config: RuntimeConfig,
    child_specs: List[AnySpec],
    shared_runtime: Optional["Runtime"] = None,
    allowlist: Optional[InvokeCapabilityAllowlist] = None,
    requires_approval: bool = True,
    artifacts_subdir: str = "artifacts/invoke_capability",
    timeout_ms: int = 60_000,
    override: bool = False,
) -> CustomTool:
    """
    构造一个可注入到 RuntimeConfig.custom_tools 的 invoke_capability 工具。

    参数：
    - child_runtime_config：子调用 Runtime 的配置模板（在后台 runner 的 event loop 中创建 Runtime）
    - child_specs：子调用可执行的能力声明快照（AgentSpec/WorkflowSpec 列表）
    - shared_runtime：可选共享 Runtime；提供时将复用该实例执行子能力（不再为每次子调用创建新 Runtime）
    - allowlist：可选能力白名单；提供后将启用校验（未命中则拒绝）
    - requires_approval：是否提示该 tool 需要审批（最终由 safety/policy 决定）
    - artifacts_subdir：产物子目录（相对 workspace_root）
    - timeout_ms：子调用超时（毫秒）；超时将返回 tool error_kind=timeout
    - override：是否允许覆盖同名工具

    返回：
    - CustomTool（ToolSpec + handler）
    """

    spec = ToolSpec(
        name="invoke_capability",
        description="\n".join(
            [
                "宿主能力委托工具：执行子 Agent/子 Workflow，并返回最小披露摘要。",
                "约束：tool handler 同步；子调用通过后台线程 + 常驻 event loop runner 执行。",
                "入参：{capability_id, input}。",
            ]
        ),
        parameters={
            "type": "object",
            "properties": {
                "capability_id": {"type": "string", "minLength": 1, "description": "目标能力 ID（Agent/Workflow）"},
                "input": {"type": "object", "description": "输入参数（敏感/大 payload 建议以 artifact 指针传递）"},
            },
            "required": ["capability_id", "input"],
            "additionalProperties": False,
        },
        requires_approval=bool(requires_approval),
        idempotency="unknown",
    )

    def handler(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        """
        工具 handler（同步）：委托执行子能力并返回摘要。

        参数：
        - call：工具调用（包含 args）
        - ctx：工具执行上下文（提供 workspace_root/run_id/WAL emitter 等）

        返回：
        - ToolResult（结构化结果写入 ToolResultPayload.data）
        """

        started = time.monotonic()
        duration_ms = 0

        try:
            args = InvokeCapabilityArgs.model_validate(call.args)
        except ValidationError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return ToolResult.error_payload(
                error_kind="validation",
                stderr="invoke_capability args validation failed",
                data={"error": str(exc)},
                duration_ms=duration_ms,
            )

        capability_id = str(args.capability_id).strip()
        input_dict = dict(args.input or {})

        if allowlist is not None and not allowlist.is_allowed(capability_id):
            duration_ms = int((time.monotonic() - started) * 1000)
            return ToolResult.error_payload(
                error_kind="permission",
                stderr=f"capability_id is not allowed: {capability_id!r}",
                data={"capability_id": capability_id},
                duration_ms=duration_ms,
            )

        # 子调用 run_id：用于审计追溯与 WAL 定位（不得与父 run 混淆）。
        child_run_id = uuid.uuid4().hex

        # 产物路径：位于 workspace_root 下，便于复制/审计。
        artifact_rel = f"{str(artifacts_subdir).strip().strip('/')}/{ctx.run_id}/{call.call_id}.json"
        artifact_path = ctx.resolve_path(artifact_rel)

        async def _run_child() -> Dict[str, Any]:
            if shared_runtime is None:
                # 在 runner loop 内创建 Runtime（避免 asyncio 原语绑定到错误的 loop）。
                from ..runtime import Runtime  # lazy import（避免循环导入）

                rt = Runtime(child_runtime_config)
                rt.register_many(list(child_specs or []))
                max_depth = child_runtime_config.max_depth
            else:
                # 复用宿主提供的 Runtime 实例。
                rt = shared_runtime
                # 兼容：允许调用方仍提供 child_specs；此时将其注册到 shared runtime（last-write-wins）。
                rt.register_many(list(child_specs or []))
                max_depth = int(getattr(rt.config, "max_depth", child_runtime_config.max_depth))

            # 子调用上下文（独立 run_id，避免与父 run 的证据链混淆）。
            child_ctx = ExecutionContext(run_id=child_run_id, max_depth=max_depth, guards=None)
            result = await rt.run(capability_id, input=input_dict, context=child_ctx)

            capability_status = getattr(result.status, "value", str(result.status))
            node_status = None
            events_path = None
            if result.node_report is not None:
                node_status = result.node_report.status
                events_path = result.node_report.events_path

            out = str(result.output or "")
            out_bytes = out.encode("utf-8")
            out_sha256 = _sha256_bytes(out_bytes)

            return {
                "child_capability_status": capability_status,
                "child_node_status": node_status,
                "child_events_path": events_path,
                "child_output_sha256": out_sha256,
                "child_output_bytes": len(out_bytes),
            }

        try:
            # 执行子调用（阻塞等待完成）。
            digest = _INVOKE_CAPABILITY_RUNNER.run(
                _run_child(),
                timeout_s=float(timeout_ms) / 1000.0 if timeout_ms else None,
            )

            artifact_obj: Dict[str, Any] = {
                "schema": _ARTIFACT_SCHEMA_ID,
                "created_at_ms": int(time.time() * 1000),
                "parent_run_id": str(ctx.run_id),
                "call_id": str(call.call_id),
                "capability_id": capability_id,
                "child_run_id": child_run_id,
                **digest,
            }
            artifact_sha256, artifact_bytes = _write_json_artifact(path=artifact_path, obj=artifact_obj)

            duration_ms = int((time.monotonic() - started) * 1000)
            data = {
                "capability_id": capability_id,
                "child_run_id": child_run_id,
                "child_capability_status": digest.get("child_capability_status"),
                "child_node_status": digest.get("child_node_status"),
                "child_events_path": digest.get("child_events_path"),
                "artifact_path": str(artifact_path),
                "artifact_sha256": artifact_sha256,
                "artifact_bytes": artifact_bytes,
            }
            return ToolResult.ok_payload(stdout="invoke_capability ok", data=data, duration_ms=duration_ms)
        except TimeoutError:
            duration_ms = int((time.monotonic() - started) * 1000)
            return ToolResult.error_payload(
                error_kind="timeout",
                stderr="invoke_capability child run timed out",
                data={"capability_id": capability_id, "child_run_id": child_run_id},
                duration_ms=duration_ms,
                retryable=False,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return ToolResult.error_payload(
                error_kind="unknown",
                stderr=f"invoke_capability failed: {type(exc).__name__}",
                data={"capability_id": capability_id, "child_run_id": child_run_id},
                duration_ms=duration_ms,
                retryable=False,
            )

    return CustomTool(spec=spec, handler=handler, override=bool(override))
