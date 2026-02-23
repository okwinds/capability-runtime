# 07_skill_dispatch（已迁移）

本目录曾用于演示 `SkillSpec.dispatch_rules`（技能内部触发调度）的旧口径。

## 状态

- **方案2 已移除 Skill 原语**：本仓库不再提供 `SkillSpec` / `SkillAdapter` / `dispatch_rules`。
- 为避免形成第二套编排/调度系统，本仓库只保留 **Agent/Workflow 原语**，并用 NodeReport/WAL 做证据链。

## 推荐替代方式

- 需要分支/并发/循环/路由：用 `WorkflowSpec`（本仓）表达
- 顶层工作流编排：用 Agently TriggerFlow 表达
- skills 的治理与执行：依赖 `agent_sdk`（Strict Catalog + preflight + approvals + WAL）

参考文档：

- `docs/internal/specs/engineering-spec/02_Technical_Design/MULTI_AGENT_ORCHESTRATION.md`
- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_SYSTEM.md`

