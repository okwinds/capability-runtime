# 自包含指令：构建 agently-skills-runtime 框架验证原型

> **本文档是给编码智能体的完整指令。不依赖任何外部文档。**
> 编码智能体只需读本文档即可完成全部实现。

---

## 一、任务目标

构建一个**带 React 界面**的框架验证原型，要求：

1. **覆盖框架全部能力**：Skill / Agent / Workflow 三元组的所有特性和组合方式
2. **React 界面**：供人类验收，可视化工作流执行过程和结果
3. **双模式运行**：Mock 模式（离线）+ 真实 LLM 模式（可配置 API）
4. **LLM 配置面板**：在界面中配置 API Base URL / API Key / Model Name
5. **自包含**：`pip install` 后一键启动，浏览器访问即用

**最终交付物**：一个目录 `examples/00_prototype_validation/`，包含 Python 后端 + React 前端。

---

## 二、框架 API 参考（v0.4.0 精确签名）

> 以下是编码智能体实现时必须遵循的真实 API。所有 import 路径、字段名、类型均已验证。

### 2.1 Protocol 层（纯 dataclass，零外部依赖）

```python
# ── capability.py ──
from agently_skills_runtime.protocol.capability import (
    CapabilitySpec,     # @dataclass(frozen=True)
    CapabilityKind,     # Enum: SKILL, AGENT, WORKFLOW
    CapabilityRef,      # @dataclass(frozen=True): id: str, kind: Optional[CapabilityKind]
    CapabilityResult,   # @dataclass: status, output, error, metadata, duration_ms, report
    CapabilityStatus,   # Enum: SUCCESS, FAILED, SKIPPED
)
```

**CapabilitySpec 字段**：
```python
@dataclass(frozen=True)
class CapabilitySpec:
    id: str                              # 唯一标识
    kind: CapabilityKind                 # SKILL | AGENT | WORKFLOW
    name: str = ""                       # 人类可读名称
    description: str = ""                # 描述
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**CapabilityResult 字段**：
```python
@dataclass
class CapabilityResult:
    status: CapabilityStatus             # SUCCESS | FAILED | SKIPPED
    output: Any = None                   # 执行输出
    error: Optional[str] = None          # 错误信息
    metadata: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[float] = None  # 执行耗时
    report: Any = None                   # 执行报告
```

```python
# ── skill.py ──
from agently_skills_runtime.protocol.skill import SkillSpec, SkillDispatchRule

@dataclass(frozen=True)
class SkillDispatchRule:
    condition: str                       # 触发条件（检查 context.bag 中此 key 是否 truthy）
    target: CapabilityRef                # 调度目标
    priority: int = 0                    # 数值越大越优先
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class SkillSpec:
    base: CapabilitySpec
    source: str                          # 内容（inline 文本 / 文件路径 / URI）
    source_type: str = "file"            # "file" | "inline" | "uri"
    dispatch_rules: List[SkillDispatchRule] = field(default_factory=list)
    inject_to: List[str] = field(default_factory=list)  # Agent ID 列表
```

```python
# ── agent.py ──
from agently_skills_runtime.protocol.agent import AgentSpec, AgentIOSchema

@dataclass(frozen=True)
class AgentIOSchema:
    fields: Dict[str, str] = field(default_factory=dict)   # 字段名 → 类型描述
    required: List[str] = field(default_factory=list)

@dataclass(frozen=True)
class AgentSpec:
    base: CapabilitySpec
    skills: List[str] = field(default_factory=list)          # ⚠️ 字符串 ID 列表，不是 CapabilityRef
    tools: List[str] = field(default_factory=list)
    collaborators: List[CapabilityRef] = field(default_factory=list)
    callable_workflows: List[CapabilityRef] = field(default_factory=list)
    input_schema: Optional[AgentIOSchema] = None
    output_schema: Optional[AgentIOSchema] = None            # ⚠️ AgentIOSchema 类型，不是 dict
    loop_compatible: bool = False
    llm_config: Optional[Dict[str, Any]] = None
    prompt_template: Optional[str] = None                    # 支持 {field} 占位符
    system_prompt: Optional[str] = None
```

```python
# ── workflow.py ──
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
)

@dataclass(frozen=True)
class InputMapping:
    source: str          # 6 种前缀之一（见下文）
    target_field: str    # 目标字段名

@dataclass(frozen=True)
class Step:
    id: str
    capability: CapabilityRef
    input_mappings: List[InputMapping] = field(default_factory=list)

@dataclass(frozen=True)
class LoopStep:
    id: str
    capability: CapabilityRef
    iterate_over: str                    # 数据源表达式（如 "step.parse.sections"）
    item_input_mappings: List[InputMapping] = field(default_factory=list)
    max_iterations: int = 100
    collect_as: str = "results"
    fail_strategy: str = "abort"         # "abort" | "skip" | "collect"

