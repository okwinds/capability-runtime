"""原型验证：离线 Mock Agent 适配器。"""
from __future__ import annotations

from typing import Any, Dict

from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus


class PrototypeMockAdapter:
    """按 agent_id 返回确定性 mock 输出，确保 InputMapping 数据链路可回归。"""

    async def execute(
        self,
        *,
        spec: Any,
        input: Dict[str, Any],
        context: Any,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 mock 分派并返回与下游契约对齐的输出结构。"""
        aid = spec.base.id

        if aid == "content-parser":
            return _ok(
                {
                    "title": "Sample Analysis Document",
                    "sections": [
                        {
                            "title": "Introduction",
                            "content": "Opening paragraph about the topic.",
                            "word_count": 120,
                        },
                        {
                            "title": "Main Argument",
                            "content": "Core thesis and reasoning.",
                            "word_count": 350,
                        },
                        {
                            "title": "Evidence",
                            "content": "Supporting data and references.",
                            "word_count": 280,
                        },
                    ],
                    "total_sections": 3,
                }
            )

        if aid == "section-analyzer":
            title = input.get("section_title", "Unknown")
            scores = {"Introduction": 8.5, "Main Argument": 5.2, "Evidence": 3.1}
            score = scores.get(title, 6.0)
            return _ok(
                {
                    "section_title": title,
                    "quality_score": score,
                    "issues": [f"Issue found in '{title}'"] if score < 7 else [],
                    "highlights": [f"Strong point in '{title}'"] if score >= 7 else [],
                }
            )

        if aid == "tone-reviewer":
            return _ok(
                {
                    "tone_score": 7.2,
                    "tone_label": "formal",
                    "recommendations": ["Vary sentence structure"],
                }
            )

        if aid == "fact-checker":
            return _ok(
                {
                    "fact_score": 6.8,
                    "verified_claims": 5,
                    "disputed_claims": 1,
                    "unverifiable_claims": 2,
                }
            )

        if aid == "deep-investigator":
            return _ok(
                {
                    "root_causes": ["Insufficient citations", "Outdated data"],
                    "severity_assessment": "high",
                    "recommended_actions": [
                        "Add primary sources",
                        "Update statistics",
                    ],
                }
            )

        if aid == "positive-summarizer":
            return _ok(
                {
                    "summary": "Content is well-structured with strong highlights.",
                    "confidence": 0.85,
                }
            )

        if aid == "critical-reporter":
            return _ok(
                {
                    "summary": "Content has critical issues requiring attention.",
                    "action_items": ["Revise evidence section", "Add citations"],
                    "urgency": "high",
                }
            )

        if aid == "neutral-summarizer":
            return _ok(
                {
                    "summary": "Content shows mixed quality across sections.",
                    "areas_for_improvement": [
                        "Evidence quality",
                        "Source diversity",
                    ],
                }
            )

        if aid == "report-compiler":
            return _ok(
                {
                    "title": "Content Analysis Report",
                    "executive_summary": "Multi-perspective analysis complete.",
                    "detailed_findings": [
                        "3 sections analyzed",
                        "Tone: formal (7.2/10)",
                        "Facts: 5 verified, 1 disputed",
                    ],
                    "overall_score": 6.5,
                    "recommendation": "Revise evidence section before publication.",
                }
            )

        return CapabilityResult(status=CapabilityStatus.FAILED, error=f"Unknown agent: {aid}")


def _ok(output: Dict[str, Any]) -> CapabilityResult:
    """构造成功的统一返回结构。"""
    return CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)
