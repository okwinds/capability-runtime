# agently-skills-runtime

一句话定位：一个**生产级的能力运行时（Capability Runtime）+ 上游桥接层**。在“能力范式”上强调 **Skill / Agent / Workflow 三元对等**，但在“本仓公共协议原语/对外承诺”上只提供 **Agent / Workflow**；skills 引擎能力由上游 `agent_sdk` 提供。本仓为可观测与审计提供稳定的结构化产出（NodeReport v2）。

## 安装

Python >= 3.10：

```bash
python -m pip install -e .
```

（可选）开发依赖：

```bash
python -m pip install -e ".[dev]"
```

## 30 秒快速体验（离线可跑）

下面示例不依赖真实 LLM，只体验“声明 → 注册 → 执行”的最小闭环：

```bash
python examples/00_quickstart_capability_runtime/run.py
```

## 核心概念：范式三元对等，协议二元承诺

在完整系统里，**Skill / Agent / Workflow 在能力范式上都是一等公民**；但需要注意“边界与承诺”：

- **本仓对外承诺的能力原语**：仅 **Agent / Workflow**（可注册/可编排/可执行），见 `CapabilityRuntime`。
- **skills 引擎能力的真相源**：由上游 `agent_sdk` 提供（strict catalog + mention + sources + preflight + tools/approvals + WAL/events）。本仓不把 `skill` 作为公共协议原语，也不重造 skills 注入/调度引擎，避免形成第二套 skills 体系。
- **证据链优先**：编排分支与审计优先读取 NodeReport/WAL/tool evidence（控制面），而不是解析 `final_output` 自由文本（数据面）。

你可以把它理解为：**“协议二元（Agent/Workflow）+ 引擎一元（agent_sdk）+ 证据链闭环（NodeReport/WAL）”**。

## 能力来源与执行闭环（ASCII 图）

### 图 1：能力来源（两上游 + 本仓桥接）

```text
                    +----------------------+
                    | Upstream: Agently    |
                    | - TriggerFlow (入口) |
                    | - OpenAICompatible   |
                    +----------+-----------+
                               |
                               | (LLM 传输/编排入口)
                               v
+---------------------------------------------------------------------+
| This Repo: agently-skills-runtime                                   |
| - Protocol: AgentSpec / WorkflowSpec   (对外承诺的能力原语)          |
| - Runtime:  CapabilityRuntime          (register/validate/run)       |
| - Adapters: WorkflowAdapter / AgentAdapter                           |
| - Bridge:   AgentlySkillsRuntime     (preflight/upstreams + reporting)|
+----------------------------+----------------------------------------+
                             |
                             | (真实执行与 skills/tool/approvals 委托)
                             v
                    +----------------------+
                    | Upstream: agent_sdk  |
                    | - Skills Engine      |
                    | - Tools/Approvals    |
                    | - WAL / AgentEvent   |
                    +----------+-----------+
                               |
                               | (events/evidence)
                               v
                     NodeReport v2 (控制面) + final_output (数据面)
```

### 图 2：面向能力的执行闭环（声明 → 注册 → 编排 → 执行 → 取证）

```text
[你的业务域代码]
  |
  | 1) 声明能力
  |    - AgentSpec / WorkflowSpec               (本仓)
  |    - skills overlays + strict mention       (agent_sdk)
  v
CapabilityRuntime.register(...)                 (本仓)
  |
  | 2) Workflow 编排（强结构）
  v
WorkflowAdapter.execute(workflow)              (本仓)
  |
  | 3) 每个 step 调用 Agent（或子 Workflow）
  v
AgentAdapter.execute(agent)                    (本仓)
  |
  | 4) 委托 Bridge 运行一次 turn
  v
AgentlySkillsRuntime.run_async(task, ...)      (本仓 Bridge)
  |
  | 5) 真实执行：skills/tool/approvals/WAL/events
  v
agent_sdk.Agent.run_stream_async(...)          (上游)
  |
  | 6) 聚合证据链并返回
  v
NodeReportBuilder -> NodeReport v2             (本仓)
  |
  +--> 业务分支/审计看 NodeReport（控制面）
  +--> 业务展示/落盘用 final_output（数据面）
```

### 图 3：数据面 vs 控制面（为什么不只看输出文本）

```text
NodeResultV2
  - final_output : string
      (数据面：生态兼容，可能是自由文本/弱结构)

  - node_report  : NodeReportV2
      (控制面：强结构证据链，用于编排/审计/回归)
      - status / reason              (分支依据)
      - tool_calls + approvals       (证据)
      - events_path (WAL 指针)       (可追溯)
      - meta (脱敏摘要)              (可观测，不泄露)
```

