# Repo Compliance Audit Skill（仓库合规审计技能）

## Goal（目标）

提供一个**通用、全局、可复用**的“代码仓库合规审计 + 选择性合规重构”技能（Skill），用于：

1. **第一阶段（Audit）**：在**不修改仓库内容**的前提下，对仓库进行合规性检查并形成**可取证**的审计报告（包含人类可读 + 机器可读两种输出）。
2. **第二阶段（Remediation，可选）**：仅在**人类明确选择**要修复的条目后，对仓库执行**选择性合规重构**（默认不改业务逻辑，只补齐合规缺口）。

该技能面向的“合规”包含但不限于：
- 指令遵循性（如 AGENTS.md、用户明确约束、仓库约束文件）
- 文档/规格/索引制度落地（Spec-first、索引、worklog、task summary）
- TDD 与可复现证据（离线回归命令与结果、最小可运行步骤）
- 秘钥/敏感信息与仓库卫生（.env.example、密钥扫描、二进制/大文件）

> 重要澄清：本 skill 所谓“指令遵循性审查”，指的是对**仓库可观察证据**的核验（文件存在性、内容片段、worklog 命令记录、测试运行结果摘要等）。它不会假定“某次对话/某个代理执行过程”必然可追溯到仓库里；若执行过程没有被写入 worklog/提交记录，则应被审计为“缺少证据”而不是“已遵循/未遵循”的断言。

## Non-goals（非目标）

- 不尝试“理解业务正确性”或“重写业务逻辑”。
- 不强行统一所有仓库的目录结构；整改阶段仅在选中条目且可安全自动化时执行最小变更。
- 不依赖外网；默认不要求安装额外依赖（仅用 Python 标准库）。

## Constraints（约束）

- **生态/通用性**：不写死某个具体项目的目录结构；允许按仓库内的规则文件（如 `AGENTS.md`）动态启用/禁用控制项。
- **可取证**：所有结论必须给出证据（文件路径、命令输出摘要、规则来源）。
- **安全默认**：
  - Audit 阶段默认只写入 `/tmp`（或用户指定输出目录），避免污染仓库工作区。
  - Remediation 阶段仅对人类选中的条目进行修复；并且默认只允许“safe-to-autofix”类型修复。

## Contract（契约 / 输出协议）

### 1) Audit 输出（必须）

Audit 运行后产出同一批次的两个文件：

1. `report.md`：人类可读审计报告（结论摘要、风险分级、证据、可选修复清单）
2. `findings.json`：机器可读发现列表（用于人类勾选后进入整改阶段）

可选开关（建议在“对外共享报告”时启用）：
- `--redact report`：仅脱敏 `report.md`（保留 `findings.json` 供系统编排/整改使用）
- `--redact all`：脱敏 `report.md` + `findings.json`（对外共享）
- `--no-git-meta`：不收集 git 元信息（减少泄露与噪声）
- `--no-secret-scan`：禁用疑似密钥扫描（减少误报/性能开销/报告风险）

`findings.json` 顶层结构：

```json
{
  "meta": {
    "tool": "repo-compliance-audit",
    "version": "0.1",
    "generated_at": "2026-02-06T12:34:56Z",
    "repo_root": "/abs/path",
    "git": {
      "is_git_repo": true,
      "head": "abc123",
      "dirty": true
    }
  },
  "summary": {
    "counts_by_severity": { "high": 1, "medium": 2, "low": 3, "info": 4 },
    "counts_by_category": { "docs": 3, "testing": 2 }
  },
  "findings": [
    {
      "id": "DOCS_INDEX_MISSING",
      "title": "缺少文档索引 DOCS_INDEX.md",
      "severity": "high",
      "category": "docs",
      "summary": "仓库缺少关键文档索引，难以协作追溯与复现。",
      "rule_sources": ["AGENTS.md#3 文档索引（必须维护）"],
      "evidence": [
        { "type": "path_exists", "path": "DOCS_INDEX.md", "ok": false }
      ],
      "proposed_fix": {
        "kind": "create_file",
        "path": "DOCS_INDEX.md",
        "notes": "生成最小可用索引骨架，后续由人类补齐。"
      },
      "safe_to_autofix": true,
      "tags": ["index", "spec-driven"]
    }
  ]
}
```

字段约定：
- `severity`：`high|medium|low|info`
- `category`：例如 `instruction|docs|spec|testing|repro|security|hygiene|ci`
- `rule_sources`：说明该检查来自哪些规则/指令（能定位到文件/章节更好）
- `safe_to_autofix`：是否允许在整改阶段自动执行

### 2) Remediation 输入（必须）

整改阶段由人类提供被选中的 `finding.id` 列表（或文件），技能仅对该子集执行修复：

