# 06_skill_injection（已迁移）

本目录曾用于演示 `SkillSpec.inject_to` 自动注入技能内容到 Agent 的旧口径。

## 状态

- **方案2 已移除 Skill 原语**：本仓库不再提供 `SkillSpec` / `SkillAdapter` / `inject_to`。
- skills 的发现/mention/sources/preflight/tools/approvals/WAL 全部以 **`agent_sdk`** 为真相源。

## 迁移到哪里

如需“让 Agent 使用技能”，推荐用 `agent_sdk` 的方式：

1. 在 SDK 配置（YAML overlays）里声明 Strict Catalog + sources
2. 在 task/prompt 中使用 strict mention 引用 skills
3. 用本仓 `Runtime.preflight()` / `preflight_or_raise()` 做开发机 gate

参考文档：

- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_SYSTEM.md`
- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_PREFLIGHT.md`
- `docs/internal/specs/engineering-spec/04_Operations/CONFIGURATION.md`