### 图 4：三元“互相调用/引用”的实现方式（Scheme2）

> 口径提醒：本仓不把 `skill` 当作公共协议原语；skills 的“执行与治理”在 `agent_sdk` 引擎层完成。  
> 因此所谓“三元互调”，更多是**效果层互调**，实现层通常通过 “Agent 作为承载体 + tool/Host 作为桥梁”完成。

```text
  (A) Workflow 编排多个“以 skill 为核心的节点”

  +-----------------------+        +-----------------------+
  | Workflow (this repo)  |  step  | Agent (this repo)     |
  | - Step/Loop/Parallel  +------->| - 只做薄壳任务组织     |
  | - result.* 可路由      |        | - task 内引用 skills   |
  +-----------------------+        +-----------+-----------+
                                              |
                                              | strict mention / injected content
                                              v
                                   +-----------------------+
                                   | Skill (agent_sdk)     |
                                   | - catalog/mention     |
                                   | - sources/preflight   |
                                   | - tools/approvals/WAL |
                                   +-----------------------+
```

```text
  (B) Agent “调用 workflow”的推荐路径：通过 tool / Host 触发

  +-----------------------+     tool_call: run_workflow / triggerflow_run_flow
  | Agent (this repo)     +----------------------------------------------+
  +-----------------------+                                              |
                                                                         v
                                                                +-------------------+
                                                                | Host / TriggerFlow |
                                                                +---------+---------+
                                                                          |
                                                                          | CapabilityRuntime.run("WF-*")
                                                                          v
                                                                +-------------------+
                                                                | Workflow (this repo)|
                                                                +-------------------+
```

### 图 5：把“skills 作为 workflow 节点”的推荐落地（薄壳 Agent 节点）

```text
你想要的业务效果：
  Workflow 里每个节点都“基于某个 skill 做事”，最后汇总输出

Scheme2 推荐落地：
  - 不创建 Skill 节点类型（本仓不承诺 skill 原语）
  - 为每个 skill（或一组 skills）创建一个薄壳 AgentSpec
  - Workflow 的 Step 仍然只指向 Agent/Workflow

  +---------------------+
  | WorkflowSpec        |
  |  - step: draft      +--> AgentSpec("draft") : task 里引用 $[space].draft_skill
  |  - step: review     +--> AgentSpec("review") : task 里引用 $[space].review_skill
  |  - step: final      +--> AgentSpec("final") : 汇总 step_outputs / tool evidence
  +---------------------+
```

### 图 6：业务域如何“面向能力”组织（建议结构，不绑定具体业务）

```text
your-domain/
  agents/                 # AgentSpec：薄壳任务单元（承载 skills 引用）
    *.py
  workflows/              # WorkflowSpec：强结构编排（Step/Loop/Parallel/Conditional）
    *.py
  sdk-overlays/           # agent_sdk overlays：skills catalog/sources/prompt/run/safety
    *.yaml
  registry.py             # 一键 register：把 agents/workflows 注册进 CapabilityRuntime
  main.py                 # 入口：run(workflow_id) -> NodeReport v2 + final_output
```

## 实现落点（类 / 方法 / 包名）

下面把“多能力之间的调用/引用”落到**本仓真实代码位置**，你可以据此从 README 直接跳进实现：

### 0) 使用者的最小学习面（Facade：你只需要学本仓）

本仓的目标是把“双上游能力”收敛成对使用者友好的入口；对大多数接入方而言，**你优先学习/使用的是本仓 API**：

```text
 +-------------------------+     +--------------------------------------+
 |  Your App / Host Code   |     | This Repo (what you learn first)     |
 +-----------+-------------+     +------------------+-------------------+
             |                                    |
             | declare/register/run               | 组织/编排/证据链
             +----------------------------------->| CapabilityRuntime
             |                                    | - run(...) / validate()
             | run one LLM turn + evidence        |
             +----------------------------------->| AgentlySkillsRuntime
                                                  | - run_async(...)
                                                  | - register_tool(...)
                                                  +-------------------+
                                                            |
                                                            | (实现细节：由本仓桥接与委托)
                                                            v
                                                  +-------------------+
                                                  | Upstreams         |
                                                  | - agently         |
                                                  | - agent_sdk       |
                                                  +-------------------+
```