@dataclass(frozen=True)
class ParallelStep:
    id: str
    branches: List[Union[Step, LoopStep]] = field(default_factory=list)
    join_strategy: str = "all_success"   # "all_success" | "any_success" | "best_effort"

@dataclass(frozen=True)
class ConditionalStep:
    id: str
    condition_source: str                # 条件值的数据源表达式
    branches: Dict[str, Union[Step, LoopStep]] = field(default_factory=dict)
    default: Optional[Union[Step, LoopStep]] = None
```

```python
# ── context.py ──
from agently_skills_runtime.protocol.context import ExecutionContext, RecursionLimitError

@dataclass
class ExecutionContext:
    run_id: str
    bag: Dict[str, Any]                  # 全局共享数据
    step_outputs: Dict[str, Any]         # step_id → 输出
    call_chain: List[str]                # 调用链
    depth: int = 0
    max_depth: int = 10
```

### 2.2 InputMapping 的 6 种 source 前缀

| 前缀 | 含义 | 示例 |
|------|------|------|
| `context.{key}` | 从 context.bag 读取 | `"context.raw_content"` |
| `previous.{key}` | 从上一步输出读取 | `"previous.summary"` |
| `step.{step_id}.{key}` | 指定步骤的输出字段 | `"step.parse.sections"` |
| `step.{step_id}` | 步骤输出整体 | `"step.design"` |
| `literal.{value}` | 字面量 | `"literal.standard"` |
| `item` / `item.{key}` | 循环中当前元素 | `"item.title"` |

### 2.3 Runtime 层

```python
from agently_skills_runtime.runtime.engine import (
    CapabilityRuntime, RuntimeConfig, AdapterProtocol,
)

@dataclass(frozen=True)
class RuntimeConfig:
    max_depth: int = 10
    max_total_loop_iterations: int = 50000
    default_loop_max_iterations: int = 200
    # ⚠️ v0.4.0 的 RuntimeConfig 没有 workspace_root

