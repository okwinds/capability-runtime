# Finding Catalog（finding.id 目录）

本文件用于统一 `repo-compliance-audit` 输出的 `finding.id` 命名、语义与整改边界，避免不同仓库/不同执行者产生口径漂移。

## 约定

- `finding.id`：稳定标识符（用于人类勾选与自动化脚本选择性整改）
- `severity`：`high|medium|low|info`
- `safe_to_autofix`：仅表示“低风险可自动化”，不代表“无需人工复核”

## IDs

### AGENTS_MD_MISSING

- **含义**：仓库根目录未发现 `AGENTS.md`（或等价规则文件）。
- **常见影响**：审计无法对照“仓库显式协作规则”进行指令遵循性核验；需要人工确认规则来源。
- **默认建议**：人工确认是否存在其它规则文件（如 `CONTRIBUTING.md`、`docs/process.md`），或补充 `AGENTS.md`。
- **safe_to_autofix**：false（需要人类确定规则口径）

### AGENTS_MD_DELETED

- **含义**：`AGENTS.md` 曾被 git 跟踪，但当前工作区缺失（疑似被删除/误删/篡改）。
- **常见影响**：规则来源被破坏；协作与交付约束可能失效；属于高风险事件。
- **默认建议**：立即人工核查并从 git 恢复；建议在 CI 增加规则文件存在性门禁。
- **safe_to_autofix**：false（需要人工确认与恢复策略）

### AGENTS_MD_UNTRACKED

- **含义**：`AGENTS.md` 存在但未纳入版本控制（不可追溯）。
- **常见影响**：规则可能被悄悄修改而不经过 review/CI，降低合规可信度。
- **默认建议**：人工 `git add AGENTS.md` 并走正常评审流程合入。
- **safe_to_autofix**：false（需要人工确认仓库治理策略）

### AGENTS_MD_MODIFIED

- **含义**：`AGENTS.md` 在工作区处于非干净状态（git status porcelain 非空）。
- **常见影响**：规则被改动是强信号，应被视为高风险变更，需要人工审查。
- **默认建议**：人工复核差异；若为误改/恶意改动应回滚；若为合理更新需同步更新相关 spec/test gate。
- **safe_to_autofix**：false（强制人工）

### DOCS_INDEX_MISSING

- **含义**：仓库缺少 `DOCS_INDEX.md`（或等价的关键文档索引）。
- **常见影响**：关键文档不可发现；协作无法追溯；交付不可复现。
- **默认建议**：生成最小索引骨架（不写死业务内容），后续由人类补齐。
- **safe_to_autofix**：true

### WORKLOG_MISSING

- **含义**：缺少工作记录文件（常见为 `docs/worklog.md`）。
- **常见影响**：无法取证“做了什么/为何这么做/怎么复现”。
- **默认建议**：创建最小 worklog 骨架（含日期分段与命令记录位）。
- **safe_to_autofix**：true

### ENV_EXAMPLE_MISSING

- **含义**：存在 `.env`，但缺少 `.env.example`（或 `.env.sample`）。
- **常见影响**：环境配置不可复现；同时 `.env` 可能包含密钥，存在泄露风险。
- **默认建议**：从 `.env` 提取变量名并剥离值，生成 `.env.example`（不得复制真实值）。
- **safe_to_autofix**：true

### POSSIBLE_SECRET_FOUND

- **含义**：扫描到疑似密钥/私钥/访问令牌等敏感信息（仅提示，不保证 100% 准确）。
- **常见影响**：泄露风险（高）。
- **默认建议**：人工复核 → 立即轮转/撤销 → 从历史中清理（必要时使用 git history rewrite）。
- **safe_to_autofix**：false（强制人工）

### REQUIRED_PATH_MISSING

- **含义**：检测到仓库规则文件（如 `AGENTS.md`）声明/强烈暗示“必须存在”的路径，但该路径缺失。
- **说明**：该 ID 通常带 `meta.required_path` 指明具体路径。
- **safe_to_autofix**：false（默认不自动，因为不同仓库约定差异很大）

### SPEC_ENTRYPOINT_MISSING

- **含义**：未检测到规格/设计文档的入口文件（例如 `docs/spec.md`、`SPEC_INDEX.md` 等）。
- **常见影响**：无法证明 Spec-first 落地；实现者难以仅凭文档复刻。
- **默认建议**：补齐 spec 入口（至少包含 Goal/Constraints/Contract/Acceptance Criteria/Test Plan 的索引与指针）。
- **safe_to_autofix**：false（不同仓库结构差异较大）

### SPEC_REQUIRED_SECTIONS_MISSING

- **含义**：发现 spec 入口文件，但内容未覆盖关键章节（Goal/Constraints/Contract/AC/Test Plan 的子集不足）。
- **常见影响**：spec 可读但不可执行；验收与回归难以落地。
- **默认建议**：按仓库规则补齐缺失章节与验收/测试计划。
- **safe_to_autofix**：false（需要人工撰写内容）

### TDD_EVIDENCE_MISSING

- **含义**：缺少“离线回归/TDD 已执行”的证据（例如缺少测试工程痕迹，或 worklog 中无测试命令与结果记录）。
- **常见影响**：无法证明“完成=测试通过”，容易引入回归。
- **默认建议**：补齐离线回归测试并把命令+结果记录到 worklog；CI 可选加门禁。
- **safe_to_autofix**：false（通常需要补测试与执行）

### DOC_LANGUAGE_POSSIBLE_VIOLATION

- **含义**：规则文件明确要求中文文档，但关键文档（README/Spec/Index）中文比例可能偏低（启发式）。
- **常见影响**：协作语言约束未落地（可能导致团队沟通成本上升）。
- **默认建议**：人工复核后按约定补齐中文说明或双语策略。
- **safe_to_autofix**：false

### AGENTS_EXECUTION_WORKLOG_EVIDENCE_MISSING

- **含义**：检测到“本次工作区存在变更”（尤其是代码变更），但未发现 worklog 同步更新的证据（例如 `docs/worklog.md` 不在变更集内，或缺少测试命令/结果记录信号）。
- **常见影响**：无法取证“是否按规则执行”；容易出现“看似完成但过程不可追溯”的交付。
- **默认建议**：人工补齐 worklog：记录本次工作内容、关键命令、关键输出、关键决策与理由。
- **safe_to_autofix**：false（需要人工写入内容）

### AGENTS_EXECUTION_SPEC_FIRST_EVIDENCE_MISSING

- **含义**：检测到“本次工作区存在代码变更”，但缺少 Spec-first 的过程证据（例如 spec 入口/规格文件没有同步变更）。
- **常见影响**：容易出现“先改代码后补文档”或“文档与实现脱节”，降低可复刻性与评审效率。
- **默认建议**：人工补齐/更新 spec（至少包含 Goal/Constraints/Contract/AC/Test Plan），并在 worklog 记录对应修改与理由。
- **safe_to_autofix**：false（需要人工写入内容）

### AGENTS_EXECUTION_TEST_EVIDENCE_MISSING

- **含义**：检测到“本次工作区存在代码变更”，但缺少 TDD/离线回归已执行的过程证据（worklog 中无测试命令与结果信号）。
- **常见影响**：无法证明“完成=测试通过”，回归风险上升。
- **默认建议**：运行离线回归测试并把命令与结果写入 worklog；必要时在 CI 加门禁。
- **safe_to_autofix**：false（需要人工执行并记录）
