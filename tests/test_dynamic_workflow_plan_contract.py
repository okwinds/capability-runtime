from __future__ import annotations

import pytest

from capability_runtime.dynamic_workflow import DynamicWorkflowPlanError, compile_task_dag
from capability_runtime.protocol import DynamicWorkflowNode, DynamicWorkflowPlan


def test_compile_task_dag_maps_tasks_to_neutral_nodes_with_stable_hash() -> None:
    task_dag = {
        "graph_id": "dag.preview",
        "task_schema_version": "agently.task_dag.v1",
        "semantic_outputs": {"answer": "final"},
        "policies": {"fail_strategy": "fail_fast"},
        "diagnostics": [{"source": "unit"}],
        "tasks": [
            {
                "id": "draft",
                "kind": "model",
                "title": "Draft",
                "purpose": "write draft",
                "binding": "agent.draft",
                "inputs": "seed",
                "produces": "draft_text",
            },
            {
                "id": "review",
                "kind": "skill",
                "depends_on": "draft",
                "inputs": {"capability_id": "agent.review", "tone": "strict"},
                "produces": {"review": "text"},
                "approval": {"required": True},
                "side_effect_policy": {"mode": "none"},
                "fallback": {"mode": "skip"},
            },
        ],
    }

    plan = compile_task_dag(task_dag, registry_ids={"agent.draft", "agent.review"})
    plan_again = compile_task_dag(dict(task_dag), registry_ids={"agent.draft", "agent.review"})

    assert isinstance(plan, DynamicWorkflowPlan)
    assert plan.graph_id == "dag.preview"
    assert plan.source == "task_dag"
    assert plan.plan_hash == plan_again.plan_hash
    assert [node.id for node in plan.nodes] == ["draft", "review"]

    draft, review = plan.nodes
    assert isinstance(draft, DynamicWorkflowNode)
    assert draft.kind == "model"
    assert draft.capability_id == "agent.draft"
    assert draft.inputs == {"value": "seed"}
    assert draft.produces == ("draft_text",)
    assert review.kind == "skill"
    assert review.depends_on == ("draft",)
    assert review.capability_id == "agent.review"
    assert review.produces == ("review",)
    assert review.approval_required is True

    diagnostics = list(plan.diagnostics)
    assert any(item.get("task_schema_version") == "agently.task_dag.v1" for item in diagnostics)
    assert any(item.get("semantic_outputs") == {"answer": "final"} for item in diagnostics)
    assert any(item.get("policies") == {"fail_strategy": "fail_fast"} for item in diagnostics)
    assert any(item.get("node_id") == "review" and "fallback" in item for item in diagnostics)


@pytest.mark.parametrize(
    ("task_dag", "error_code"),
    [
        ({"graph_id": "dup", "tasks": [{"id": "a", "kind": "model"}, {"id": "a", "kind": "model"}]}, "DYNAMIC_DAG_DUPLICATE_NODE"),
        ({"graph_id": "missing", "tasks": [{"id": "a", "kind": "model", "depends_on": "b"}]}, "DYNAMIC_DAG_UNKNOWN_DEPENDENCY"),
        ({"graph_id": "self", "tasks": [{"id": "a", "kind": "model", "depends_on": "a"}]}, "DYNAMIC_DAG_CYCLE"),
        (
            {
                "graph_id": "cycle",
                "tasks": [
                    {"id": "a", "kind": "model", "depends_on": "b"},
                    {"id": "b", "kind": "model", "depends_on": "a"},
                ],
            },
            "DYNAMIC_DAG_CYCLE",
        ),
        ({"graph_id": "bad-kind", "tasks": [{"id": "a", "kind": "unknown"}]}, "DYNAMIC_DAG_INVALID"),
    ],
)
def test_compile_task_dag_rejects_invalid_graphs_with_stable_error_codes(task_dag: dict, error_code: str) -> None:
    with pytest.raises(DynamicWorkflowPlanError) as exc:
        compile_task_dag(task_dag, registry_ids={"agent.any"})

    assert exc.value.error_code == error_code


def test_compile_task_dag_enforces_max_nodes_fail_closed() -> None:
    task_dag = {
        "graph_id": "too-large",
        "tasks": [
            {"id": "a", "kind": "model", "binding": "agent.a"},
            {"id": "b", "kind": "model", "binding": "agent.b"},
        ],
    }

    with pytest.raises(DynamicWorkflowPlanError) as exc:
        compile_task_dag(task_dag, registry_ids={"agent.a", "agent.b"}, max_nodes=1)

    assert exc.value.error_code == "DYNAMIC_DAG_TOO_LARGE"


def test_compile_task_dag_fails_when_node_cannot_resolve_registered_capability() -> None:
    task_dag = {
        "graph_id": "unresolved",
        "tasks": [{"id": "a", "kind": "model", "binding": "agent.missing"}],
    }

    with pytest.raises(DynamicWorkflowPlanError) as exc:
        compile_task_dag(task_dag, registry_ids={"agent.other"})

    assert exc.value.error_code == "DYNAMIC_DAG_NODE_UNRESOLVED"
