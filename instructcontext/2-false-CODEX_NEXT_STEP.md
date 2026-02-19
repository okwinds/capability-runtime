# Codex CLI 指令：v0.2.0 → v0.2.1 补齐执行通路

> 本指令用于 `codex --model claude-sonnet-4-20250514` 执行
> 真相源：`instructcontext/1-true-CODEX_PROMPT.md`
> 上游 pin：Agently 4.0.7 + skills-runtime-sdk 0.1.1

---

## 背景

v0.2.0 已完成 CODEX_PROMPT Step 1~6 的最低验收门禁（protocol + runtime + adapters 骨架 + 测试 + 归档）。但框架当前只能用 mock runner 跑测试，无法连接真实 LLM 执行 Agent。

本轮目标：**补齐从"协议空转"到"真实可执行"的最后通路**，以及关键测试护栏。

---

## 执行范围（严格遵守，不做范围外的事）

### ✅ In Scope

1. 迁移 `llm_backend.py`
2. 实现 `DefaultAgentRunner`
3. 增强 `upstream.py` 版本 pin 校验
4. 补齐 ParallelStep / ConditionalStep / dispatch_rules 测试
5. 接入 ReportBuilder 到执行流
6. 更新 `__init__.py` 导出（如有新增公共类型）
7. 更新 pyproject.toml 版本到 0.2.1

### ❌ Out of Scope

- 不修改 protocol/ 层的任何类型定义
- 不修改上游 Agently 或 skills-runtime-sdk 源码
- 不添加 YAML 声明式注册（后续迭代）
- 不添加业务逻辑（存储、人机交互、UI）
- 不改动 legacy/ 目录（只从中复制代码）

---

## Task 1：迁移 llm_backend.py

### 来源
`legacy/2026-02-18-bridge-only-mainline/src/agently_skills_runtime/adapters/agently_backend.py`

### 目标
`src/agently_skills_runtime/adapters/llm_backend.py`

### 操作
1. 复制旧 `agently_backend.py` 到 `adapters/llm_backend.py`
2. 更新 import 路径（`agently_skill_runtime` → `agently_skills_runtime`）
3. 保留所有功能不变：
   - `AgentlyChatBackend`（实现 SDK ChatBackend 接口）
   - `AgentlyRequester` / `AgentlyRequesterFactory` Protocol
   - `build_openai_compatible_requester_factory()`
4. 在文件顶部添加注释：标明从何处迁移、功能不变、依赖上游可选
5. 因为上游包可能未安装，所有上游 import 必须用 try/except 包裹，缺失时在模块级设置 `_HAS_UPSTREAM = False`
6. 不为此文件写单测（依赖上游真实安装），但确保 import 不报错

### 验证
```python
python -c "from agently_skills_runtime.adapters import llm_backend; print('OK')"
```
即使上游未安装也不应报错（import 成功，使用时才报错）。

---

## Task 2：实现 DefaultAgentRunner

### 位置
`src/agently_skills_runtime/adapters/agent_adapter.py`（在现有文件中追加）

### 规格
```python
class DefaultAgentRunner:
    """
    默认 Agent 执行器——桥接 Agently + skills-runtime-sdk。

    需要上游可用时才能实例化。
    若上游不可用，应在 __init__ 时抛出 DependencyError。
    """

    def __init__(self, *, agently_agent: Any = None, llm_config: dict | None = None) -> None:
        """
        参数：
        - agently_agent：宿主提供的 Agently agent 实例（可选，不提供则内部创建）
        - llm_config：LLM 配置 dict（base_url, model, api_key 等）
        """
        ...

    async def __call__(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        skills_text: str,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """
        执行流程：
        1. 从 spec.llm_config 或 self.llm_config 获取 LLM 配置
        2. 构造 task = skills_text + JSON(input)
        3. 如果 agently_agent 可用：用 Agently agent 执行
        4. 否则：用 llm_backend 的 requester 直接调用
        5. 收集输出，构造 CapabilityResult
        """
        ...
```

### 关键约束
- 所有上游 import 用 try/except，缺失时 `__init__` 抛 `DependencyError`
- 不强制要求上游安装（framework core 仍可独立运行）
- `AgentAdapter.__init__` 的 `runner` 参数默认值保持 `None`（向后兼容）

### 在 `__init__.py` 中**不导出** DefaultAgentRunner（它是可选适配层）

---

## Task 3：增强 upstream.py 版本 pin 校验

### 位置
`src/agently_skills_runtime/adapters/upstream.py`

### 当前状态
只有 `find_spec()` 检查模块存在性。