说明：
- 你可以完全不直接 import 上游模块就完成“声明/注册/编排/执行/取证”的主流程；
- 上游知识在你需要深度定制（例如 overlay/skills catalog/工具体系）时再学习即可，本仓尽量把常见能力以稳定入口收敛出来。

### 1) Workflow 调用 Agent / Workflow（本仓原生）

```text
agently_skills_runtime.runtime.engine.CapabilityRuntime
  - run(capability_id: str, *, input: dict|None = None, ...) -> CapabilityResult
  - _execute(spec, *, input: dict, context: ExecutionContext) -> CapabilityResult

agently_skills_runtime.adapters.workflow_adapter.WorkflowAdapter
  - execute(*, spec: WorkflowSpec, input: dict, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult
    - Step / LoopStep / ParallelStep / ConditionalStep
    - 写入 context.step_outputs / context.step_results（用于 mapping 与基于证据链路由）
```

### 2) Agent “以 skills 为基础做事”（通过上游 agent_sdk）

```text
agently_skills_runtime.adapters.agent_adapter.AgentAdapter
  - execute(*, spec: AgentSpec, input: dict, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult
    - runner(task: str, *, initial_history: list[dict]|None = None) -> Any

说明：
- 在 Scheme2 下，skills 的发现/mention/sources/preflight/tools/approvals/WAL 都由上游 agent_sdk 负责；
- 本仓的 AgentAdapter 只负责“组织 task + 委托 runner + 状态映射 + 保留 NodeReport”。
```

### 3) Agent “调用 TriggerFlow 工作流”（本仓已内置：`triggerflow_run_flow` tool）

当你在 `AgentlySkillsRuntime` 构造时注入 `triggerflow_runner`，桥接层会把一个需要审批的 tool 注册进 SDK Agent：

```text
agently_skills_runtime.adapters.triggerflow_tool.build_triggerflow_run_flow_tool(deps)
  -> (ToolSpec(name="triggerflow_run_flow", requires_approval=True), handler)

agently_skills_runtime.bridge.AgentlySkillsRuntime
  - __init__(..., triggerflow_runner: TriggerFlowRunner|None = None, ...)
  - _get_or_create_agent(): register_agent_tool(agent, spec, handler, override=False)
```

这样 LLM 在运行时就可以通过 tool_call 触发 TriggerFlow（并在 WAL 中产生 approval_* 证据链，最终汇总进 NodeReport）。

### 4) Agent “调用本仓 WorkflowSpec”（推荐：Host 自定义 tool；模式与 TriggerFlow tool 一致）

本仓不内置 `run_workflow` tool（避免强绑定你的业务 runtime 实例），但推荐按同样的方式在 Host 层提供一个 tool：

- tool handler 内部调用：`CapabilityRuntime.run("WF-xxx", input=...)`
- tool 的审批、事件与证据链仍由 `agent_sdk` WAL 驱动并最终进入 NodeReport

### 5) 三元互调“到底是谁在组织调用”（调用链标注到方法）

下面这张图把“互调”落到**本仓的组织点**：谁负责递归调度、谁负责把 run 变成证据链、谁负责把 tool_call 变成 workflow 执行。

```text
WorkflowSpec (this repo)
  |
  | WorkflowAdapter.execute(...)             agently_skills_runtime.adapters.workflow_adapter.WorkflowAdapter
  v
Step(capability=AgentSpec/WorkflowSpec)
  |
  | CapabilityRuntime._execute(...)          agently_skills_runtime.runtime.engine.CapabilityRuntime
  v
AgentAdapter.execute(...)                    agently_skills_runtime.adapters.agent_adapter.AgentAdapter
  |
  | runner = AgentlySkillsRuntime.run_async  agently_skills_runtime.bridge.AgentlySkillsRuntime
  v
agent_sdk.Agent.run_stream_async(...)        (implementation detail; upstream engine)
  |
  | tool_call_requested(name="run_workflow") (WAL/events evidence)
  v
Host tool handler(call, ctx)                 (your code; registered via bridge.register_tool)
  |
  | CapabilityRuntime.run("WF-xxx", ...)     agently_skills_runtime.runtime.engine.CapabilityRuntime
  v
ToolResult.ok(data=...) -> WAL/events        (upstream WAL; evidence)
  |
  | NodeReportBuilder.build(events)          agently_skills_runtime.reporting.node_report.NodeReportBuilder
  v
NodeReportV2 (control plane) + final_output (data plane)
```

