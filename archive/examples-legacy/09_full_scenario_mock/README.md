# 示例 09：完整场景（离线 mock）

本示例展示一个完整的“内容创作工作流”，对应典型组合模式：
- Pipeline（顺序编排）
- Fan-out（LoopStep 对多个角度扩写）

## 场景流程

`workflow.content_creation` 包含 4 个 Agent：

1. `agent.topic_analyst`
- 输入：`raw_idea`
- 输出：`topic` + `angles[]`

2. `agent.angle_writer`（循环执行）
- 输入：`topic` + `angle`
- 输出：`section`

3. `agent.editor`
- 输入：`topic` + `sections[]`
- 输出：`final_draft` + `word_count`

4. `agent.quality_checker`
- 输入：`final_draft`
- 输出：`quality_score` + `issues[]`

最终通过 `output_mappings` 聚合为统一结果。

## 运行方式

```bash
python examples/09_full_scenario_mock/run.py
```

## 期望输出

终端会打印：
- `workflow.status=success`
- 完整 JSON 输出（包含 topic / angles / sections / final_draft / word_count / quality_score / issues）

## 说明

- 该示例完全离线，不依赖网络、LLM、API key。
- 适合用来回归验证编排逻辑和映射表达式（`context.*` / `step.*` / `item.*`）。