# AdapterProtocol（typing.Protocol）
class AdapterProtocol(Protocol):
    async def execute(self, *, spec: Any, input: Dict[str, Any],
                      context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult: ...
```

**CapabilityRuntime 公共 API**：
```python
rt = CapabilityRuntime(config=RuntimeConfig())
rt.set_adapter(kind: CapabilityKind, adapter: AdapterProtocol) -> None
rt.register(spec: AnySpec) -> None
rt.register_many(specs: List[AnySpec]) -> None
rt.validate() -> List[str]              # 返回缺失的能力 ID
await rt.run(capability_id, *, input=None, context_bag=None, run_id=None, max_depth=None) -> CapabilityResult
```

### 2.4 Adapters 层

```python
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
```

**WorkflowAdapter**：内置，自动编排 steps。无需额外配置。
```python
WorkflowAdapter()  # 无参构造
```

**SkillAdapter**：加载 Skill 内容 + 处理 dispatch_rules。
```python
SkillAdapter(*, workspace_root: str = ".")
# execute() 行为：
#   1. 加载内容（inline → 直接返回 source；file → 从文件读取）
#   2. 检查 dispatch_rules：对每条规则，用 context.bag.get(condition) 检查是否 truthy
#      若匹配，调用 runtime._execute(target_spec, ...) 并将结果记入 metadata["dispatched"]
#   3. 返回 CapabilityResult(output=content_string, metadata={...})
```

**AgentAdapter**：桥接 LLM 执行。**这是连接真实 LLM 的关键**。
```python
AgentAdapter(
    *,
    runner: Optional[Callable[..., Awaitable[Any]]] = None,
    skill_content_loader: Optional[Callable[[SkillSpec], str]] = None,
)

# ⚠️ runner 签名（关键！）：
# async def runner(task: str, *, initial_history: Optional[List] = None) -> Any
#
# AgentAdapter.execute() 内部流程：
#   1. 合并 skills：spec.skills + registry.find_skills_injecting_to(agent_id)
#   2. 加载每个 skill 的内容文本
#   3. 调用 _build_task() 构造 task 字符串：
#      - 如有 prompt_template：用 input 做 format
#      - 拼接 skills 内容为 "--- 参考资料 ---"
#      - 如有 output_schema：追加 "请按以下格式输出 JSON："
#   4. 如有 system_prompt：构造 initial_history=[{"role":"system","content":...}]
#   5. 调用 runner(task, initial_history=initial_history)
#   6. 包装返回值为 CapabilityResult
#      - str → SUCCESS, output=str
#      - dict → SUCCESS, output=dict
#      - 其他 → SUCCESS, output=result
```

---

## 三、场景设计：Multi-Perspective Content Analyzer

### 3.1 场景概述

输入一段内容文本，经过：解析 → 逐段分析（循环）→ 多视角并行评审 → 按严重程度分流（条件）→ 汇总报告。

**13 个能力**：9 Agent + 2 Skill + 2 Workflow。每个组件都有不可替代的验证职责。

### 3.2 能力覆盖矩阵

| 框架能力 | 验证组件 |
|----------|---------|
| Agent 基础执行 | AG-001 content-parser |
| Agent loop_compatible | AG-002 section-analyzer |
| Agent 装载 Skill（skills 字段） | AG-003 tone-reviewer, AG-004 fact-checker |
| Agent prompt_template + system_prompt | 全部 9 个 Agent |
| Agent output_schema (AgentIOSchema) | 全部 9 个 Agent |
| Skill inline source | SK-001, SK-002 |
| Skill inject_to | SK-001 → AG-003, AG-004 |
| Skill dispatch_rules | SK-002 → AG-005 |
| Workflow Step（顺序） | WF-002 step 1, 3, 5 |
| Workflow LoopStep | WF-002 step 2 |
| Workflow ParallelStep | WF-001 |
| Workflow ConditionalStep | WF-002 step 4 |
| Workflow 嵌套 Workflow | WF-002 step 3 → WF-001 |
| InputMapping 6 种前缀 | 全部覆盖（见下文具体标注） |
| 递归深度保护 | WF-002 → WF-001 → Agent (3 层) |
| 循环失败策略 skip | WF-002 step 2 |

### 3.3 Skill 声明

```python
from agently_skills_runtime.protocol.capability import (
    CapabilitySpec, CapabilityKind, CapabilityRef,
)
from agently_skills_runtime.protocol.skill import SkillSpec, SkillDispatchRule

SK_001 = SkillSpec(
    base=CapabilitySpec(
        id="review-rubric",
        kind=CapabilityKind.SKILL,
        name="Review Rubric",
        description="Evaluation criteria injected into reviewer agents",
    ),
    source=(
        "## Content Review Rubric\n\n"
        "### Tone Criteria\n"
        "- Clarity (1-10)\n- Consistency (1-10)\n- Appropriateness (1-10)\n\n"
        "### Fact-Check Criteria\n"
        "- Verifiability (1-10)\n- Accuracy (1-10)\n- Source quality (1-10)\n\n"
        "### Severity: score>=7 → positive, 4<=score<7 → neutral, score<4 → critical"
    ),
    source_type="inline",
    inject_to=["tone-reviewer", "fact-checker"],  # ← 验证 inject_to
)

SK_002 = SkillSpec(
    base=CapabilitySpec(
        id="escalation-policy",
        kind=CapabilityKind.SKILL,
        name="Escalation Policy",
        description="Auto-dispatch deep investigator on critical issues",
    ),
    source="When critical issues found, trigger deep investigation.",
    source_type="inline",
    dispatch_rules=[                                # ← 验证 dispatch_rules
        SkillDispatchRule(
            condition="critical_detected",          # bag 中此 key 为 truthy 则触发
            target=CapabilityRef(id="deep-investigator"),
            priority=10,
        ),
    ],
)
```

### 3.4 Agent 声明

```python
from agently_skills_runtime.protocol.agent import AgentSpec, AgentIOSchema

AG_001 = AgentSpec(
    base=CapabilitySpec(id="content-parser", kind=CapabilityKind.AGENT, name="Content Parser"),
    system_prompt="You are a content structure analyst. Parse content into sections.",
    prompt_template="Parse the following content into sections:\n\n{raw_content}",
    output_schema=AgentIOSchema(fields={
        "title": "str: overall title",
        "sections": "list: [{title, content, word_count}]",
        "total_sections": "int",
    }),
)

AG_002 = AgentSpec(
    base=CapabilitySpec(id="section-analyzer", kind=CapabilityKind.AGENT, name="Section Analyzer"),
    system_prompt="You are a content quality analyst.",
    prompt_template="Analyze section:\nTitle: {section_title}\nContent: {section_content}\nMode: {analysis_mode}",
    output_schema=AgentIOSchema(fields={
        "section_title": "str",
        "quality_score": "float: 0-10",
        "issues": "list[str]",
        "highlights": "list[str]",
    }),
    loop_compatible=True,    # ← 验证 loop_compatible
)

AG_003 = AgentSpec(
    base=CapabilitySpec(id="tone-reviewer", kind=CapabilityKind.AGENT, name="Tone Reviewer"),
    system_prompt="You are a tone and style expert. Use the review rubric provided.",
    prompt_template="Review the tone of:\n\n{content_summary}",
    output_schema=AgentIOSchema(fields={
        "tone_score": "float: 0-10",
        "tone_label": "str: formal/casual/mixed",
        "recommendations": "list[str]",
    }),
    skills=["review-rubric"],    # ← 验证 Agent 装载 Skill（字符串 ID）
)

AG_004 = AgentSpec(
    base=CapabilitySpec(id="fact-checker", kind=CapabilityKind.AGENT, name="Fact Checker"),
    system_prompt="You are a fact-checking specialist. Use the review rubric provided.",
    prompt_template="Verify factual claims in:\n\n{content_summary}",
    output_schema=AgentIOSchema(fields={
        "fact_score": "float: 0-10",
        "verified_claims": "int",
        "disputed_claims": "int",
        "unverifiable_claims": "int",
    }),
    skills=["review-rubric"],    # ← 同一 Skill 注入多个 Agent
)

AG_005 = AgentSpec(
    base=CapabilitySpec(id="deep-investigator", kind=CapabilityKind.AGENT, name="Deep Investigator"),
    system_prompt="You are a deep investigation specialist.",
    prompt_template="Conduct deep investigation on:\n\n{target}",
    output_schema=AgentIOSchema(fields={
        "root_causes": "list[str]",
        "severity_assessment": "str",
        "recommended_actions": "list[str]",
    }),
    # ← 不在任何 Workflow 显式 steps 中，由 SK-002 dispatch 触发
)

AG_006 = AgentSpec(
    base=CapabilitySpec(id="positive-summarizer", kind=CapabilityKind.AGENT, name="Positive Summarizer"),
    system_prompt="Summarize positive analysis results.",
    prompt_template="Content scored positively. Highlights:\n{analysis_data}",
    output_schema=AgentIOSchema(fields={"summary": "str", "confidence": "float"}),
)

AG_007 = AgentSpec(
    base=CapabilitySpec(id="critical-reporter", kind=CapabilityKind.AGENT, name="Critical Reporter"),
    system_prompt="Generate critical issue report.",
    prompt_template="Content has critical issues:\n{analysis_data}",
    output_schema=AgentIOSchema(fields={"summary": "str", "action_items": "list[str]", "urgency": "str"}),
)

AG_008 = AgentSpec(
    base=CapabilitySpec(id="neutral-summarizer", kind=CapabilityKind.AGENT, name="Neutral Summarizer"),
    system_prompt="Provide a balanced summary.",
    prompt_template="Content has mixed results:\n{analysis_data}",
    output_schema=AgentIOSchema(fields={"summary": "str", "areas_for_improvement": "list[str]"}),
)

AG_009 = AgentSpec(
    base=CapabilitySpec(id="report-compiler", kind=CapabilityKind.AGENT, name="Report Compiler"),
    system_prompt="Compile all analysis into a final report.",
    prompt_template=(
        "Compile final report:\n"
        "Section analyses: {section_analyses}\n"
        "Review results: {review_results}\n"
        "Summary: {summary}"
    ),
    output_schema=AgentIOSchema(fields={
        "title": "str",
        "executive_summary": "str",
        "detailed_findings": "list[str]",
        "overall_score": "float",
        "recommendation": "str",
    }),
)

ALL_AGENTS = [AG_001, AG_002, AG_003, AG_004, AG_005, AG_006, AG_007, AG_008, AG_009]
```

### 3.5 Workflow 声明

```python
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
)