## 代码示例（最小可复制）

### 示例 A：Workflow 编排多个 Agent（离线 mock runner）

> 完整可运行版本见：`examples/00_quickstart_capability_runtime/run.py`。

```python
import asyncio

from agently_skills_runtime import (
    AgentAdapter,
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilityRuntime,
    CapabilitySpec,
    CapabilityStatus,
    Step,
    WorkflowAdapter,
    WorkflowSpec,
)


async def _mock_runner(task: str, *, initial_history=None):
    _ = initial_history
    return {"task_seen": task}


async def main() -> None:
    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=_mock_runner))
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    rt.register(
        AgentSpec(base=CapabilitySpec(id="A1", kind=CapabilityKind.AGENT, name="A1"), prompt_template="do {x}")
    )
    rt.register(
        AgentSpec(base=CapabilitySpec(id="A2", kind=CapabilityKind.AGENT, name="A2"), prompt_template="do {y}")
    )
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="WF-1", kind=CapabilityKind.WORKFLOW, name="wf"),
            steps=[
                Step(id="s1", capability=CapabilityRef(id="A1")),
                Step(id="s2", capability=CapabilityRef(id="A2")),
            ],
        )
    )

    out = await rt.run("WF-1", input={"x": 1, "y": 2})
    assert out.status == CapabilityStatus.SUCCESS


if __name__ == "__main__":
    asyncio.run(main())
```

### 示例 B：Agent 调用 TriggerFlow（通过 `triggerflow_run_flow` tool）

> 参考可运行示例：`examples/10_bridge_wiring/`（真实 LLM 环境）。

关键点：你不需要在本仓实现“workflow 解析器”，而是让 Agent 通过 tool_call 调用 TriggerFlow；
工具注册与审批证据链由本仓提供（`agently_skills_runtime.adapters.triggerflow_tool`）。

### 示例 C：Agent 调用本仓 Workflow（Host 提供 `run_workflow` tool；推荐模式）

> 重要约束：`agent_sdk` 的 tool handler 是同步函数（见 `agently_skills_runtime.adapters.triggerflow_tool`），因此如果你的 Workflow 执行是异步的，需要在 Host 的 runner 里处理“同步↔异步”桥接。下面代码示例展示的是**模式**，不是唯一实现。

#### C.1 实现流程图（带落点）

```text
AgentSpec (this repo)
  |
  | AgentAdapter.execute(...)                    agently_skills_runtime.adapters.agent_adapter.AgentAdapter
  v
AgentlySkillsRuntime.run_async(...)              agently_skills_runtime.bridge.AgentlySkillsRuntime
  |
  | agent_sdk.Agent.run_stream_async(...)        agent_sdk.core.agent.Agent
  |   - tool_call_requested(name="run_workflow")
  v
ToolRegistry -> handler(call, ctx)               (你在 Host 自己实现；签名对齐 agent_sdk)
  |
  | (可选) approval_requested/decided            ctx.emit_event(AgentEvent(...))
  | runner.run_workflow(...)                     (你实现/注入的 WorkflowRunner)
  v
CapabilityRuntime.run("WF-xxx", ...)             agently_skills_runtime.runtime.engine.CapabilityRuntime
  |
  | ToolResult.ok(data=...)                      agent_sdk.tools.protocol.ToolResult
  v
NodeReportBuilder.build(events) -> NodeReportV2  agently_skills_runtime.reporting.node_report.NodeReportBuilder
```

#### C.2 最小代码骨架（tool + runner + 注入）

你可以参考本仓已实现的 tool（`agently_skills_runtime.adapters.triggerflow_tool.build_triggerflow_run_flow_tool`），在业务侧实现一个 `run_workflow` tool：

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Tuple

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.tools.protocol import ToolCall, ToolResult, ToolSpec
from agent_sdk.tools.registry import ToolExecutionContext

from agently_skills_runtime import CapabilityRuntime
from agently_skills_runtime.adapters.upstream import register_agent_tool


class WorkflowRunner(Protocol):
    def run_workflow(self, *, workflow_id: str, input: Any = None, timeout_sec: Optional[float] = None) -> Any: ...


@dataclass(frozen=True)
class Deps:
    runner: WorkflowRunner


