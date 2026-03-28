"""Output 校验组件：包装 output_validator 并写入 NodeReport.meta。"""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, Callable, Dict, Optional

from .config import OutputValidationMode
from .structured_output import apply_structured_output_summary, validate_structured_output
from .types import NodeReport


class OutputValidator:
    """输出校验器（mode + validator callback 的组合封装）。"""

    def __init__(self, *, mode: OutputValidationMode, validator: Optional[Callable[..., Any]]) -> None:
        """
        构造输出校验器。

        参数：
        - mode：`off/warn/error`
        - validator：可选校验回调（推荐 keyword-only 签名）
        """

        self._mode = mode
        self._validator = validator

    def _invoke_validator(self, *, final_output: Any, report: NodeReport, context: Dict[str, Any]) -> Any:
        """
        调用 validator，并只在“签名确实不匹配”时回退到 positional。

        说明：
        - 不用 `except TypeError` 直接判定签名不匹配，避免把 validator 内部 bug 误吞；
        - 优先走推荐的 keyword-only 契约：`(*, final_output, node_report, context)`。
        """

        validator = self._validator
        assert validator is not None

        keyword_args = {"final_output": final_output, "node_report": report, "context": context}
        try:
            signature = inspect.signature(validator)
        except (TypeError, ValueError):
            return validator(final_output, report, context)

        try:
            signature.bind_partial(**keyword_args)
        except TypeError as keyword_bind_error:
            try:
                signature.bind_partial(final_output, report, context)
            except TypeError:
                raise keyword_bind_error
            return validator(final_output, report, context)
        return validator(**keyword_args)

    def validate(
        self,
        *,
        final_output: Any,
        report: NodeReport,
        context: Dict[str, Any],
        output_schema: Optional[Any] = None,
    ) -> None:
        """
        调用 output_validator 并把“最小披露”摘要写入 NodeReport.meta。

        行为：
        - mode=off：不调用
        - mode=warn：记录摘要但不覆盖状态
        - mode=error：validator 返回 ok=False 时覆盖为 failed（可回归护栏）
        """

        capability_id = str(context.get("capability_id") or "")
        if output_schema is not None and getattr(output_schema, "fields", None):
            validation = validate_structured_output(
                final_output=final_output,
                output_schema=output_schema,
                capability_id=capability_id,
                mode=self._mode,
            )
            apply_structured_output_summary(
                report=report,
                validation=validation,
                fail_on_error=self._mode == "error",
            )

        if self._mode == "off" or self._validator is None:
            return

        try:
            raw = self._invoke_validator(final_output=final_output, report=report, context=context)
        except Exception as exc:
            # validator 自身异常：作为可观测信息记录；不强行失败（避免“验证器把系统打挂”）。
            report.meta["output_validation"] = {
                "mode": self._mode,
                "ok": False,
                "error": f"validator_exception:{type(exc).__name__}",
            }
            if self._mode == "error":
                report.status = "failed"
                report.reason = "output_validation_error"
                report.meta["output_validation_overrode_status"] = True
            return

        if not isinstance(raw, dict):
            report.meta["output_validation"] = {
                "mode": self._mode,
                "ok": True,
                "note": "validator_return_not_dict",
            }
            return

        ok = bool(raw.get("ok", True))
        schema_id = raw.get("schema_id") if isinstance(raw.get("schema_id"), str) else None
        errors = raw.get("errors") if isinstance(raw.get("errors"), list) else []

        summary: Dict[str, Any] = {"mode": self._mode, "ok": ok}
        if schema_id:
            summary["schema_id"] = schema_id
        if errors:
            # errors 期望是可披露的摘要条目（path/kind/message）
            summary["errors"] = errors

        normalized_payload = raw.get("normalized_payload")
        if isinstance(normalized_payload, dict):
            payload_text = json.dumps(normalized_payload, ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            summary["normalized_payload_sha256"] = digest
            summary["normalized_payload_bytes"] = len(payload_text.encode("utf-8"))
            summary["normalized_payload_top_keys"] = sorted(list(normalized_payload.keys()))[:20]

        report.meta["output_validation"] = summary

        if (not ok) and self._mode == "error":
            report.status = "failed"
            report.reason = "output_validation_error"
            report.meta["output_validation_overrode_status"] = True
