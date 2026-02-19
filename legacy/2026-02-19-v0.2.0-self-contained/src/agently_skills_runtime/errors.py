"""
errors.py

框架错误定义（v0.2.0 主线）。

设计目标：
- 提供可被业务层捕获/分类的错误类型；
- 不引入上游依赖（Agently / skills-runtime-sdk）。
"""

from __future__ import annotations


class AgentlySkillsRuntimeError(Exception):
    """
    本仓库统一错误基类。

    说明：
    - 运行时内部可以选择“返回 CapabilityResult.FAILED”或“抛异常”两种方式表达失败；
    - 对业务层暴露时，建议统一用本基类及其子类承载“可诊断”的失败原因。
    """


class ConfigurationError(AgentlySkillsRuntimeError):
    """配置错误（缺字段、字段类型不匹配、配置文件无法解析等）。"""


class DependencyValidationError(AgentlySkillsRuntimeError):
    """依赖校验失败（注册表中存在缺失能力引用）。"""


class CapabilityNotFoundError(AgentlySkillsRuntimeError):
    """执行或引用了未注册/不存在的能力。"""


class AdapterNotConfiguredError(AgentlySkillsRuntimeError):
    """能力种类对应的 Adapter 未配置（例如 SkillAdapter 为空）。"""


class CapabilityExecutionError(AgentlySkillsRuntimeError):
    """能力执行失败（内部异常、循环熔断、协议不满足等）。"""


class UpstreamVerificationError(AgentlySkillsRuntimeError):
    """上游来源/版本校验失败（例如导入路径不在期望的 fork 根目录）。"""

