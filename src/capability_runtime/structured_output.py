from __future__ import annotations

"""结构化输出桥接：`output_schema` 校验、摘要留痕与结果收敛。"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .config import OutputValidationMode
from .logging_utils import log_suppressed_exception
from .protocol.agent import AgentIOSchema
from .protocol.capability import CapabilityResult, CapabilityStatus
from .types import NodeReport


@dataclass(frozen=True)
class StructuredOutputValidation:
    """一次结构化输出校验的收敛结果。"""

    ok: bool
    raw_output: str
    normalized_output: Optional[Dict[str, Any]]
    summary: Dict[str, Any]


def schema_id_for_capability(*, capability_id: str) -> str:
    """为 capability 生成稳定的结构化输出 schema_id。"""

    return f"capability-runtime.agent_output_schema.v1:{capability_id}"


def parse_json_object_snapshot(text: str) -> Optional[Dict[str, Any]]:
    """
    尝试把累计文本解析为 JSON object 快照。

    说明：
    - 只接受顶层 object；
    - 失败时返回 None，不做猜测性修复。
    """

    try:
        payload = json.loads(str(text or ""))
    except Exception as exc:
        log_suppressed_exception(
            context="parse_structured_output_json",
            exc=exc,
            extra={"text_len": len(str(text or ""))},
        )
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _digest_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """把 payload 归一为最小披露摘要。"""

    payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {
        "normalized_payload_sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        "normalized_payload_bytes": len(payload_text.encode("utf-8")),
        "normalized_payload_top_keys": sorted(list(payload.keys()))[:20],
    }


def validate_structured_output(
    *,
    final_output: Any,
    output_schema: AgentIOSchema,
    capability_id: str,
    mode: OutputValidationMode,
) -> StructuredOutputValidation:
    """
    基于 `AgentIOSchema` 校验终态输出。

    v1 语义：
    - 只接受顶层 JSON object
    - 只校验 required fields
    - 不拒绝额外字段
    - 不强做类型校验（`fields` 仍是描述字符串）
    """

    required = [str(name) for name in list(output_schema.required or []) if str(name)]
    summary: Dict[str, Any] = {
        "mode": mode,
        "ok": False,
        "schema_id": schema_id_for_capability(capability_id=capability_id),
        "required": required,
    }

    if isinstance(final_output, dict):
        normalized = dict(final_output)
        raw_output = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    else:
        raw_output = "" if final_output is None else str(final_output)
        try:
            parsed = json.loads(raw_output)
        except Exception as exc:
            log_suppressed_exception(
                context="validate_structured_output_parse",
                exc=exc,
                extra={"raw_output_len": len(raw_output)},
            )
            summary["errors"] = [
                {
                    "path": "$",
                    "kind": "invalid_json",
                    "message": "final_output is not valid JSON object",
                }
            ]
            return StructuredOutputValidation(
                ok=False,
                raw_output=raw_output,
                normalized_output=None,
                summary=summary,
            )
        if not isinstance(parsed, dict):
            summary["errors"] = [
                {
                    "path": "$",
                    "kind": "non_object",
                    "message": "final_output must be a top-level JSON object",
                }
            ]
            return StructuredOutputValidation(
                ok=False,
                raw_output=raw_output,
                normalized_output=None,
                summary=summary,
            )
        normalized = dict(parsed)

    present_keys = sorted(list(normalized.keys()))
    summary["present_keys"] = present_keys
    summary.update(_digest_payload(normalized))

    errors: List[Dict[str, str]] = []
    for field in required:
        if field not in normalized:
            errors.append(
                {
                    "path": f"$.{field}",
                    "kind": "missing_required",
                    "message": f"{field} is required",
                }
            )
    if errors:
        summary["errors"] = errors
        return StructuredOutputValidation(
            ok=False,
            raw_output=raw_output,
            normalized_output=normalized,
            summary=summary,
        )

    summary["ok"] = True
    summary["errors"] = []
    return StructuredOutputValidation(
        ok=True,
        raw_output=raw_output,
        normalized_output=normalized,
        summary=summary,
    )


def apply_structured_output_summary(
    *,
    report: NodeReport,
    validation: StructuredOutputValidation,
    fail_on_error: bool,
) -> None:
    """把结构化输出摘要写入 NodeReport，并在需要时 fail-closed。"""

    report.meta["structured_output"] = dict(validation.summary)
    if (not validation.ok) and fail_on_error:
        report.status = "failed"
        report.reason = "structured_output_error"
        report.meta["structured_output_overrode_status"] = True


def finalize_structured_result(
    *,
    result: CapabilityResult,
    validation: StructuredOutputValidation,
    fail_on_error: bool,
) -> CapabilityResult:
    """把普通 CapabilityResult 收敛为结构化结果。"""

    result.metadata["raw_output"] = validation.raw_output
    result.metadata["structured_output"] = dict(validation.summary)

    if result.node_report is not None:
        apply_structured_output_summary(
            report=result.node_report,
            validation=validation,
            fail_on_error=fail_on_error,
        )

    if not validation.ok:
        result.status = CapabilityStatus.FAILED
        result.output = None
        result.error = "Structured output contract violated"
        result.error_code = "STRUCTURED_OUTPUT_INVALID"
        return result

    result.output = dict(validation.normalized_output or {})
    result.error = None
    result.error_code = None
    return result
