"""
adapters/

上游适配器层：桥接 Agently 与 skills-runtime-sdk 的公共 API。

约束：
- 适配器可以依赖上游包；
- protocol/ 与 runtime/ 不得依赖上游包；
- 适配器的 execute() 必须为 async。
"""

