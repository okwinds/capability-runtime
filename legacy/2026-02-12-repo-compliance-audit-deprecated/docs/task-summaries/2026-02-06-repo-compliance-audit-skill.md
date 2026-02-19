# Task Summary：repo-compliance-audit（仓库合规审计技能）

## 1) Goal / Scope

- Goal：新增一个**通用/全局**的“仓库合规审计 + 人类选择后整改”技能，满足“先审计取证、再选择性修复”的工作流。
- In Scope：
  - Audit：生成 `report.md`（人类可读）+ `findings.json`（机器可读）。
  - Remediation：按人类勾选的 `finding.id` 执行选择性低风险整改（默认不改业务逻辑）。
- 离线回归测试：覆盖 audit→remediate 的最小闭环。
  - 并覆盖 AGENTS 指令遵循性审查的最小 finding 生成（Spec-first/TDD 证据）。
- Out of Scope：
  - 不做业务逻辑正确性审计。
  - 不提供“所有 finding 的自动修复器”（仅提供低风险/通用项；其余给出可取证建议）。
- Constraints：
  - 无外网依赖；脚本仅用 Python 标准库。
  - Audit 阶段默认不修改仓库内容（输出写到 `--out` 目录）。

## 2) Context（背景与触发）

- 背景：需要一个可复用的“合规审查”能力，第一步必须能验证是否遵循仓库规则（如 `AGENTS.md`）并形成可取证报告；第二步必须由人类选择条目后才执行整改。

## 3) Spec / Contract（文档契约）

- Contract：
  - Audit 输出：`report.md` + `findings.json`（含 `finding.id/severity/category/evidence/safe_to_autofix`）。
  - Remediation 输入：人类提供选中的 `finding.id` 列表（逗号或文件）。
- Acceptance Criteria：`docs/specs/engineering-spec/04_Operations/REPO_COMPLIANCE_AUDIT.md`。
- Test Plan：单测构造临时仓库，断言 findings 生成与低风险修复器行为正确。
- 风险与降级：
  - secrets 扫描存在误报/漏报风险 → 仅提示高风险并强制人工复核，默认不自动处理。

## 4) Implementation（实现说明）

### 4.1 Key Decisions（关键决策与 trade-offs）

- Decision：对人类输出不强制 JSON，对系统交互使用 `findings.json`（控制面强结构）。
  - Why：兼顾生态兼容（大量仓库/团队习惯 Markdown 报告）与系统可编排（finding.id 可做门禁/自动化）。
  - Trade-off：需要同时维护两种输出的一致性（通过同一 finding 数据源生成）。

### 4.2 Code Changes（按文件列）

- `skills/repo-compliance-audit/SKILL.md`：技能说明（Audit→人类勾选→Remediation）。
- `skills/repo-compliance-audit/scripts/audit_repo.py`：审计脚本（输出报告 + findings）。
- `skills/repo-compliance-audit/scripts/remediate_repo.py`：整改脚本（按选择项执行最小修复器）。
- `skills/repo-compliance-audit/scripts/audit_repo.py`：补齐 AGENTS 指令遵循性审查（Spec-first/TDD/语言启发式）。
- `skills/repo-compliance-audit/references/finding-catalog.md`：finding.id 目录与口径说明。
- `docs/specs/engineering-spec/04_Operations/REPO_COMPLIANCE_AUDIT.md`：工程规格补充（契约/AC/Test Plan）。
- `tests/test_repo_compliance_audit_skill.py`：离线回归（audit→remediate 闭环）。

## 5) Verification（验证与测试结果）

### Unit / Offline Regression（必须）

- 命令：`/usr/bin/python3 -m unittest discover -s tests -v`
- 结果：`OK`（14 tests）

## 6) Results（交付结果）

- 交付物列表：
  - `skills/repo-compliance-audit/`（skill + scripts + references）
  - `docs/specs/engineering-spec/04_Operations/REPO_COMPLIANCE_AUDIT.md`
- 如何使用（示例）：
  - Audit：`python3 skills/repo-compliance-audit/scripts/audit_repo.py --repo . --out /tmp/repo-compliance-audit`
  - Remediation：`python3 skills/repo-compliance-audit/scripts/remediate_repo.py --repo . --findings /tmp/repo-compliance-audit/findings.json --select DOCS_INDEX_MISSING`

## 7) Known Issues / Follow-ups

- 已知问题：
  - `AGENTS.md` 的“强约束路径”提取采用启发式，可能存在误判 → 建议后续引入可选的 `.repo-compliance.json` profile（仍保持默认通用）。
- 后续建议：
  - 根据团队实际治理要求补充更多 finding 与修复器，但保持“默认不改业务逻辑”的边界。

## 8) Doc Index Update

- 已在 `DOCS_INDEX.md` 登记：是
