# Recipe: 02_policy_references_patch（Policy/References 驱动补丁）

本配方演示“策略/引用驱动补丁”的最小形态（skills-first）：

- Policy：以技能 bundle 的 `references/` 文件作为“受限引用”（`skill_ref_read`）
- Patch：根据 policy 的约束执行 `apply_patch`
- Evidence：NodeReportV2.tool_calls 记录 `skill_ref_read/apply_patch` 的证据

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/recipes/02_policy_references_patch/run.py --workspace-root /tmp/asr-recipe-02
```