### 增强
```python
UPSTREAM_PINS = {
    "agently": "4.0.7",
    "skills_runtime_sdk": "0.1.1",  # 对应 agent_sdk
}

def check_upstream_versions(mode: str = "warn") -> list[str]:
    """
    检查上游版本。

    参数：
    - mode: "off" | "warn" | "error"

    返回：
    - 版本不匹配的警告/错误消息列表

    行为：
    - "off"：不检查
    - "warn"：检查并返回警告（不阻断）
    - "error"：检查并在不匹配时抛 DependencyError
    """
```

### 测试
`tests/adapters/test_upstream.py`：
- 已安装且版本匹配 → 无警告
- 已安装但版本不匹配 → warn 模式返回警告
- 未安装 → warn 模式返回"未安装"消息
- error 模式 + 不匹配 → 抛异常

---

## Task 4：补齐 ParallelStep 测试

### 位置
`tests/scenarios/test_workflow_parallel.py`

### 场景
```
WorkflowSpec:
  steps:
    - ParallelStep(id="para", branches=[
        Step(id="branch-a", capability=agent-a),
        Step(id="branch-b", capability=agent-b),
      ], join_strategy="all_success")
```

### 验证点
- 两个 branch 都成功 → ParallelStep 成功
- 一个 branch 失败 + all_success → ParallelStep 失败
- 一个 branch 失败 + best_effort → ParallelStep 成功（partial）
- step_outputs 正确记录并行结果

---

## Task 5：补齐 ConditionalStep 测试

### 位置
`tests/scenarios/test_workflow_conditional.py`

### 场景
```
WorkflowSpec:
  steps:
    - Step(id="classify", capability=agent-classifier)
    - ConditionalStep(
        id="route",
        condition_source="step.classify.category",
        branches={
          "A": Step(id="handle-a", capability=agent-a),
          "B": Step(id="handle-b", capability=agent-b),
        },
        default=Step(id="handle-default", capability=agent-default),
      )
```

### 验证点
- condition 匹配 "A" → 走 agent-a
- condition 匹配 "B" → 走 agent-b
- condition 无匹配 + 有 default → 走 default
- condition 无匹配 + 无 default → 返回失败（或跳过，视实现）

---

## Task 6：补齐 SkillAdapter dispatch_rules 测试

### 位置
`tests/adapters/test_skill_adapter_dispatch.py`

### 场景
- Skill 有 dispatch_rules，condition 为 bag key → 匹配时委托目标
- 多条 rules，按 priority 排序 → 高优先级先评估
- 无 dispatch_rules → 返回 skill 内容

---

## Task 7：接入 ReportBuilder 到执行流

### 改动点

1. `runtime/engine.py` 的 `run()` 方法：
   - 创建 `ReportBuilder(run_id=run_id, capability_id=capability_id)`
   - emit "run.started"
   - 执行完成后 emit "run.completed" 或 "run.failed"
   - 将 `builder.build()` 赋给 `CapabilityResult.report`

2. `adapters/workflow_adapter.py`：
   - 在每个 step 执行前后 emit "step.started" / "step.completed"
   - 在 loop iteration 中 emit "loop.iteration"

3. 传递方式：通过 `ExecutionContext.bag["__report_builder__"]` 透传（不改 Protocol 类型定义）

### 测试
在 `test_workflow_with_loop.py` 中增加断言：
- `result.report is not None`
- `result.report.events` 非空
- 包含 "run.started" 和 "run.completed" 事件

---

## Task 8：最终清理

1. 更新 `pyproject.toml` 版本到 `0.2.1`
2. 在 `adapters/__init__.py` 中添加 llm_backend 的条件导出
3. 更新 README.md 的"最小示例"部分（如有 API 变化）
4. 在 `docs/task-summaries/` 下创建本轮的 task-summary

---

## 验证命令

全部完成后，运行以下命令并确保通过：

```bash
# 1. 安装
python -m pip install -e ".[dev]"

# 2. Import 验收
python -c "from agently_skills_runtime import CapabilityRuntime, SkillSpec, AgentSpec, WorkflowSpec; print('OK')"
python -c "from agently_skills_runtime.adapters import llm_backend; print('llm_backend OK')"

# 3. 离线回归
pytest -q

# 4. 确认新增测试存在且通过
pytest -q tests/scenarios/test_workflow_parallel.py
pytest -q tests/scenarios/test_workflow_conditional.py
pytest -q tests/adapters/test_skill_adapter_dispatch.py
pytest -q tests/adapters/test_upstream.py
```

---

## 关键约束（重复强调）

1. **Python 3.10+**，使用 `from __future__ import annotations`
2. **不侵入上游**：Agently 和 skills-runtime-sdk 的源码不改
3. **上游可选**：protocol/ 和 runtime/ 必须不依赖上游即可运行和测试
4. **adapters/ 中的上游依赖必须 try/except 保护**：import 失败时设标志位，使用时 fail-fast
5. **测试必须离线可跑**：不依赖真实 LLM/网络/数据库
6. **不做业务逻辑**：框架只提供"能力组织"，不做存储/UI/人机交互
