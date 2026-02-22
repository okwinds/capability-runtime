# archive/legacy/（历史实验线/阶段性产物）

本目录用于存放**不再作为主线验收对象**的历史产物（实验线、阶段性重构快照、清理残留等），以便追溯与审计。

> 注意：主线交付以 `src/` + `tests/` + `docs/internal/specs/engineering-spec/` 为准；本目录内容仅用于“为什么这样演进”的追溯。

## 目录说明（按时间）

- `2026-02-12-repo-compliance-audit-deprecated/`
  - 早期与“repo 合规审计/整改”相关的历史资产归档（已不作为主线依赖）。
- `2026-02-13-repo-structure-cleanup/`
  - 仓库结构清理过程中产生的过渡产物归档（例如不再使用的辅助 shim/临时文件等）。
- `2026-02-18-bridge-only-mainline/`
  - “桥接层主线”在某一阶段的快照/追溯材料（用于对比后续演进）。
- `2026-02-19-v0.2.0-self-contained/`
  - v0.2.0 自研 Capability Runtime 实验线（自研执行内核）；已按战略回归归档，仅保留追溯价值。