def build_run_workflow_tool(*, deps: Deps) -> Tuple[ToolSpec, Any]:
    spec = ToolSpec(
        name="run_workflow",
        description="Run a local WorkflowSpec by id (requires approval).",
        parameters={
            "type": "object",
            "properties": {"workflow_id": {"type": "string"}, "input": {}, "timeout_sec": {"type": "number"}},
            "required": ["workflow_id"],
            "additionalProperties": False,
        },
        requires_approval=True,
    )

    def handler(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.args or {}
        wf_id = args.get("workflow_id")
        if not isinstance(wf_id, str) or not wf_id.strip():
            return ToolResult.error_payload(error_kind="validation", stderr="workflow_id must be a non-empty string")

        # 说明：为保持 README 简短，这里省略了“脱敏摘要 + approval_* 证据事件”的完整实现；
        # 生产实现请直接参考 `agently_skills_runtime.adapters.triggerflow_tool` 的做法（emit approval_requested/decided）。
        if ctx.human_io is None:
            ctx.emit_event(
                AgentEvent(type="approval_requested", ts="now", run_id=ctx.run_id, payload={"call_id": call.call_id, "tool": call.name})
            )
            ctx.emit_event(
                AgentEvent(type="approval_decided", ts="now", run_id=ctx.run_id, payload={"call_id": call.call_id, "tool": call.name, "decision": "denied"})
            )
            return ToolResult.error_payload(error_kind="permission", stderr="run_workflow requires HumanIOProvider for approval")

        # 执行（runner 内部负责同步/异步桥接）
        out = deps.runner.run_workflow(workflow_id=wf_id.strip(), input=args.get("input"), timeout_sec=args.get("timeout_sec"))
        return ToolResult.ok(data={"workflow_id": wf_id.strip(), "output": out})

    return spec, handler


class LocalRuntimeWorkflowRunner:
    def __init__(self, *, runtime: CapabilityRuntime):
        self._rt = runtime

    def run_workflow(self, *, workflow_id: str, input: Any = None, timeout_sec: Optional[float] = None) -> Any:
        _ = timeout_sec
        payload = input if isinstance(input, dict) else {}
        # 注意：示例用 asyncio.run 演示模式；生产建议用独立线程/进程/服务化避免 event loop 冲突。
        res = asyncio.run(self._rt.run(workflow_id, input=payload))
        return {"status": getattr(res.status, "value", str(res.status)), "output": res.output, "error": res.error}


def register_run_workflow_tool(*, bridge: Any, runtime: CapabilityRuntime) -> None:
    spec, handler = build_run_workflow_tool(deps=Deps(runner=LocalRuntimeWorkflowRunner(runtime=runtime)))
    bridge.register_tool(spec=spec, handler=handler, override=False)
```

接入位置（推荐）：
- 业务侧构造 `AgentlySkillsRuntime` 后，直接调用其公共 API `register_tool(...)` 注册自定义 tool（不会强迫你覆盖私有方法）。
- 在首次 `run_async(...)` 懒创建 SDK Agent 时，bridge 会把已注册的 tools 注入到底层 SDK Agent。

#### C.3 “同步 tool handler ↔ 异步 workflow run”的桥接策略（教科书式清单）

你会遇到的现实约束是：tool handler 同步，但 workflow 执行通常是异步/长耗时。推荐从简单到工程化依次选择：

1) **线程桥接（本地最小可用）**
   - 做法：在 `WorkflowRunner.run_workflow(...)` 内把异步执行丢到独立线程，并在该线程内 `asyncio.run(...)` 跑完整 workflow。
   - 适用：本地 demo / 单机工具；不适合高并发。

2) **子进程/队列桥接（隔离 event loop 与资源）**
   - 做法：tool handler 写入任务（文件/队列/DB），由 worker 进程运行 `CapabilityRuntime.run(...)`，再回写结果。
   - 适用：需要隔离资源、避免 event loop 冲突、可控的吞吐。

3) **服务化桥接（推荐生产形态）**
   - 做法：把 workflow runtime 变成独立服务（HTTP/SSE/消息队列），tool handler 只负责发起请求与等待/轮询结果；审批与证据链仍通过 WAL/events 汇总到 NodeReport。
   - 适用：生产接入、需要弹性伸缩、需要清晰的超时/重试/隔离策略。

## 文档与示例

- 文档索引：`DOCS_INDEX.md`
- 面向使用者的文档入口：`docs/README.md`
- 工程规格入口（偏研发/验收）：`docs/spec.md`（规格索引：`docs/internal/specs/engineering-spec/SPEC_INDEX.md`）
- 示例索引：`examples/README.md`

## 测试（离线回归）

```bash
python -m pytest -q
```