# ── 子流程：并行评审 ──
WF_001 = WorkflowSpec(
    base=CapabilitySpec(id="parallel-review", kind=CapabilityKind.WORKFLOW, name="Parallel Review"),
    steps=[
        ParallelStep(
            id="multi-review",
            branches=[
                Step(
                    id="tone",
                    capability=CapabilityRef(id="tone-reviewer"),
                    input_mappings=[
                        InputMapping(source="context.content_summary", target_field="content_summary"),
                    ],
                ),
                Step(
                    id="facts",
                    capability=CapabilityRef(id="fact-checker"),
                    input_mappings=[
                        InputMapping(source="context.content_summary", target_field="content_summary"),
                    ],
                ),
            ],
            join_strategy="best_effort",   # ← 验证 ParallelStep + join_strategy
        ),
    ],
    output_mappings=[
        InputMapping(source="step.multi-review", target_field="review_results"),
    ],
)

# ── 主流程：全编排模式 ──
WF_002 = WorkflowSpec(
    base=CapabilitySpec(id="content-analysis", kind=CapabilityKind.WORKFLOW, name="Content Analysis Pipeline"),
    steps=[
        # Step 1: 解析（验证 context. 前缀 + literal. 前缀）
        Step(
            id="parse",
            capability=CapabilityRef(id="content-parser"),
            input_mappings=[
                InputMapping(source="context.raw_content", target_field="raw_content"),
                InputMapping(source="literal.standard", target_field="parse_mode"),
            ],
        ),

        # Step 2: 循环分析（验证 LoopStep + step.X.Y 前缀 + item.key 前缀）
        LoopStep(
            id="section-loop",
            capability=CapabilityRef(id="section-analyzer"),
            iterate_over="step.parse.sections",
            item_input_mappings=[
                InputMapping(source="item.title", target_field="section_title"),
                InputMapping(source="item.content", target_field="section_content"),
                InputMapping(source="context.analysis_depth", target_field="analysis_mode"),
            ],
            max_iterations=50,
            fail_strategy="skip",          # ← 验证 fail_strategy
        ),

        # Step 3: 嵌套子流程（验证 Workflow 嵌套 Workflow）
        Step(
            id="parallel-review-step",
            capability=CapabilityRef(id="parallel-review"),  # ← 引用子 Workflow
            input_mappings=[
                InputMapping(source="step.parse.title", target_field="content_summary"),
            ],
        ),

        # Step 4: 条件分支（验证 ConditionalStep）
        ConditionalStep(
            id="route-by-severity",
            condition_source="context.overall_severity",
            branches={
                "positive": Step(
                    id="summarize-positive",
                    capability=CapabilityRef(id="positive-summarizer"),
                    input_mappings=[
                        InputMapping(source="step.section-loop", target_field="analysis_data"),
                    ],
                ),
                "critical": Step(
                    id="report-critical",
                    capability=CapabilityRef(id="critical-reporter"),
                    input_mappings=[
                        InputMapping(source="step.section-loop", target_field="analysis_data"),
                    ],
                ),
            },
            default=Step(
                id="summarize-neutral",
                capability=CapabilityRef(id="neutral-summarizer"),
                input_mappings=[
                    InputMapping(source="step.section-loop", target_field="analysis_data"),
                ],
            ),
        ),

        # Step 5: 编译报告（验证 previous. 前缀 + 跨步骤消费）
        Step(
            id="compile",
            capability=CapabilityRef(id="report-compiler"),
            input_mappings=[
                InputMapping(source="step.section-loop", target_field="section_analyses"),
                InputMapping(source="step.parallel-review-step", target_field="review_results"),
                InputMapping(source="previous.summary", target_field="summary"),
            ],
        ),
    ],
    output_mappings=[
        InputMapping(source="step.parse", target_field="parsed_content"),
        InputMapping(source="step.section-loop", target_field="section_analyses"),
        InputMapping(source="step.parallel-review-step", target_field="review_results"),
        InputMapping(source="step.route-by-severity", target_field="severity_summary"),
        InputMapping(source="step.compile", target_field="final_report"),
    ],
)

