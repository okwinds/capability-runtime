"""原型验证：13 个能力声明（2 Skill + 9 Agent + 2 Workflow）。"""
from __future__ import annotations

from agently_skills_runtime.protocol.agent import AgentIOSchema, AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityRef, CapabilitySpec
from agently_skills_runtime.protocol.skill import SkillDispatchRule, SkillSpec
from agently_skills_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)

SK_001 = SkillSpec(
    base=CapabilitySpec(
        id="review-rubric",
        kind=CapabilityKind.SKILL,
        name="Review Rubric",
        description="Evaluation criteria injected into reviewer agents",
    ),
    source=(
        "## Content Review Rubric\n\n"
        "### Tone Criteria\n"
        "- Clarity (1-10)\n- Consistency (1-10)\n- Appropriateness (1-10)\n\n"
        "### Fact-Check Criteria\n"
        "- Verifiability (1-10)\n- Accuracy (1-10)\n- Source quality (1-10)\n\n"
        "### Severity: score>=7 -> positive, 4<=score<7 -> neutral, score<4 -> critical"
    ),
    source_type="inline",
    inject_to=["tone-reviewer", "fact-checker"],
)

SK_002 = SkillSpec(
    base=CapabilitySpec(
        id="escalation-policy",
        kind=CapabilityKind.SKILL,
        name="Escalation Policy",
        description="Auto-dispatch deep investigator on critical issues",
    ),
    source="When critical issues found, trigger deep investigation.",
    source_type="inline",
    dispatch_rules=[
        SkillDispatchRule(
            condition="critical_detected",
            target=CapabilityRef(id="deep-investigator"),
            priority=10,
        )
    ],
)

AG_001 = AgentSpec(
    base=CapabilitySpec(
        id="content-parser",
        kind=CapabilityKind.AGENT,
        name="Content Parser",
        description="Parse content into structured sections.",
    ),
    system_prompt="You are a content structure analyst. Parse content into sections.",
    prompt_template="Parse the following content into sections:\n\n{raw_content}",
    output_schema=AgentIOSchema(
        fields={
            "title": "str: overall title",
            "sections": "list: [{title, content, word_count}]",
            "total_sections": "int",
        }
    ),
)

AG_002 = AgentSpec(
    base=CapabilitySpec(
        id="section-analyzer",
        kind=CapabilityKind.AGENT,
        name="Section Analyzer",
        description="Analyze quality for each parsed section.",
    ),
    system_prompt="You are a content quality analyst.",
    prompt_template=(
        "Analyze section:\nTitle: {section_title}\n"
        "Content: {section_content}\nMode: {analysis_mode}"
    ),
    output_schema=AgentIOSchema(
        fields={
            "section_title": "str",
            "quality_score": "float: 0-10",
            "issues": "list[str]",
            "highlights": "list[str]",
        }
    ),
    loop_compatible=True,
)

AG_003 = AgentSpec(
    base=CapabilitySpec(
        id="tone-reviewer",
        kind=CapabilityKind.AGENT,
        name="Tone Reviewer",
        description="Review tone and style quality.",
    ),
    system_prompt="You are a tone and style expert. Use the review rubric provided.",
    prompt_template="Review the tone of:\n\n{content_summary}",
    output_schema=AgentIOSchema(
        fields={
            "tone_score": "float: 0-10",
            "tone_label": "str: formal/casual/mixed",
            "recommendations": "list[str]",
        }
    ),
    skills=["review-rubric"],
)

AG_004 = AgentSpec(
    base=CapabilitySpec(
        id="fact-checker",
        kind=CapabilityKind.AGENT,
        name="Fact Checker",
        description="Check factual claims and evidence quality.",
    ),
    system_prompt="You are a fact-checking specialist. Use the review rubric provided.",
    prompt_template="Verify factual claims in:\n\n{content_summary}",
    output_schema=AgentIOSchema(
        fields={
            "fact_score": "float: 0-10",
            "verified_claims": "int",
            "disputed_claims": "int",
            "unverifiable_claims": "int",
        }
    ),
    skills=["review-rubric"],
)

AG_005 = AgentSpec(
    base=CapabilitySpec(
        id="deep-investigator",
        kind=CapabilityKind.AGENT,
        name="Deep Investigator",
        description="Deep investigation for escalated critical issues.",
    ),
    system_prompt="You are a deep investigation specialist.",
    prompt_template="Conduct deep investigation on:\n\n{target}",
    output_schema=AgentIOSchema(
        fields={
            "root_causes": "list[str]",
            "severity_assessment": "str",
            "recommended_actions": "list[str]",
        }
    ),
)

AG_006 = AgentSpec(
    base=CapabilitySpec(
        id="positive-summarizer",
        kind=CapabilityKind.AGENT,
        name="Positive Summarizer",
        description="Summarize positive outcomes.",
    ),
    system_prompt="Summarize positive analysis results.",
    prompt_template="Content scored positively. Highlights:\n{analysis_data}",
    output_schema=AgentIOSchema(fields={"summary": "str", "confidence": "float"}),
)

AG_007 = AgentSpec(
    base=CapabilitySpec(
        id="critical-reporter",
        kind=CapabilityKind.AGENT,
        name="Critical Reporter",
        description="Generate critical issue report.",
    ),
    system_prompt="Generate critical issue report.",
    prompt_template="Content has critical issues:\n{analysis_data}",
    output_schema=AgentIOSchema(
        fields={
            "summary": "str",
            "action_items": "list[str]",
            "urgency": "str",
        }
    ),
)

