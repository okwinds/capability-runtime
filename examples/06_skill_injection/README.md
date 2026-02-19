# 06_skill_injection（Skill 注入到 Agent：inject_to）

**演示**：通过 `SkillSpec.inject_to` 声明“自动注入”，让某个 Agent 在执行时自动携带指定 Skill 的内容。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/06_skill_injection/run.py
```

预期输出要点：
- `status=success`
- `task_preview`：runner 看到的 task 前 200 字符
- `contains_injected_skill=true`：证明注入内容已进入 task

## 学到什么

- `SkillSpec.inject_to: List[str]` 的**地面真相**：它是 **Agent ID 列表**（不是正则、不是表达式）。
- 注入发生在 `AgentAdapter.execute()`：它会合并两类技能来源：
  - `AgentSpec.skills`（显式装载）
  - `CapabilityRegistry.find_skills_injecting_to(agent_id)`（匹配 `inject_to`）
- 注入的 Skill 内容会被拼接进 Agent 的 `task` 文本（详见 `AgentAdapter._build_task()`）。

## 代码要点（run.py 已实现）

1) 注册 1 个 Agent + 1~2 个 Skill：
- `AgentSpec.base.id == "agent_demo"`（示例 ID 可变，但必须稳定）
- 至少 1 个 `SkillSpec.inject_to` 包含该 Agent ID

2) 使用 `AgentAdapter(runner=...)` 运行，且 runner 必须是**离线可运行的 mock**：
- runner 的签名需兼容：`async def runner(task: str, *, initial_history=None) -> Any`
- runner 可以直接把收到的 `task` 原样返回（便于断言“注入内容出现了”）

3) 断言注入生效：
- `AgentSpec.skills` 为空也要能注入（仅靠 `inject_to`）
- 若同时显式装载与注入同一 Skill ID，需要去重（以最终拼接一次为准）

4) 输出口径（便于人工验证）：
- 打印 `CapabilityResult.status`
- 打印 runner 返回的摘要字段（`task_preview` / `contains_injected_skill`）