ALL_WORKFLOWS = [WF_001, WF_002]
ALL_SKILLS = [SK_001, SK_002]
ALL_SPECS = ALL_SKILLS + ALL_AGENTS + ALL_WORKFLOWS  # 13 个能力
```

### 3.6 Mock Adapter 规格

```python
class PrototypeMockAdapter:
    """Mock adapter：按 agent_id 返回有意义的 mock 数据。
    关键：mock 输出的 key 必须与下游 InputMapping 的 source 匹配。"""

    async def execute(self, *, spec, input, context, runtime):
        aid = spec.base.id

        if aid == "content-parser":
            return _ok({
                "title": "Sample Analysis Document",
                "sections": [
                    {"title": "Introduction", "content": "Opening paragraph about the topic.", "word_count": 120},
                    {"title": "Main Argument", "content": "Core thesis and reasoning.", "word_count": 350},
                    {"title": "Evidence", "content": "Supporting data and references.", "word_count": 280},
                ],
                "total_sections": 3,
            })

        if aid == "section-analyzer":
            title = input.get("section_title", "Unknown")
            scores = {"Introduction": 8.5, "Main Argument": 5.2, "Evidence": 3.1}
            score = scores.get(title, 6.0)
            return _ok({
                "section_title": title,
                "quality_score": score,
                "issues": [f"Issue found in '{title}'"] if score < 7 else [],
                "highlights": [f"Strong point in '{title}'"] if score >= 7 else [],
            })

        if aid == "tone-reviewer":
            return _ok({"tone_score": 7.2, "tone_label": "formal",
                        "recommendations": ["Vary sentence structure"]})

        if aid == "fact-checker":
            return _ok({"fact_score": 6.8, "verified_claims": 5,
                        "disputed_claims": 1, "unverifiable_claims": 2})

        if aid == "deep-investigator":
            return _ok({"root_causes": ["Insufficient citations", "Outdated data"],
                        "severity_assessment": "high",
                        "recommended_actions": ["Add primary sources", "Update statistics"]})

        if aid == "positive-summarizer":
            return _ok({"summary": "Content is well-structured with strong highlights.", "confidence": 0.85})

        if aid == "critical-reporter":
            return _ok({"summary": "Content has critical issues requiring attention.",
                        "action_items": ["Revise evidence section", "Add citations"], "urgency": "high"})

        if aid == "neutral-summarizer":
            return _ok({"summary": "Content shows mixed quality across sections.",
                        "areas_for_improvement": ["Evidence quality", "Source diversity"]})

        if aid == "report-compiler":
            return _ok({
                "title": "Content Analysis Report",
                "executive_summary": "Multi-perspective analysis complete.",
                "detailed_findings": ["3 sections analyzed", "Tone: formal (7.2/10)", "Facts: 5 verified, 1 disputed"],
                "overall_score": 6.5,
                "recommendation": "Revise evidence section before publication.",
            })

        return CapabilityResult(status=CapabilityStatus.FAILED, error=f"Unknown agent: {aid}")

def _ok(output):
    return CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)
