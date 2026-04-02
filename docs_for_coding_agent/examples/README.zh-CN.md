# docs_for_coding_agent/examples（可回归示例库）

本目录用于**让编码智能体通过小样本学习**，掌握如何在本仓中：
- skills-first（system prompt 变薄）
- evidence-first（WAL + NodeReport + tool/approvals 证据）
- 离线可回归（pytest 作为门禁）

## 目录结构

- `atomic/`：原子示例（每例只教学 1 个能力点）
- `recipes/`：组合配方（面向真实交付形态的“能力组合”）

## 建议阅读顺序（Atomic）

1. `atomic/00_runtime_minimal/`：Runtime 最小闭环（register/validate/run）
2. `atomic/01_sdk_native_minimal/`：run_stream 的事件流协议
3. `atomic/02_read_node_report/`：如何读 NodeReport 的稳定证据
4. `atomic/03_preflight_gate/`：preflight gate（off/warn/error）
5. `atomic/04_custom_tool/`：custom_tools 注入
6. `atomic/05_exec_sessions_stub/`：exec sessions stub（exec_command/write_stdin）
7. `atomic/06_collab_stub/`：collab stub（spawn_agent/wait/close_agent）
8. `atomic/07_web_search_offline/`：web_search 默认 fail-closed
9. `atomic/08_view_image_offline/`：view_image 离线读取图片
10. `atomic/09_multiseg_namespace_mention/`：多段 namespace + strict mention（可观察 skill_injected）

## Recipes（组合配方）

- `recipes/00_review_fix_qa_report/`：Review→Fix→QA→Report（最小工程闭环）
- `recipes/01_map_reduce_parallel/`：Map-Reduce 并行子任务汇总（stub）
- `recipes/02_policy_references_patch/`：Policy/References 驱动补丁（skill_ref_read + apply_patch）
- `recipes/03_skill_exec_actions/`：Skills Actions（skill_exec：frontmatter.actions → approvals → tool evidence）
- `recipes/04_invoke_capability_child_agent/`：渐进式披露：skills 驱动委托子 Agent（invoke_capability）
- `recipes/05_invoke_capability_child_workflow/`：Agent → 子 Workflow（invoke_capability）

## 离线回归（门禁）

```bash
pytest -q tests/test_coding_agent_examples_atomic.py
pytest -q tests/test_coding_agent_examples_recipes.py
```
