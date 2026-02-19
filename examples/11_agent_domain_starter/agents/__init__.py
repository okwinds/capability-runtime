"""Agent 声明集合。"""

from .angle_writer import spec as angle_writer_spec
from .editor import spec as editor_spec
from .topic_analyst import spec as topic_analyst_spec

__all__ = ["topic_analyst_spec", "angle_writer_spec", "editor_spec"]
