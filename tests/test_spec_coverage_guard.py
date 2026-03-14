from __future__ import annotations

"""
离线回归护栏：源码模块必须有对应的 docs/specs/ 源规格。

规则：
- 扫描 src/capability_runtime/ 下所有 ≥50 行的 .py 模块（排除 __init__.py）。
- 通过 SPEC_MAPPING（显式映射）或 SPEC_EXEMPTIONS（豁免列表）逐一核对。
- 不在映射/豁免中的模块 → 测试失败。
- 新模块禁止加入 SPEC_EXEMPTIONS；存量模块逐步补齐后移除。

对齐规格：docs/specs/spec-governance-guards-v1.md
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src" / "capability_runtime"
_SPECS_DIR = _REPO_ROOT / "docs" / "specs"

_MIN_LINES = 50

# 显式映射：模块相对路径（去掉 .py）→ 对应 spec 文件名列表
SPEC_MAPPING: dict[str, list[str]] = {
    "runtime": [
        "runtime-run-stream-semantics-v1.md",
        "runtime-structural-refactor-2026-03-01.md",
        "structured-output-bridge-v1.md",
        "structured-stream-consumption-v1.md",
    ],
    "logging_utils": ["runtime-error-observability-v1.md"],
    "reporting/node_report": ["node-report-v1.md"],
    "adapters/agently_backend": [
        "agently-backend-stream-event-ordering-v1.md",
        "per-capability-llm-config-v1.md",
    ],
    "protocol/context": ["execution-context-mapping-expression-v1.md"],
    "protocol/capability": ["capability-result-error-code.md"],
    "host_toolkit/invoke_capability": ["invoke-capability-artifact-v1.md"],
    "ui_events/projector": ["runtime-ui-events-v1.md"],
    "ui_events/session": ["runtime-ui-events-v1.md"],
    "ui_events/store": ["runtime-ui-events-v1.md"],
    "ui_events/transport": ["runtime-ui-events-v1.md"],
    "ui_events/v1": ["runtime-ui-events-v1.md"],
    "runtime_ui_events_mixin": ["runtime-ui-events-v1.md"],
    "upstream_compat": [
        "upgrade-skills-runtime-sdk-0.1.6.md",
        "upgrade-skills-runtime-sdk-0.1.7.md",
        "upgrade-skills-runtime-sdk-0.1.8.md",
        "upgrade-skills-runtime-sdk-0.1.9.md",
    ],
    # Phase 3 补齐
    "sdk_lifecycle": ["sdk-lifecycle-v1.md"],
    "adapters/triggerflow_workflow_engine": ["triggerflow-workflow-engine-v1.md"],
    "adapters/agent_adapter": ["agent-adapter-v1.md"],
    "host_toolkit/approvals_profiles": ["host-toolkit-v1.md"],
    "host_toolkit/evidence_hooks": ["host-toolkit-v1.md"],
    "host_toolkit/history": ["host-toolkit-v1.md"],
    "host_toolkit/resume": ["host-toolkit-v1.md"],
    "host_toolkit/system_prompt": ["host-toolkit-v1.md"],
    "host_toolkit/turn_delta": ["host-toolkit-v1.md"],
    "guards": ["runtime-support-modules-v1.md"],
    "registry": ["runtime-support-modules-v1.md"],
    "manifest": ["runtime-capability-manifest-v1.md"],
    "host_protocol": ["runtime-hitl-host-protocol-v1.md"],
    "workflow_runtime": ["workflow-host-runtime-surface-v1.md"],
    "service_facade": ["runtime-service-session-bridge-v1.md"],
    "services": ["runtime-support-modules-v1.md"],
    "output_validator": ["runtime-support-modules-v1.md"],
    "structured_output": ["structured-output-bridge-v1.md"],
    "protocol/agent": ["protocol-types-v1.md"],
    "protocol/workflow": ["protocol-types-v1.md"],
}

# 豁免列表：确实不需要独立 spec 的极小模块
SPEC_EXEMPTIONS: dict[str, str] = {
    "config": "行为隐含在 runtime-structural-refactor spec 中（151 行，支撑配置）",
    "errors": "极小模块（20 行），暂免",
    "types": "类型别名模块（85 行），暂免",
    "adapters/workflow_engine": "ABC，极小模块（43 行）",
    "utils/usage": "工具函数模块（65 行），抽取自 node_report/projector，行为隐含在 runtime-ui-events-v1 和 node-report-v1",
}


def _module_key(path: Path) -> str:
    """将源文件路径转换为模块 key（相对于 src/capability_runtime/，去掉 .py）。"""
    rel = path.relative_to(_SRC_ROOT)
    return str(rel.with_suffix("")).replace("\\", "/")


def _count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _spec_exists(spec_names: list[str]) -> bool:
    return any((_SPECS_DIR / name).is_file() for name in spec_names)


def test_all_significant_modules_have_spec_or_exemption() -> None:
    """
    断言：src/capability_runtime/ 下所有 ≥50 行的模块
    必须在 SPEC_MAPPING 或 SPEC_EXEMPTIONS 中声明。
    """
    modules = sorted(
        p
        for p in _SRC_ROOT.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in str(p)
    )

    uncovered: list[str] = []
    for mod_path in modules:
        if _count_lines(mod_path) < _MIN_LINES:
            continue
        key = _module_key(mod_path)
        if key in SPEC_EXEMPTIONS:
            continue
        if key in SPEC_MAPPING:
            continue
        uncovered.append(key)

    assert uncovered == [], (
        f"以下模块 ≥{_MIN_LINES} 行但未在 SPEC_MAPPING 或 SPEC_EXEMPTIONS 中声明。"
        f"请先在 docs/specs/ 创建对应源规格，然后添加到 SPEC_MAPPING；"
        f"或（仅限存量模块）添加到 SPEC_EXEMPTIONS 并标注 TODO。\n"
        f"未覆盖模块：{uncovered}"
    )


def test_spec_mapping_entries_point_to_existing_files() -> None:
    """
    断言：SPEC_MAPPING 中引用的 spec 文件实际存在于 docs/specs/。
    防止 spec 被重命名/删除后映射失效。
    """
    missing: list[tuple[str, str]] = []
    for module_key, spec_names in SPEC_MAPPING.items():
        for name in spec_names:
            if not (_SPECS_DIR / name).is_file():
                missing.append((module_key, name))

    assert missing == [], (
        f"SPEC_MAPPING 中引用了不存在的 spec 文件。"
        f"请检查文件是否被重命名或删除：{missing}"
    )


def test_exemptions_are_intentional() -> None:
    """
    断言：豁免列表中的条目都有明确理由（非空字符串）。
    若存在 TODO 标注，信息性输出待补数量。
    """
    empty_reasons = [k for k, v in SPEC_EXEMPTIONS.items() if not v.strip()]
    assert empty_reasons == [], f"SPEC_EXEMPTIONS 中以下条目缺少理由：{empty_reasons}"
    todo_count = sum(1 for reason in SPEC_EXEMPTIONS.values() if "TODO" in reason)
    total = len(SPEC_EXEMPTIONS)
    print(f"\n[spec-coverage] 豁免列表：{total} 项，其中 {todo_count} 项待补 spec")
