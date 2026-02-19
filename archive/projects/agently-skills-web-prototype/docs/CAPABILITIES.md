# 能力清单（Capability Inventory）

> 本清单用于把“全量覆盖”落成可执行的验证项，而不是口号。

---

## 1) Skills Runtime SDK（引擎侧）

- tools 闭环：LLM `tool_calls` → ToolRegistry 执行 → tool output 回注
  - 验证：`demo` 模式 scripted stream 触发 `triggerflow_run_flow`
- approvals gate（fail-closed）
  - 验证：Web UI 的 Pending Approvals + approve/deny
- WAL/事件证据链（events_path）
  - 验证：Run Snapshot 中展示 `events_path`（若 SDK 在 workspace_root 产出）
- preflight gate（零 I/O）
  - 验证：后续可在 UI 增加“一键 preflight”按钮（本期已准备后端配置与 overlays）

## 2) Agently（编排/请求侧）

- OpenAICompatible requester + streaming 适配
  - 验证：`real` 模式（需安装 agently 并具备真实 requester 配置）
- TriggerFlow 编排
  - 验证：原型内置 `InProcessFlowRunner` 作为 runner 注入示例；真实 TriggerFlow runner 可在宿主侧替换注入

## 3) Bridge（本仓）

- `AgentlyChatBackend`：流式解析（text/tool_calls/done）
  - 验证：demo 复用 `AgentlyChatBackend` 的 parsing，触发 tool_calls 的 flush 逻辑
- TriggerFlow tool（`triggerflow_run_flow`）+ approvals 证据链
  - 验证：demo run 触发该 tool，并通过 approvals API 决策
- NodeReport（控制面强结构）
  - 验证：Run Snapshot 返回 `node_report`（用于编排分支）

