<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# Legacy Archive：2026-02-12 repo-compliance-audit deprecation

本目录归档了与当前“fork-bridge 主线”无关的历史资产，保留追溯但不再参与主线开发：

- `skills/repo-compliance-audit/`（技能与脚本）
- `tests/test_repo_compliance_audit_skill.py`（对应测试）
- `docs/specs/engineering-spec/04_Operations/REPO_COMPLIANCE_AUDIT.md`（对应规格）
- `docs/task-summaries/2026-02-06-repo-compliance-audit-skill.md`（对应任务总结）
- 旧构建产物（`build/`、`capability_runtime.egg-info/`）

归档原因：路线已切换为“`agently` fork + `skills-runtime-sdk` fork + 本仓只做桥接层”，需清理主线噪音。