```

### 3.7 三个验证场景

| 场景 | context_bag.overall_severity | 走的分支 | 验证点 |
|------|-----|--------|--------|
| A: neutral | `"neutral"` | default → neutral-summarizer | ConditionalStep.default |
| B: critical | `"critical"` | branches["critical"] → critical-reporter | ConditionalStep.branches |
| C: positive | `"positive"` | branches["positive"] → positive-summarizer | ConditionalStep.branches |

---

## 四、LLM Runner 规格（真实模式）

当用户切换到 Real LLM 模式时，使用 `AgentAdapter` + 自定义 runner 连接 OpenAI 兼容 API。

```python
import httpx, json

async def create_llm_runner(base_url: str, api_key: str, model: str):
    """创建一个调用 OpenAI 兼容 API 的 runner。
    签名必须是 async def runner(task: str, *, initial_history=None) -> Any"""

    async def runner(task: str, *, initial_history=None) -> dict:
        messages = []
        if initial_history:
            messages.extend(initial_history)
        messages.append({"role": "user", "content": task})

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.7},
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

        # 尝试解析为 JSON，失败则返回原始字符串
        try:
            return json.loads(content)
        except (json.JSONDecodeError, KeyError):
            return content

    return runner
```

**组装方式**：
```python
from agently_skills_runtime.adapters.agent_adapter import AgentAdapter

runner = await create_llm_runner(base_url, api_key, model)
agent_adapter = AgentAdapter(runner=runner)
rt.set_adapter(CapabilityKind.AGENT, agent_adapter)
```

**与 Mock 模式的切换**：后端维护一个全局 runtime 实例。切换模式时：
1. 创建新的 CapabilityRuntime
2. 根据模式选择 adapter（MockAdapter 或 AgentAdapter）
3. 重新注册所有 13 个 Spec
4. validate()

---

## 五、后端规格（FastAPI）

### 5.1 依赖

```
fastapi
uvicorn
httpx
agently-skills-runtime   # pip install -e . 从仓库根目录安装
```

### 5.2 API 设计

```
GET  /                     → 返回 React 前端 HTML
GET  /api/capabilities     → 返回已注册的 13 个能力列表
GET  /api/config           → 返回当前 LLM 配置和模式
POST /api/config           → 更新 LLM 配置 { base_url, api_key, model }
POST /api/mode             → 切换模式 { mode: "mock" | "real" }
POST /api/run              → 执行场景 { scenario: "neutral"|"critical"|"positive"|"custom", custom_input?: string }
GET  /api/run/{run_id}/events → SSE: 实时推送执行进度事件
```

### 5.3 SSE 事件流设计

执行过程中通过 SSE 推送以下事件：

```
event: step_start
data: {"step_id": "parse", "capability_id": "content-parser", "type": "Step"}

event: step_complete
data: {"step_id": "parse", "status": "SUCCESS", "output": {...}, "duration_ms": 12.5}

event: loop_item
data: {"step_id": "section-loop", "index": 0, "item": "Introduction", "status": "SUCCESS"}

event: parallel_start
data: {"step_id": "multi-review", "branches": ["tone", "facts"]}

event: branch_complete
data: {"step_id": "multi-review", "branch_id": "tone", "status": "SUCCESS"}

event: conditional_route
data: {"step_id": "route-by-severity", "condition_value": "neutral", "selected_branch": "default"}

event: workflow_complete
data: {"status": "SUCCESS", "output": {...}, "duration_ms": 156.7}

event: error
data: {"message": "..."}
```

**实现提示**：如果框架层没有暴露步骤级别的 hook，后端可以：
- 在调用 `rt.run()` 之前和之后推送 workflow_start / workflow_complete
- 用包装 adapter 在 execute() 前后推送 step_start / step_complete
- 包装 adapter 记录调用信息并通过 asyncio.Queue 传递给 SSE handler

### 5.4 包装 Adapter（实现步骤级 SSE 推送的关键）

```python
class InstrumentedAdapter:
    """包装一个 adapter，在执行前后推送 SSE 事件。"""

    def __init__(self, inner, event_queue: asyncio.Queue):
        self._inner = inner
        self._queue = event_queue

    async def execute(self, *, spec, input, context, runtime):
        step_id = spec.base.id
        await self._queue.put({"event": "step_start", "data": {
            "step_id": step_id, "capability_id": spec.base.id, "name": spec.base.name,
        }})
        t0 = time.monotonic()
        result = await self._inner.execute(spec=spec, input=input, context=context, runtime=runtime)
        elapsed = (time.monotonic() - t0) * 1000
        await self._queue.put({"event": "step_complete", "data": {
            "step_id": step_id, "status": result.status.value, "duration_ms": round(elapsed, 1),
            "output_preview": _truncate(result.output),
        }})
        return result
