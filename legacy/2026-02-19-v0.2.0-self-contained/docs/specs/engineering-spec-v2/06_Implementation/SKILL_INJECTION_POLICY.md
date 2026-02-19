# Skill 自动注入策略（inject_to）

> 目标：把 `SkillSpec.inject_to` 的行为从“字段存在但未落地”提升为**可回归**的最小能力，使 capability runtime 的“Skill ↔ Agent”互嵌关系在协议层之外也有明确执行语义。
>
> 真相源：`instructcontext/1-true-CODEX_PROMPT.md` + `instructcontext/1-true-agently-skills-runtime-spec-v1.md`

---

## 1) Goal

在 `AgentAdapter.execute()` 中落地 `SkillSpec.inject_to` 的最小语义：

- 当执行某个 `AgentSpec` 时，除了 `AgentSpec.skills` 显式声明的 skills，还应**自动注入**所有满足条件的 skills：
  - `SkillSpec.inject_to` 包含该 agent 的 `AgentSpec.base.id`

该能力必须具备离线回归测试（Unit）。

---

## 2) Constraints

- 不侵入上游：不依赖 Agently/skills-runtime-sdk 的私有 API。
- v0.2.0 交付范围优先（D-004）：仅保证“注入文本拼接 + runner 注入”的可回归骨架，不要求真实 LLM 执行闭环。
- 框架不定义人机交互（D-003）。
- 安全策略保持：`SkillSpec.source_type="uri"` 仍默认禁用，是否可用由 `RuntimeConfig.skill_uri_allowlist` 决定（D-005）。

---

## 3) Contract

### 3.1 输入

- `AgentSpec`：
  - `base.id`：当前 agent id
  - `skills`：显式声明要注入的 skill id 列表
- `CapabilityRegistry`：包含已注册的 `SkillSpec`（用于扫描 `inject_to`）

### 3.2 规则

1. **显式 skills 优先**：注入顺序以 `AgentSpec.skills` 的顺序为先。
2. **自动注入补充**：在显式 skills 之后，追加所有满足 `agent_id in SkillSpec.inject_to` 的 skill（按注册表遍历顺序即可，不强制排序）。
3. **去重**：同一个 skill id 只注入一次（显式与自动注入重叠时，保留显式位置）。
4. **缺失处理**：
   - 若 `AgentSpec.skills` 引用的 skill 未注册：返回 `FAILED`（保持 fail-fast）。
   - 自动注入来源于 registry 扫描，不存在“缺失”的可能；若发现类型不是 `SkillSpec`，应忽略或视为错误（本阶段选择 **忽略非 SkillSpec**，避免过度耦合 registry 内部实现）。

### 3.3 输出

- `skills_text: str`：按注入顺序加载后的文本以 `"\n\n"` 拼接（空白内容应被过滤）。

---

## 4) Acceptance Criteria

- AC-1：当某 `SkillSpec.inject_to=["agent-x"]` 且执行 `AgentSpec.base.id="agent-x"` 时，该 skill 内容会被注入到 `skills_text`。
- AC-2：当 `AgentSpec.skills=["s1"]` 且 `s1.inject_to` 也包含该 agent 时，注入不重复（`skills_text` 中只出现一次 `s1` 的内容）。
- AC-3：缺失显式 skill id 时，`AgentAdapter.execute()` 返回 `FAILED`（并包含可诊断错误字符串）。

---

## 5) Test Plan（离线回归）

新增/更新单测：

- `tests/adapters/test_agent_adapter.py`
  - 覆盖 AC-1/AC-2/AC-3

回归命令：

```bash
.venv/bin/python -m pytest -q
```
