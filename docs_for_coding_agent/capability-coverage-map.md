# 能力覆盖矩阵（Coverage Map）

> 面向：编码智能体 / 维护者  
> 目的：把“能力点”与“契约入口 + 示例 + 测试 + 证据断言”连起来，作为“无死角覆盖”的验收基线。  
> 约束：默认 **离线可回归**；真模型/联网仅作为可选集成验证。  

## 0) 读者如何使用本表

1. 先选一个能力点（CAP-*）。
2. 通过表中链接找到：
   - 契约入口（openspec/specs + src 入口）
   - 可运行示例（examples/ 或 docs_for_coding_agent/examples/）
   - 离线回归门禁（pytest）
   - evidence 断言点（WAL locator + NodeReport/tool evidence）
3. 跑最小离线命令，确认示例与证据链可复现。

## 1) 能力点（CAP-*）→ 证据入口映射

> 说明：本仓对外只承诺 `Agent/Workflow` 原语；skills/tool/approvals/WAL/events 等能力由上游 `skills_runtime` 提供并通过本仓桥接可用。

| CAP | 能力点 | 契约入口 | Code 入口 | 示例入口 | 离线测试入口 | evidence 断言点 |
|---|---|---|---|---|---|---|
| CAP-CR-001 | Protocol：仅 Agent/Workflow | `openspec/specs/capability-runtime/spec.md` | `src/agently_skills_runtime/protocol/` | `examples/02_workflow/` | `pytest -q`（本仓） | `CapabilityResult.status` 与 `context.step_outputs` |
| CAP-CR-002 | Runtime：register/validate/run | `openspec/specs/capability-runtime/spec.md` | `src/agently_skills_runtime/runtime.py` | `docs_for_coding_agent/examples/atomic/00_runtime_minimal/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k runtime_minimal` | `NodeReport.events_path` + `hello.txt` |
| CAP-CR-003 | Workflow：顺序/循环/条件/并行 | `openspec/specs/capability-runtime/spec.md` | `src/agently_skills_runtime/adapters/workflow_adapter.py` | `examples/02_workflow/` | `pytest -q`（本仓） | `context.step_results[*].status` |
| CAP-BRIDGE-001 | bridge：事件转发 + 终态收敛 | `openspec/specs/upstream-bridge/spec.md` | `src/agently_skills_runtime/adapters/agent_adapter.py` | `examples/03_bridge_e2e/` | `pytest -q`（本仓，offline stub） | `run_stream()` 先 yield `AgentEvent` 再 yield `CapabilityResult` |
| CAP-BRIDGE-002 | sdk_native：不依赖 Agently 的 OpenAI backend | `openspec/specs/upstream-bridge/spec.md` | `src/agently_skills_runtime/runtime.py` | `docs_for_coding_agent/examples/atomic/01_sdk_native_minimal/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k sdk_native_minimal` | `NodeReport.engine.module == "skills_runtime"` |
| CAP-BRIDGE-003 | 离线注入：Fake backend 仍产出证据链 | `openspec/specs/examples-human-apps/spec.md` | `src/agently_skills_runtime/config.py` + `src/agently_skills_runtime/runtime.py` | `examples/apps/* --mode offline`（本变更创建） | `pytest -q tests/test_examples_smoke.py`（本变更创建） | `NodeReport.events_path != None` 且可读 |
| CAP-EVID-001 | NodeReport：状态/原因/证据链 | `openspec/specs/evidence-chain/spec.md` | `src/agently_skills_runtime/reporting/node_report.py` | `docs_for_coding_agent/examples/atomic/02_read_node_report/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k read_node_report` | `report.tool_calls[*].ok/error_kind/approval_decision` |
| CAP-SKILLS-001 | skills-first：mention 注入（Scheme2） | `openspec/specs/upstream-bridge/spec.md` | `src/agently_skills_runtime/adapters/agent_adapter.py` | `docs_for_coding_agent/examples/atomic/09_multiseg_namespace_mention/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k multiseg_namespace_mention` | WAL 中 `skill_injected.mention_text`（含多段 namespace）+ `report.activated_skills` |
| CAP-SKILLS-002 | preflight gate：warn/error/off | `openspec/specs/capability-runtime/spec.md` | `src/agently_skills_runtime/adapters/agent_adapter.py` | `docs_for_coding_agent/examples/atomic/03_preflight_gate/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k preflight_gate` | error：`events_path=None`；warn：`meta.preflight_issues` |
| CAP-TOOLS-001 | 内置工具：标准库（read/grep/list/write/patch/shell） | 上游 tools 契约（由 `skills_runtime` 提供） | （上游）`skills_runtime/tools/builtin/*` | `docs_for_coding_agent/examples/atomic/00_runtime_minimal/` + `docs_for_coding_agent/examples/atomic/02_read_node_report/` + `docs_for_coding_agent/examples/recipes/00_review_fix_qa_report/` | `pytest -q tests/test_coding_agent_examples_atomic.py` + `pytest -q tests/test_coding_agent_examples_recipes.py` | `report.tool_calls[*].name/ok/error_kind` |
| CAP-TOOLS-004 | Skills Actions：`skill_exec`（Phase 3） | 上游 tools（builtin：`skill_exec`） | （上游）`skills_runtime/tools/builtin/skill_exec.py` | `docs_for_coding_agent/examples/recipes/03_skill_exec_actions/` | `pytest -q tests/test_coding_agent_examples_recipes.py -k skill_exec_actions` | `report.tool_calls[*].name=="skill_exec"` + WAL 中 approvals 事件 |
| CAP-TOOLS-002 | approvals：工具审批证据链 | `openspec/specs/evidence-chain/spec.md` | `src/agently_skills_runtime/reporting/node_report.py` | `examples/apps/*`（本变更创建） | `pytest -q`（本仓） | `approval_requested/approval_decided` 事件能聚合到 NodeReport |
| CAP-TOOLS-003 | custom_tools：宿主注入工具 | `openspec/specs/upstream-bridge/spec.md` | `src/agently_skills_runtime/config.py` | `docs_for_coding_agent/examples/atomic/04_custom_tool/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k custom_tool` | `report.tool_calls` 包含自定义工具调用 |
| CAP-TOOLS-005 | invoke_capability：能力委托（Agent→子 Agent/Workflow） | `openspec/specs/host-lifecycle-toolkit/spec.md` | `src/agently_skills_runtime/host_toolkit/invoke_capability.py` | `docs_for_coding_agent/examples/recipes/04_invoke_capability_child_agent/` + `docs_for_coding_agent/examples/recipes/05_invoke_capability_child_workflow/` | `pytest -q tests/test_coding_agent_examples_recipes.py -k invoke_capability` + `pytest -q tests/test_host_toolkit_invoke_capability.py` | `report.tool_calls[*].name=="invoke_capability"` + `artifact_path/sha256` |
| CAP-EXEC-001 | exec sessions：exec_command/write_stdin | 上游 tools（需要注入 exec_sessions provider） | `src/agently_skills_runtime/runtime.py`（注入点） | `docs_for_coding_agent/examples/atomic/05_exec_sessions_stub/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k exec_sessions_stub` | `tool_calls[*].data.session_id`（running=True 时） |
| CAP-COLLAB-001 | collab：spawn_agent/send_input/wait/close | 上游 tools（需要注入 collab_manager） | `src/agently_skills_runtime/runtime.py`（注入点） | `docs_for_coding_agent/examples/atomic/06_collab_stub/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k collab_stub` | `wait.data.results[*].final_output` |
| CAP-WEB-001 | web_search：默认禁用（fail-closed） | 上游 tools | （上游）`skills_runtime/tools/builtin/web_search.py` | `docs_for_coding_agent/examples/atomic/07_web_search_offline/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k web_search_offline` | tool error_kind=validation（disabled） |
| CAP-IMG-001 | view_image：离线读取图片 base64 | 上游 tools | （上游）`skills_runtime/tools/builtin/view_image.py` | `docs_for_coding_agent/examples/atomic/08_view_image_offline/` | `pytest -q tests/test_coding_agent_examples_atomic.py -k view_image_offline` | tool data.mime/base64 |
| CAP-SSE-001 | HTTP/SSE：事件流 + 终态 + wal_locator | `openspec/specs/examples-human-apps/spec.md` | `examples/apps/sse_gateway_minimal/`（本变更创建） | `examples/apps/sse_gateway_minimal/`（本变更创建） | `pytest -q tests/test_examples_smoke.py -k sse`（本变更创建） | SSE 流包含 `run_started` 与终态（含 wal_locator） |

## 2) 上游内置工具清单（pinned: skills-runtime-sdk==0.1.6）

> 说明：以下为上游 `skills_runtime.tools.builtin.*` 模块名（用于覆盖矩阵与示例选择）。  
> 本仓示例以“类别覆盖”为主，不要求每个工具都单独一个人类 app，但在编码智能体示例库中应做到“可获得能力面不遗漏”。

- 文件/仓库：`read_file` / `file_read` / `file_write` / `grep_files` / `list_dir` / `apply_patch`
- 命令执行：`shell_exec` / `shell_command` / `shell`
- 人类交互：`request_user_input` / `ask_human` / `update_plan`
- Skills：`skill_ref_read` / `skill_exec`
- Web/Image：`web_search` / `view_image`
- Exec sessions：`exec_command` / `write_stdin`
- Collab：`spawn_agent` / `send_input` / `wait` / `close_agent` / `resume_agent`
