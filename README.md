# agently-skills-runtime

一句话定位：一个**生产级的能力运行时（Capability Runtime）+ 上游桥接层**，用“**Skill / Agent / Workflow 三元对等**”的方式声明、组合、执行能力，并为可观测与审计提供稳定的结构化产出（NodeReport v2）。

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

## 核心概念：三元对等（Skill / Agent / Workflow）

在本框架中，**Skill / Agent / Workflow 三者都是一等公民**：

- **Skill**：可被注入/调度的能力片段（内容来自 file/inline/uri；默认安全策略对 uri 走 allowlist）
- **Agent**：可执行的任务单元（可注入 Skills；执行细节由 Adapter 决定，常见是桥接到上游 LLM/SDK）
- **Workflow**：可组合/编排的执行图（顺序、并行、循环、条件分支；由 Adapter 递归调度）

它们都共享同一套 `CapabilitySpec` 基座（`id/kind/name/...`），统一注册到 `CapabilityRuntime`，再通过不同 `Adapter` 执行。

## 文档与示例

- 文档索引：`DOCS_INDEX.md`
- 面向使用者的文档入口：`docs/README.md`
- 工程规格入口（偏研发/验收）：`docs/spec.md`（规格索引：`docs/internal/specs/engineering-spec/SPEC_INDEX.md`）
- 示例索引：`examples/README.md`

## 测试（离线回归）

```bash
python -m pytest -q
```
