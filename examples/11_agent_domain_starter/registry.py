"""业务域能力注册入口。"""
from __future__ import annotations

from agently_skills_runtime import CapabilityRuntime

from agents import angle_writer, editor, topic_analyst
from skills import writing_style
from workflows import content_creation

ALL_SPECS = [
    topic_analyst.spec,
    angle_writer.spec,
    editor.spec,
    writing_style.spec,
    content_creation.spec,
]


def register_all(runtime: CapabilityRuntime) -> None:
    """注册本业务域所有能力，并执行依赖校验。"""
    runtime.register_many(ALL_SPECS)
    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")
