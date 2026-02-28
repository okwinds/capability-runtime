from __future__ import annotations

"""AgentSpec 单元测试。"""

from capability_runtime.protocol.agent import AgentIOSchema, AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilityRef, CapabilitySpec


def test_agent_spec_minimal():
    spec = AgentSpec(
        base=CapabilitySpec(id="MA-013", kind=CapabilityKind.AGENT, name="单角色设计师"),
    )
    assert spec.base.id == "MA-013"
    assert spec.tools == []
    assert spec.loop_compatible is False
    assert spec.llm_config is None
    assert spec.prompt_template is None
    assert spec.system_prompt is None


def test_agent_spec_full():
    spec = AgentSpec(
        base=CapabilitySpec(
            id="MA-013",
            kind=CapabilityKind.AGENT,
            name="单角色设计师",
            tags=["TP2"],
        ),
        tools=["web_search"],
        collaborators=[CapabilityRef(id="MA-014")],
        callable_workflows=[CapabilityRef(id="WF-001D")],
        input_schema=AgentIOSchema(
            fields={"角色定位": "str", "故事梗概": "str"},
            required=["角色定位"],
        ),
        output_schema=AgentIOSchema(fields={"角色小传": "str"}),
        loop_compatible=True,
        llm_config={"model": "deepseek-chat", "temperature": 0.7},
        prompt_template="设计角色：{角色定位}",
        system_prompt="你是角色设计专家",
    )
    assert spec.loop_compatible is True
    assert spec.input_schema.required == ["角色定位"]
    assert spec.llm_config["model"] == "deepseek-chat"


def test_agent_io_schema_defaults():
    schema = AgentIOSchema()
    assert schema.fields == {}
    assert schema.required == []