- `--select DOCS_INDEX_MISSING,WORKLOG_MISSING`
- 或 `--select-file selected.txt`（每行一个 id）

整改执行完成后：
- 输出 `remediation_report.md`（记录执行了哪些 fix、改动了哪些文件、是否需要人工复核）

## Acceptance Criteria（验收标准）

### Audit 阶段

- 能在任意目录执行并指定 `--repo`，输出目录可指定 `--out`；默认输出到 `/tmp`（或等价临时目录）。
- 产出 `report.md` 与 `findings.json`，并且：
  - `findings.json` 满足上述结构约束；
  - 每条 finding 都包含 `id/severity/category/summary/evidence/safe_to_autofix`；
  - 结论可追溯：报告中能看到关键证据与规则来源。
- 在**不含 git**的目录仍可运行（以 `--repo` 为根）。
- 当仓库存在 `AGENTS.md` 时，Audit 至少应输出以下“指令遵循性相关”检查之一（以证据为准）：
  - `AGENTS_MD_MISSING`（若缺失）
  - `SPEC_ENTRYPOINT_MISSING` / `SPEC_REQUIRED_SECTIONS_MISSING`（Spec-first 证据）
  - `TDD_EVIDENCE_MISSING`（测试/TDD 证据）
  - `DOC_LANGUAGE_POSSIBLE_VIOLATION`（语言约束启发式提示）
  - 以及对规则文件完整性的取证提示：`AGENTS_MD_DELETED` / `AGENTS_MD_MODIFIED` / `AGENTS_MD_UNTRACKED`
  - 以及对“执行过程证据”的即时提示（当 git 工作区存在变更时才会产出）：
    - `AGENTS_EXECUTION_SPEC_FIRST_EVIDENCE_MISSING`
    - `AGENTS_EXECUTION_TEST_EVIDENCE_MISSING`
    - `AGENTS_EXECUTION_WORKLOG_EVIDENCE_MISSING`

### Remediation 阶段

- 必须支持“人类选择后再执行”的交互方式（ID 列表输入）。
- 默认只执行 `safe_to_autofix=true` 的修复；对其它条目给出明确提示并拒绝自动执行（除非显式 override）。
- 默认不改业务逻辑：只允许创建/补齐合规文件、补齐索引/模板、生成 `.env.example`（剥离值）等低风险操作。

### CI Gate（推荐）

目标：把 AGENTS.md 的“过程约束”变成可执行门禁，避免 agent/人类在执行过程中漏写 worklog、漏跑回归、或规则文件被篡改/删除。

推荐策略：

1. **最小门禁（推荐默认）**：执行 audit 并启用 `--fail-on high`
   - 主要拦截：`AGENTS_MD_DELETED` / `AGENTS_MD_MODIFIED` / `AGENTS_EXECUTION_TEST_EVIDENCE_MISSING` / `POSSIBLE_SECRET_FOUND`
2. **严格门禁（按需启用）**：执行 audit 并启用 `--fail-on medium`
   - 额外拦截：Spec-first 证据缺失、worklog 过程证据缺失等 medium findings

示例命令：

```bash
python3 skills/repo-compliance-audit/scripts/audit_repo.py --repo . --out /tmp/repo-compliance-audit --fail-on high
```

注意：
- “执行过程证据”类 findings 仅在 git 工作区存在变更时触发（用于提醒尚未整理/未提交前的过程缺口）；若你在 CI 的触发时机是“合并前检查”，建议同时要求提交信息/PR 模板承载 worklog/test evidence 的链接或摘要。

## Test Plan（测试计划）

离线回归（必须）：

1. **Unit**：构造临时仓库目录，分别覆盖：
   - 缺少 `DOCS_INDEX.md` 的发现生成；
   - 存在 `.env` 但缺少 `.env.example` 的发现生成；
   - `findings.json` schema 字段完整性断言。
2. **Unit**：对 `safe_to_autofix` 的修复器做最小集验证：
   - 选中 `ENV_EXAMPLE_MISSING` 时生成 `.env.example` 且不包含原值；
   - 选中 `DOCS_INDEX_MISSING` 时生成最小索引骨架。
3. **Unit**：对 AGENTS 指令遵循性审查（启发式）做最小覆盖：
   - 当存在 `AGENTS.md` 但缺少 spec 入口时，产出 `SPEC_ENTRYPOINT_MISSING`；
   - 当存在 `AGENTS.md` 且缺少测试证据时，产出 `TDD_EVIDENCE_MISSING`。
4. **Unit**：对“执行过程证据”的即时审查做最小覆盖（依赖 git）：
   - 当工作区存在代码变更且 worklog 缺少测试命令+结果信号时，产出 `AGENTS_EXECUTION_TEST_EVIDENCE_MISSING`。

命令（示例）：

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```
