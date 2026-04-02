# Atomic: 07_web_search_offline（web_search：默认 fail-closed）

本示例只教学一个能力点：**web_search 默认关闭（fail-closed）**。

你将看到：
- 未配置 provider 时，`web_search` 返回 `error_kind="validation"`（disabled）
- 该行为可用于离线门禁（避免外网依赖）

注意：
- 当前 pinned 的上游 `skills_runtime.core.agent.Agent` 尚未提供 `web_search_provider` 的注入入口，
  因此本仓 bridge 路径下无法在运行时打开 web_search（需要上游或桥接层进一步演进）。

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/07_web_search_offline/run.py --workspace-root /tmp/caprt-atomic-07
```

