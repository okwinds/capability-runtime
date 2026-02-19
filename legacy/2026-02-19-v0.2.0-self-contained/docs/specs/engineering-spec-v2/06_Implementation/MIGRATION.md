# 迁移与归档（Migration, v2）

> 目标：以“可追溯但不干扰主线”为原则完成破坏式升级迁移。
>
> 约束：不侵入上游；保留 `projects/agently-skills-web-prototype/` 不动。

---

## 1) 破坏式升级声明（v0.2.0）

- v0.2.0 将主线从 bridge-only 转为 capability-oriented runtime。
- 对外 API、包内结构与核心类型体系发生变化，旧入口不保证兼容。

---

## 2) legacy 归档策略（必须）

归档原则：

1. 旧主入口与旧类型体系不再被新主线 import/use
2. 旧资产必须可追溯（保留原始文件与说明，不“悄悄消失”）
3. 归档后索引可检索（`DOCS_INDEX.md` 必须更新）

归档范围（按 `instructcontext/1-true-CODEX_PROMPT.md` 的处置决策）：

- 旧实现入口：
  - `src/agently_skills_runtime/runtime.py`
  - `src/agently_skills_runtime/types.py`
  - 以及任何与旧 bridge-only 主线绑定的模块（实现阶段逐项确认）

归档位置建议：

- `legacy/2026-02-18-capability-runtime-refactor/`
  - `src/`：旧代码镜像
  - `docs/`：旧规格/说明镜像（如存在冲突 PRD/Spec，可一起映射）
  - `README.md`：归档说明（为什么归档、如何回溯）

---

## 3) 迁移路径（旧入口 → 新入口）

旧：
- “单次 run 包装器”式入口（bridge-only 思路）

新：
- `CapabilityRuntime`（注册 + 校验 + 执行）
- `protocol/*` 声明能力
- `runtime/*` 负责组合与执行控制
- `adapters/*` 负责上游桥接

---

## 4) 索引与过程记录要求（必须）

实现阶段完成迁移后，必须同步：

- `DOCS_INDEX.md`：登记 v2 PRD/Spec、legacy 归档路径、任务总结
- `docs/worklog.md`：记录迁移命令与验证结果
- `docs/task-summaries/<date>-capability-runtime-refactor.md`：记录决策、代码变更、测试结果
- `docs/backlog.md`：记录未尽事宜（含时间戳）

---

## 5) 假设（Assumptions）

- 归档的旧实现不再作为新主线依赖；若业务方仍需旧 API，必须通过显式引用 legacy 路径实现临时过渡，并在后续版本清理。
