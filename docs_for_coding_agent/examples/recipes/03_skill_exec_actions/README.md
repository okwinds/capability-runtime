# Recipe: 03_skill_exec_actions（Skills Actions / skill_exec）

本配方示例演示 **Skills Actions（Phase 3）** 的最小可回归闭环：

- overlay：`skills.actions.enabled=true`（默认 fail-closed）
- skill bundle：在 `SKILL.md` frontmatter 里声明 `actions.<action_id>.argv`
- agent：通过 builtin tool `skill_exec` 执行 action（带 approvals 与 tool evidence）

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/recipes/03_skill_exec_actions/run.py --workspace-root /tmp/caprt-recipe-03
```