```

### 5.5 前端托管

后端同时 serve React 前端。React 页面为单个 HTML 文件，通过 CDN 加载 React + Babel。

```python
@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("frontend/index.html").read_text()
```

---

## 六、React 前端规格

### 6.1 技术方案

- 单文件 HTML：`frontend/index.html`
- 通过 CDN 加载 React 18 + ReactDOM + Babel standalone
- 通过 CDN 加载 Tailwind CSS
- 不需要构建工具，直接用 `<script type="text/babel">`

### 6.2 界面布局

```
┌──────────────────────────────────────────────────────────────┐
│                        顶部标题栏                              │
│  agently-skills-runtime Prototype Validator                   │
│  [Mock Mode ●] / [Real LLM Mode ○]                           │
├────────────────────┬─────────────────────────────────────────┤
│   左侧面板 (320px)  │              主区域                       │
│                    │                                          │
│  ┌──────────────┐  │  ┌─────────────────────────────────────┐│
│  │ LLM 配置      │  │  │ Workflow DAG 可视化                   ││
│  │ Base URL     │  │  │                                      ││
│  │ API Key      │  │  │  [parse] → [section-loop] →          ││
│  │ Model        │  │  │  [parallel-review] → [route] →       ││
│  │ [Save]       │  │  │  [compile]                           ││
│  └──────────────┘  │  │                                      ││
│                    │  │  步骤状态用颜色表示：                     ││
│  ┌──────────────┐  │  │  灰=待执行 蓝=执行中 绿=成功 红=失败     ││
│  │ 场景选择      │  │  └─────────────────────────────────────┘│
│  │ ○ Neutral    │  │                                          │
│  │ ○ Critical   │  │  ┌─────────────────────────────────────┐│
│  │ ○ Positive   │  │  │ 执行日志（实时滚动）                     ││
│  │ ○ Custom     │  │  │ [10:23:01] step_start: parse         ││
│  │              │  │  │ [10:23:01] step_complete: parse ✓     ││
│  │ [textarea    │  │  │ [10:23:02] loop_item: Introduction ✓  ││
│  │  custom]     │  │  │ ...                                   ││
│  └──────────────┘  │  └─────────────────────────────────────┘│
│                    │                                          │
│  [▶ Run Analysis] │  ┌─────────────────────────────────────┐│
│                    │  │ 结果面板（可折叠各步骤输出）              ││
│  ┌──────────────┐  │  │ ▸ parsed_content                     ││
│  │ 能力注册表    │  │  │ ▸ section_analyses                   ││
│  │ 13 registered│  │  │ ▸ review_results                     ││
│  │ 9 Agents     │  │  │ ▸ severity_summary                   ││
│  │ 2 Skills     │  │  │ ▾ final_report                       ││
│  │ 2 Workflows  │  │  │   { title: "...", score: 6.5, ... }  ││
│  └──────────────┘  │  └─────────────────────────────────────┘│
└────────────────────┴─────────────────────────────────────────┘
```

### 6.3 核心功能需求

#### A. 模式切换

- 页面顶部有 Mock / Real LLM 的切换按钮
- 切换到 Real LLM 时，左侧 LLM 配置面板变为可编辑
- 切换到 Mock 时，配置面板变灰（不可编辑但保留值）
- 切换时调用 `POST /api/mode`

#### B. LLM 配置面板

- 三个输入框：Base URL、API Key（密码类型）、Model Name
- Save 按钮 → `POST /api/config`
- 加载时从 `GET /api/config` 读取
- 配置保存成功后显示绿色提示

#### C. 场景选择与执行

- 4 个单选按钮：Neutral / Critical / Positive / Custom
- 选择 Custom 时显示 textarea 供输入自定义内容
- "Run Analysis" 按钮 → `POST /api/run`
- 执行中按钮变为 disabled 并显示 spinner

#### D. Workflow DAG 可视化

- 用简单的 HTML/CSS 方块 + 箭头表示工作流拓扑
- 主 workflow 的 5 个步骤横向排列
- 嵌套的 parallel-review 展开为子图
- 条件分支展示三条路径
- 每个步骤方块的背景色实时更新：
  - `#e5e7eb`（灰）= pending
  - `#93c5fd`（蓝）= running
  - `#86efac`（绿）= success
  - `#fca5a5`（红）= failed
  - `#fde68a`（黄）= skipped

#### E. 实时日志

- 通过 EventSource 连接 SSE 端点
- 每条事件显示时间戳 + 事件类型 + 关键信息
- 自动滚动到底部
- 不同事件类型用不同颜色标记

#### F. 结果面板

- workflow_complete 后显示
- 按 output_mappings 的 5 个 key 分组展示
- 每个 key 可折叠/展开
- JSON 用代码高亮显示（简单的 `<pre>` 即可）
- 显示总耗时和总体状态

#### G. 能力注册表

- 左下角显示已注册的 13 个能力
- 按类型分组（Agent / Skill / Workflow）
- 点击可展开看 ID 和 name

### 6.4 设计风格