AG_008 = AgentSpec(
    base=CapabilitySpec(
        id="neutral-summarizer",
        kind=CapabilityKind.AGENT,
        name="Neutral Summarizer",
        description="Provide balanced summary for mixed results.",
    ),
    system_prompt="Provide a balanced summary.",
    prompt_template="Content has mixed results:\n{analysis_data}",
    output_schema=AgentIOSchema(
        fields={"summary": "str", "areas_for_improvement": "list[str]"}
    ),
)

AG_009 = AgentSpec(
    base=CapabilitySpec(
        id="report-compiler",
        kind=CapabilityKind.AGENT,
        name="Report Compiler",
        description="Compile all analysis artifacts into final report.",
    ),
    system_prompt="Compile all analysis into a final report.",
    prompt_template=(
        "Compile final report:\n"
        "Section analyses: {section_analyses}\n"
        "Review results: {review_results}\n"
        "Summary: {summary}"
    ),
    output_schema=AgentIOSchema(
        fields={
            "title": "str",
            "executive_summary": "str",
            "detailed_findings": "list[str]",
            "overall_score": "float",
            "recommendation": "str",
        }
    ),
)

WF_001 = WorkflowSpec(
    base=CapabilitySpec(
        id="parallel-review",
        kind=CapabilityKind.WORKFLOW,
        name="Parallel Review",
        description="Run tone and fact review in parallel.",
    ),
    steps=[
        ParallelStep(
            id="multi-review",
            branches=[
                Step(
                    id="tone",
                    capability=CapabilityRef(id="tone-reviewer"),
                    input_mappings=[
                        InputMapping(
                            source="context.content_summary",
                            target_field="content_summary",
                        )
                    ],
                ),
                Step(
                    id="facts",
                    capability=CapabilityRef(id="fact-checker"),
                    input_mappings=[
                        InputMapping(
                            source="context.content_summary",
                            target_field="content_summary",
                        )
                    ],
                ),
            ],
            join_strategy="best_effort",
        )
    ],
    output_mappings=[
        InputMapping(source="step.multi-review", target_field="review_results")
    ],
)

WF_002 = WorkflowSpec(
    base=CapabilitySpec(
        id="content-analysis",
        kind=CapabilityKind.WORKFLOW,
        name="Content Analysis Pipeline",
        description="Main workflow with parse-loop-parallel-route-compile chain.",
    ),
    steps=[
        Step(
            id="parse",
            capability=CapabilityRef(id="content-parser"),
            input_mappings=[
                InputMapping(source="context.raw_content", target_field="raw_content"),
                InputMapping(source="literal.standard", target_field="parse_mode"),
            ],
        ),
        LoopStep(
            id="section-loop",
            capability=CapabilityRef(id="section-analyzer"),
            iterate_over="step.parse.sections",
            item_input_mappings=[
                InputMapping(source="item.title", target_field="section_title"),
                InputMapping(source="item.content", target_field="section_content"),
                InputMapping(source="context.analysis_depth", target_field="analysis_mode"),
            ],
            max_iterations=50,
            fail_strategy="skip",
        ),
        Step(
            id="parallel-review-step",
            capability=CapabilityRef(id="parallel-review"),
            input_mappings=[
                InputMapping(source="step.parse.title", target_field="content_summary")
            ],
        ),
        ConditionalStep(
            id="route-by-severity",
            condition_source="context.overall_severity",
            branches={
                "positive": Step(
                    id="summarize-positive",
                    capability=CapabilityRef(id="positive-summarizer"),
                    input_mappings=[
                        InputMapping(source="step.section-loop", target_field="analysis_data")
                    ],
                ),
                "critical": Step(
                    id="report-critical",
                    capability=CapabilityRef(id="critical-reporter"),
                    input_mappings=[
                        InputMapping(source="step.section-loop", target_field="analysis_data")
                    ],
                ),
            },
            default=Step(
                id="summarize-neutral",
                capability=CapabilityRef(id="neutral-summarizer"),
                input_mappings=[
                    InputMapping(source="step.section-loop", target_field="analysis_data")
                ],
            ),
        ),
        Step(
            id="compile",
            capability=CapabilityRef(id="report-compiler"),
            input_mappings=[
                InputMapping(source="step.section-loop", target_field="section_analyses"),
                InputMapping(
                    source="step.parallel-review-step", target_field="review_results"
                ),
                InputMapping(source="previous.summary", target_field="summary"),
            ],
        ),
    ],
    output_mappings=[
        InputMapping(source="step.parse", target_field="parsed_content"),
        InputMapping(source="step.section-loop", target_field="section_analyses"),
        InputMapping(source="step.parallel-review-step", target_field="review_results"),
        InputMapping(source="step.route-by-severity", target_field="severity_summary"),
        InputMapping(source="step.compile", target_field="final_report"),
    ],
)

ALL_SKILLS = [SK_001, SK_002]
ALL_AGENTS = [AG_001, AG_002, AG_003, AG_004, AG_005, AG_006, AG_007, AG_008, AG_009]
ALL_WORKFLOWS = [WF_001, WF_002]
ALL_SPECS = ALL_SKILLS + ALL_AGENTS + ALL_WORKFLOWS

__all__ = [
    "SK_001",
    "SK_002",
    "AG_001",
    "AG_002",
    "AG_003",
    "AG_004",
    "AG_005",
    "AG_006",
    "AG_007",
    "AG_008",
    "AG_009",
    "WF_001",
    "WF_002",
    "ALL_SKILLS",
    "ALL_AGENTS",
    "ALL_WORKFLOWS",
    "ALL_SPECS",
]
