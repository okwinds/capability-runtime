<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# config/

本目录提供 `capability-runtime` 的配置形态示例。

重要边界：

- 公开入口是 `Runtime` 与 `RuntimeConfig`
- YAML 只表达配置形态，不表达 secrets
- approvals provider、provider requester factory 之类运行期对象仍由宿主代码注入，
  而不是靠静态 YAML 直接构造
- `provider_requester_factory` 是首选 bridge transport 注入入口；
  `agently_agent` 只保留为旧兼容路径，新应用代码不应把它作为主要 bridge 表面
- 常规 OpenAI-compatible 真实 provider 接线应由宿主 bootstrap 代码通过
  `build_openai_provider_requester_factory(...)` 构造该 factory。
  已经持有 provider 原生 agent 的宿主，应自行包装成 `ProviderRequesterFactory`；
  应用代码不要 import adapter 内部 helper。
- `build_openai_provider_requester_factory(...)` 默认拒绝明文 `http://`。
  受控私有 provider 必须显式传入 `allow_insecure_transport=True`，或设置
  `CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1`；发布门禁仍应限制受信 host。
- requester strategy 是 capability-runtime 配置。除非宿主显式 opt-in
  Responses，否则保持 `requester_strategy: "chat_completions"`。
- 模型选择不属于 Agently settings 职责。每个能力的模型通过
  `AgentSpec.llm_config["model"]` 设置；runtime 会把它复制到 SDK
  `ChatRequest.model`。

## 文件说明

- `default.yaml`
  - `RuntimeConfig` 的示例形态
  - 字段必须与 `src/capability_runtime/config.py` 保持一致
- `sdk.example.yaml`
  - `skills-runtime-sdk` overlay 示例
  - 用于 strict catalog、sources、mention/preflight 等形态说明

## 使用示例

```python
from pathlib import Path

import yaml

from capability_runtime import Runtime, RuntimeConfig

raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8")) or {}
cfg = RuntimeConfig(
    mode=str(raw.get("mode") or "bridge"),
    workspace_root=Path(str(raw.get("workspace_root") or ".")),
    preflight_mode=str(raw.get("preflight_mode") or "error"),
    requester_strategy=str(raw.get("requester_strategy") or "chat_completions"),
    max_dynamic_nodes=int(raw.get("max_dynamic_nodes") or 64),
)

runtime = Runtime(cfg)
print(runtime.validate())
```

## 说明

- `sdk_config_paths` 应由宿主侧指向真实 overlay 文件。
- `preflight_mode="error"` 是推荐的 fail-closed 默认值。
- `requester_strategy="responses"` 是 opt-in，不能被当成默认 bridge mode。
- 旧调用方仍可传 `RuntimeConfig.agently_requester`；新配置模板应优先使用
  `requester_strategy`。
- 旧调用方仍可传 `RuntimeConfig.agently_agent`；新的 bridge bootstrap 代码应优先使用
  `provider_requester_factory`，通常由 `build_openai_provider_requester_factory(...)`
  产生。
- 私有 `http://` provider 接线是显式例外，不是默认行为。优先使用 HTTPS；
  只有受控私有网络且已有 trusted-host guard 时才开启。
- `sdk.example.yaml` 配置 SDK/provider transport overlay，不覆写每个 agent
  的请求模型；请求模型应使用 `AgentSpec.llm_config.model`。
- 真实 provider 审计时，`NodeReport.usage` 应尽量保留 `model`、
  `request_id`、`provider` 与 token 计数。
- 默认情况下，`AgentSpec.llm_config.tool_choice` 会原样透传。只有当某个
  provider 在强制首轮工具调用后持续循环时，才显式使用
  `RuntimeConfig.tool_choice_after_tool_result="none"` 作为兼容开关。
- `max_dynamic_nodes` 用于约束 Dynamic DAG preview；不要接受无上限的模型生成图。
- 不要提交真实 `.env`、provider 凭证或环境专属 overlay 文件。
