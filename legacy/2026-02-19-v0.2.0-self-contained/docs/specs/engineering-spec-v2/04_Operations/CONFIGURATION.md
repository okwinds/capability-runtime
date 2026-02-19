# 配置（Configuration, v2）

> 目标：定义 `RuntimeConfig` 字段、默认值、风险与约束，保证“可复刻运行”。
>
> 真相源：`instructcontext/CODEX_PROMPT.md`（runtime/engine.py 注释）

---

## 1) RuntimeConfig（实现级字段）

### 字段清单

| 字段 | 类型 | 默认值 | 说明 | 风险/注意事项 |
|---|------|--------|------|---------------|
| `workspace_root` | `str` | `"."` | 工作区根目录（用于 skill file 等相对路径解析） | 需要防路径越界（实现阶段在 adapter 中处理） |
| `sdk_config_paths` | `List[str]` | `[]` | 上游 SDK 配置路径（overlay 列表） | 路径不可用时应给出可诊断错误 |
| `agently_agent` | `Any` | `None` | 宿主提供的 Agently agent 实例（供 AgentAdapter 使用） | 若为 None，则 Agent 能力不可执行（应返回 FAILED） |
| `preflight_mode` | `str` | `"error"` | `error \| warn \| off`（预检模式；v0.2.0 允许最小实现） | 预检策略不应引入人机交互语义 |
| `max_loop_iterations` | `int` | `200` | 全局循环上限（与 LoopStep.max_iterations 共同约束） | 过大可能导致资源消耗；过小可能导致正常任务失败 |
| `max_depth` | `int` | `10` | 全局嵌套深度上限（传入 ExecutionContext） | 防止无限递归；需有单测护栏 |
| `skill_uri_allowlist` | `List[str]` | `[]` | Skill URI 前缀白名单（仅 `source_type="uri"` 使用） | 默认空列表即禁用 URI 加载；需显式授权 |

---

## 2) 默认值策略

- 默认值以“安全与可回归”为优先：
  - `max_depth=10`：避免深度爆炸；
  - `max_loop_iterations=200`：避免循环资源消耗；
  - `preflight_mode="error"`：默认快速失败，避免静默漂移。
  - `skill_uri_allowlist=[]`：默认禁用 Skill URI，防止未授权加载外部/本地 URI。

---

## 3) 配置使用示例（实现阶段验收参考）

```python
from agently_skills_runtime import CapabilityRuntime, RuntimeConfig

runtime = CapabilityRuntime(config=RuntimeConfig(
    workspace_root=".",
    agently_agent=my_agent,
    preflight_mode="error",
    max_loop_iterations=200,
    max_depth=10,
    skill_uri_allowlist=["file://", "https://trusted.example/skills/"],
))
```

## 3.1) Skill URI 安全策略（v0.2.0）

- `SkillSpec.source_type="uri"` 仅在 `RuntimeConfig.skill_uri_allowlist` 命中前缀时可读取。
- 判定规则：`uri.startswith(prefix)`，前缀可以是 `file://`、`https://trusted.example/` 等。
- allowlist 为空时，所有 URI 加载都必须失败（`CapabilityStatus.FAILED`），并返回可诊断错误。
- 非 URI 来源（`inline/file`）不受该策略影响。

---

## 4) 假设（Assumptions）

- `sdk_config_paths` 的具体 overlay 语义由上游 SDK 决定；本仓仅负责透传与最小校验，不复制上游行为。

---

## 5) 配置加载（实现提示）

- YAML → `RuntimeConfig` 的解析入口位于 `src/agently_skills_runtime/config.py`（`load_runtime_config()` / `load_runtime_config_from_dict()`）。
- 约束：
  - 字段白名单 + fail-fast（未知字段直接报错），避免 silent misconfig；
  - 不在该层做任何上游 import（上游依赖仅在 adapters 层出现）。