- 整体风格：深色主题，工程风/Dashboard 风
- 背景色：`#0f172a`（slate-900）
- 卡片背景：`#1e293b`（slate-800）
- 边框：`#334155`（slate-700）
- 文字：`#f1f5f9`（slate-100）
- 强调色：`#38bdf8`（sky-400）
- 成功：`#4ade80`（green-400）
- 错误：`#f87171`（red-400）
- 字体：等宽字体（JetBrains Mono 或 Fira Code 通过 Google Fonts 加载）

---

## 七、文件结构

```
examples/00_prototype_validation/
├── server.py               # FastAPI 后端主文件
├── specs.py                # 全部 13 个 Spec 声明
├── mock_adapter.py         # PrototypeMockAdapter
├── llm_runner.py           # create_llm_runner() + AgentAdapter 组装
├── instrumented.py         # InstrumentedAdapter（SSE 事件推送）
├── frontend/
│   └── index.html          # 单文件 React 前端
├── requirements.txt        # fastapi, uvicorn, httpx
├── README.md               # 启动说明
└── test_prototype.py       # pytest 断言（可选，确保 mock 模式正确）
```

---

## 八、启动流程

```bash
# 1. 安装框架（从仓库根目录）
pip install -e ".[dev]"

# 2. 安装原型依赖
pip install fastapi uvicorn httpx

# 3. 启动
cd examples/00_prototype_validation
python server.py
# → Uvicorn running on http://localhost:8000

# 4. 浏览器访问
open http://localhost:8000
```

---

## 九、实现约束

1. **不修改 src/agently_skills_runtime/ 中的任何框架代码**
2. **所有 Spec 声明严格按第三节的字段定义**——特别注意 `skills: List[str]`（不是 CapabilityRef）和 `output_schema: AgentIOSchema`（不是 dict）
3. **Mock adapter 的输出 key 必须与 InputMapping 的 source 表达式匹配**——这是数据流连通的关键
4. **SSE 推送用 asyncio.Queue 解耦**——不要在 adapter 内部直接写 HTTP 响应
5. **AgentAdapter 的 runner 签名必须是 `async def runner(task: str, *, initial_history=None) -> Any`**——这是框架的真实签名，不能改
6. **前端是纯 CDN 加载的单文件 HTML**——不需要 npm/webpack/vite，保持零构建工具依赖
7. **错误处理**：LLM 配置错误、网络超时、API 返回错误都应在前端友好显示，不能白屏
8. **文件大小**：前端 index.html 预计 500-800 行；后端 server.py 预计 200-350 行

---

## 十、验证清单

### Mock 模式验证

- [ ] 访问 http://localhost:8000 看到完整界面
- [ ] 默认 Mock 模式
- [ ] 点击 Run（Neutral 场景）→ DAG 上步骤依次变绿
- [ ] 日志面板实时滚动显示每个步骤的事件
- [ ] 结果面板显示 5 个 output_mapping 的完整输出
- [ ] final_report.overall_score == 6.5
- [ ] 切换到 Critical 场景运行 → severity_summary 包含 action_items
- [ ] 切换到 Positive 场景运行 → severity_summary 包含 confidence

### Real LLM 模式验证

- [ ] 切换到 Real LLM 模式
- [ ] 配置 LLM（如 OpenRouter / 本地 Ollama）
- [ ] Save 成功
- [ ] 运行 Neutral 场景 → 真实 LLM 返回非 mock 内容
- [ ] 各步骤输出结构正确（即使内容不同，key 应存在）

### 框架能力验证

- [ ] 13 个能力全部注册，validate() 无缺失
- [ ] LoopStep：section_analyses 列表长度 == sections 数量
- [ ] ParallelStep：review_results 包含 2 个分支结果
- [ ] ConditionalStep：3 个场景走了不同路径
- [ ] Skill inject_to：tone-reviewer 和 fact-checker 在 Real 模式下收到了 rubric 内容
- [ ] Workflow 嵌套：parallel-review 子流程被正确调用

---

## 十一、README.md 内容

```markdown
# Framework Validation Prototype

验证 agently-skills-runtime v0.4.0 全部框架能力的交互式原型。

## 快速开始

pip install -e "../../[dev]"
pip install fastapi uvicorn httpx
python server.py

访问 http://localhost:8000

## 功能

- **Mock 模式**：离线运行，验证框架编排能力
- **Real LLM 模式**：连接 OpenAI 兼容 API，验证真实 LLM 集成
- **实时可视化**：Workflow DAG 步骤状态实时更新
- **3 个预设场景**：neutral / critical / positive 覆盖条件分支

## 覆盖的框架能力

13 个能力（9 Agent + 2 Skill + 2 Workflow）覆盖：
- Step / LoopStep / ParallelStep / ConditionalStep / 嵌套 Workflow
- Skill inject_to + dispatch_rules
- Agent skills 装载 + loop_compatible
- InputMapping 全部 6 种前缀
- 递归深度保护 + 循环失败策略
```
