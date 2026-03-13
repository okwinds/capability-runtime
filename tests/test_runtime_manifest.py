from __future__ import annotations

from capability_runtime import (
    AgentSpec,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityManifestEntry,
    CapabilityRef,
    CapabilitySpec,
    CapabilityVisibility,
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)
from capability_runtime.registry import CapabilityRegistry


def _build_runtime() -> Runtime:
    """构造仅用于 registry/manifest 回归的离线 Runtime。"""

    return Runtime(
        RuntimeConfig(
            mode="mock",
            mock_handler=lambda spec, input, context=None: {"ok": True},
        )
    )


def test_runtime_register_with_manifest_auto_generates_descriptor() -> None:
    """回归：`register_with_manifest()` 应基于 spec.base 生成可消费 descriptor。"""

    rt = _build_runtime()
    agent = AgentSpec(
        base=CapabilitySpec(
            id="agent.public",
            kind=CapabilityKind.AGENT,
            name="Public Agent",
            description="demo",
            version="1.2.3",
            tags=["demo", "public"],
        ),
        skills=["demo-skill"],
    )

    entry = rt.register_with_manifest(agent)

    assert entry.capability_id == "agent.public"
    assert entry.kind == CapabilityKind.AGENT
    assert entry.version == "1.2.3"
    assert entry.visibility == CapabilityVisibility.PUBLIC

    descriptor = rt.describe_capability("agent.public")
    assert isinstance(descriptor, CapabilityDescriptor)
    assert descriptor.entry == entry
    assert descriptor.spec == agent
    assert descriptor.dependencies == []


def test_registry_manifest_entry_can_exist_without_spec_and_be_hidden_from_exposed_listing() -> None:
    """回归：manifest entry 可独立注册，且 `expose=False` 不应出现在 exposed list。"""

    registry = CapabilityRegistry()
    hidden = CapabilityManifestEntry(
        capability_id="agent.internal",
        kind=CapabilityKind.AGENT,
        version="0.1.0",
        name="Internal Agent",
        visibility=CapabilityVisibility.INTERNAL,
        expose=False,
        source="runtime.register_manifest",
    )

    registry.register_manifest_entry(hidden)

    descriptor = registry.get_descriptor("agent.internal")
    assert isinstance(descriptor, CapabilityDescriptor)
    assert descriptor.entry == hidden
    assert descriptor.spec is None

    all_ids = [item.entry.capability_id for item in registry.list_descriptors()]
    exposed_ids = [item.entry.capability_id for item in registry.list_descriptors(exposed_only=True)]
    public_ids = [
        item.entry.capability_id
        for item in registry.list_descriptors(visibility=CapabilityVisibility.PUBLIC)
    ]

    assert all_ids == ["agent.internal"]
    assert exposed_ids == []
    assert public_ids == []


def test_workflow_descriptor_collects_nested_dependencies() -> None:
    """回归：workflow descriptor 必须收敛嵌套 step/branch/loop 的 capability refs。"""

    rt = _build_runtime()
    workflow = WorkflowSpec(
        base=CapabilitySpec(
            id="workflow.main",
            kind=CapabilityKind.WORKFLOW,
            name="Main Workflow",
            version="2.0.0",
        ),
        steps=[
            Step(
                id="draft",
                capability=CapabilityRef(id="agent.draft"),
                input_mappings=[InputMapping(source="input.topic", target_field="topic")],
            ),
            ParallelStep(
                id="parallel",
                branches=[
                    Step(id="review", capability=CapabilityRef(id="agent.review")),
                    ConditionalStep(
                        id="route",
                        condition_source="context.route",
                        branches={
                            "loop": LoopStep(
                                id="loop",
                                capability=CapabilityRef(id="agent.loop"),
                                iterate_over="context.items",
                            )
                        },
                        default=Step(id="fallback", capability=CapabilityRef(id="agent.fallback")),
                    ),
                ],
            ),
        ],
    )

    rt.register_with_manifest(workflow)
    descriptor = rt.describe_capability("workflow.main")

    assert isinstance(descriptor, CapabilityDescriptor)
    assert descriptor.spec == workflow
    assert {ref.id for ref in descriptor.dependencies} == {
        "agent.draft",
        "agent.review",
        "agent.loop",
        "agent.fallback",
    }
