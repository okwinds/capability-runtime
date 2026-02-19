# 编码智能体指令包 — 使用指南

> **本文档面向你（项目负责人）**，不是面向编码智能体。
> 它解释这套指令包的结构、使用方法、和注意事项。

---

## 一、指令包包含什么

```
CODEX_CONTEXT_BRIEF.md        ← 全局上下文（编码智能体必读）
CODEX_BATCH1_INSTRUCTION.md   ← 批次 1：cheatsheet + examples 01-05（基础）
CODEX_BATCH2_INSTRUCTION.md   ← 批次 2：心智模型 + API 清单 + examples 06-08（进阶）
CODEX_BATCH3_INSTRUCTION.md   ← 批次 3：模式手册 + Bridge 接线 + examples 09-10（真实 LLM）
CODEX_BATCH4_INSTRUCTION.md   ← 批次 4：业务域指南 + example 11（脚手架）
本文件（USAGE_GUIDE.md）       ← 你正在读的使用指南
```

---

## 二、怎么用

### 方式 A：在 Claude Code / Codex CLI 中使用

1. 把 `CODEX_CONTEXT_BRIEF.md` 放入仓库的 `instructcontext/` 目录
2. 在 `AGENTS.md` 或 `SKILLS.md` 中添加引用：
   ```
   执行任务前，先读 instructcontext/CODEX_CONTEXT_BRIEF.md
   ```
3. 逐批次发送指令：
   - 发送 BATCH 1 → 验证产出 → 发送 BATCH 2 → 验证产出 → ...

### 方式 B：在 Claude.ai 对话中使用

1. 在对话开头附上 `CODEX_CONTEXT_BRIEF.md` 的全文
2. 然后发送某一个 BATCH 指令
3. 逐批次执行

### 方式 C：作为 Project Knowledge

1. 把 `CODEX_CONTEXT_BRIEF.md` 添加为 Claude Project 的 Knowledge
2. 在对话中发送 BATCH 指令

---

## 三、执行节奏建议

```
第 1 天：BATCH 1（cheatsheet + examples 01-05）
         ↓ 验证：5 个 run.py 全部可运行
第 2 天：BATCH 2（mental-model + inventory + examples 06-08）
         ↓ 验证：3 个 run.py 可运行 + 文档质量审查
第 3 天：BATCH 3（patterns + bridge-wiring + examples 09-10）
         ↓ 验证：example 09 可运行 + example 10 真实 LLM 测试
第 4 天：BATCH 4（agent-domain-guide + example 11）
         ↓ 验证：脚手架 mock 可运行 + 文档质量审查
```

**注意**：不要跳过验证步骤。每个 BATCH 的产出是下一个 BATCH 的输入。

---

## 四、验证方法

### 代码验证

```bash
# 每个 example 独立运行
python examples/01_declare_and_run/run.py
python examples/02_workflow_sequential/run.py
# ... 依此类推

# 既有测试不受影响
python -m pytest tests/ -v
```

### 文档验证

- cheatsheet.md 中的代码片段是否可复制粘贴运行？
- import 路径是否正确（对照 src/ 中的真实模块路径）？
- API 签名是否与源码一致（特别是 CapabilityRuntime.run 的参数）？

### 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| import 失败 | 未安装框架 | `pip install -e ".[dev]"` |
| 测试失败 | 编码智能体修改了框架代码 | 检查 src/ 是否被改动，回滚 |
| run.py 报错 | mock adapter 返回的数据结构与 InputMapping 不匹配 | 检查 mock 输出的 key 是否与 step 引用一致 |
| 真实 LLM 超时 | endpoint 不可达 | 检查 .env 配置 |

---

## 五、产出后的仓库结构

全部 4 个 BATCH 交付后，仓库新增部分：

```
agently-skills-runtime/
├── docs_for_coding_agent/         ← 新增
│   ├── README.md
│   ├── cheatsheet.md
│   ├── 00-mental-model.md
│   ├── 01-capability-inventory.md
│   ├── 02-patterns.md
│   ├── 03-bridge-wiring.md
│   ├── 04-agent-domain-guide.md
│   └── contract.md
│
├── examples/                      ← 新增
│   ├── README.md
│   ├── 01_declare_and_run/
│   ├── 02_workflow_sequential/
│   ├── 03_workflow_loop/
│   ├── 04_workflow_parallel/
│   ├── 05_workflow_conditional/
│   ├── 06_skill_injection/
│   ├── 07_skill_dispatch/
│   ├── 08_nested_workflow/
│   ├── 09_full_scenario_mock/
│   ├── 10_bridge_wiring/
│   └── 11_agent_domain_starter/
│
├── src/agently_skills_runtime/    ← 不动
├── tests/                         ← 不动
└── ...
```

---

## 六、后续可选扩展

完成 4 个 BATCH 后，你可以按需扩展：

| 扩展 | 说明 | 优先级 |
|------|------|--------|
| 仓库结构清理 | 将 instructcontext/、legacy/ 归档到 archive/ | 高（BATCH 1 前或后均可） |
| smoke tests | 为 examples/ 添加 pytest smoke tests（参考 Agently 的 test_examples_smoke.py） | 中 |
| 真实业务域 | 将 example 11 复制为 agent_domain/，填入真实 Prompt | 高（Phase 4B） |
| 中文版 cheatsheet | 提供 cheatsheet.zh-CN.md | 低 |
| DOCS_INDEX 更新 | 将新增的文档添加到 DOCS_INDEX.md | 中 |

---

## 七、给编码智能体的提示技巧

1. **始终附上 CONTEXT_BRIEF**：这是编码智能体理解框架的"地面真相"。
   没有它，编码智能体会"自由发挥"，产出质量不可控。

2. **种子代码是关键**：CONTEXT_BRIEF 中的 3 段种子代码（Section 7）是
   编码智能体生成新代码的模仿对象。如果产出质量不满意，
   检查编码智能体是否正确参考了种子代码。

3. **逐批次执行比一次性好**：编码智能体在单次任务中保持的上下文窗口有限。
   分 4 个批次发送指令，每次验证后再发下一批，
   比一次性发全部指令效果好得多。

4. **验证是必须的**：编码智能体可能生成看起来正确但实际不能运行的代码。
   每个 run.py 必须手动或自动验证。

5. **允许编码智能体"降级"**：BATCH 3 的 Bridge 接线可能因为环境限制无法完成。
   指令中已经设计了降级方案（run_mock_fallback.py）。不要强求。
