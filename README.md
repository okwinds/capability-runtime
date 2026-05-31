<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# capability-runtime

`capability-runtime` is a production-oriented runtime/adapter layer that exposes a
stable `Runtime` API while composing two upstream systems:

- `skills-runtime-sdk` for skills, tools, approvals, WAL, and event evidence
- `Agently` for OpenAI-compatible transport and TriggerFlow-based orchestration internals

The public contract of this repository is intentionally narrow:

- capability primitives: `AgentSpec` and `WorkflowSpec`
- execution entrypoint: `Runtime`
- evidence surface: `NodeReport`, host snapshots, and service-facade helpers

## What You Get

- A single execution surface: `Runtime.run()` and `Runtime.run_stream()`
- Public capability registration and manifest descriptors
- Workflow orchestration on top of the runtime without exposing TriggerFlow as a public API
- Evidence-first results through `NodeReport`, tool-call reports, approval summaries, and WAL locators
- Host-facing helpers for wait/resume, approval tickets, continuity, and service streaming
- Runtime capability previews behind the same runtime contract:
  Responses requester opt-in, Dynamic DAG preview, workflow lifecycle summaries,
  Workspace/Recall context packs, and Action artifact evidence summaries

## Architecture At A Glance

```text
                           +-----------------------------+
                           | Host Application            |
                           | - register capabilities     |
                           | - run / stream / continue   |
                           +--------------+--------------+
                                          |
                                          v
+------------------------------------------------------------------------+
| capability-runtime                                                     |
|                                                                        |
|  Public contract                                                       |
|  - AgentSpec / WorkflowSpec                                            |
|  - Runtime                                                             |
|  - NodeReport / HostRunSnapshot / RuntimeServiceFacade                 |
|                                                                        |
|  Internal adapters                                                     |
|  - AgentAdapter                                                        |
|  - TriggerFlowWorkflowEngine                                           |
|  - service/session continuity bridge                                   |
+------------------------------+-----------------------------------------+
                               |
                               v
                 +-------------------------------+
                 | skills-runtime-sdk            |
                 | - skills + tools              |
                 | - approvals + exec sessions   |
                 | - WAL / AgentEvent evidence   |
                 +---------------+---------------+
                                 |
                                 v
                 +-------------------------------+
                 | Agently / TriggerFlow         |
                 | - OpenAI-compatible transport |
                 | - workflow execution internals|
                 +-------------------------------+
```

## Install

From source:

```bash
python -m pip install -e .
```

With development dependencies:

```bash
python -m pip install -e ".[dev]"
```

When the package is published, the install form is:

```bash
python -m pip install capability-runtime
```

Import name:

```python
import capability_runtime
```

## Quickstart

### 1. Offline runtime loop

```bash
python examples/01_quickstart/run_mock.py
```

This path is the smallest reproducible loop:

- register an `AgentSpec`
- validate the registry
- run in `mode="mock"`
- inspect the terminal `CapabilityResult`

### 2. Bridge mode with a real model backend

```bash
cp examples/01_quickstart/.env.example examples/01_quickstart/.env
python examples/01_quickstart/run_bridge.py
```

Bridge mode reuses Agently's OpenAI-compatible transport but still delegates the
actual skills/tools/WAL semantics to `skills-runtime-sdk`. The legacy requester
strategy is `chat_completions`. Responses mode is an explicit opt-in with
`RuntimeConfig.requester_strategy="responses"`; it is not the default.

Real provider wiring order:

1. Verify the provider model name with the gateway or `/models` surface.
2. Configure the provider chat lane with `OpenAICompatible` for chat/completions.
3. Configure the provider responses lane with `OpenAIResponsesCompatible` only if
   the provider supports `/responses`.
4. Run the runtime chat path with
   `RuntimeConfig(mode="bridge", requester_strategy="chat_completions")`.
5. Run the runtime responses path with
   `RuntimeConfig(mode="bridge", requester_strategy="responses")`.

Model routing has a separate priority chain: `AgentSpec.llm_config["model"]`
overrides the SDK `ChatRequest.model`, and that request model is the runtime
bridge source of truth when the provider usage payload omits `model`. Agently
settings configure transport details such as base URL, auth, and requester
plugin settings; they do not replace `AgentSpec.llm_config.model`.

### 3. Workflow orchestration

```bash
python examples/02_workflow/run.py
```

### 4. Runtime capability previews

```bash
python examples/05_dynamic_dag_preview/run.py
python examples/06_responses_bridge/run.py
```

These previews keep the public surface inside `capability_runtime`: use
`DynamicWorkflowPlan` / runtime methods for Dynamic DAGs and
`RuntimeConfig.requester_strategy` for Responses. Do not build downstream code on
upstream-native `TaskDAG`, `DynamicTask`, `Workspace`, `Action`, or requester
objects.

For a higher-level index, start with [examples/README.md](examples/README.md).

## Public API At A Glance

The package root exposes the supported contract:

```python
from capability_runtime import (
    Runtime,
    RuntimeConfig,
    CustomTool,
    AgentSpec,
    AgentIOSchema,
    WorkflowSpec,
    Step,
    LoopStep,
    ParallelStep,
    ConditionalStep,
    InputMapping,
    CapabilitySpec,
    CapabilityKind,
    CapabilityResult,
    CapabilityStatus,
    NodeReport,
    HostRunSnapshot,
    ApprovalTicket,
    ResumeIntent,
    RuntimeServiceFacade,
    RuntimeServiceRequest,
    RuntimeServiceHandle,
    RuntimeSession,
)
```

The runtime currently supports three execution modes through `RuntimeConfig.mode`:

- `mock`: deterministic local testing without a real LLM backend
- `bridge`: provider transport adapter + `skills-runtime-sdk` execution semantics
- `sdk_native`: native `skills-runtime-sdk` backend without the provider transport adapter

Provider bridge strategy is separate from `mode`:

- `RuntimeConfig.requester_strategy="chat_completions"`: legacy-compatible
  default bridge path.
- `RuntimeConfig.requester_strategy="responses"`: opt-in Responses bridge path.
- `sdk_backend` injection takes precedence over both strategies for offline
  regression and fake-backend tests.

Dynamic DAG preview is separate from `WorkflowSpec.steps`: compile a TaskDAG-like
mapping into the runtime-owned `DynamicWorkflowPlan`, keep `max_dynamic_nodes`
bounded, and execute nodes only through registered capabilities.

Provider audit evidence is expected in `NodeReport.usage`: preserve
`model`, `request_id`, `provider`, and token counts when the provider returns
them. If the provider omits `model`, the request model from `ChatRequest.model`
is the fallback; never treat an SDK placeholder such as `gpt-4` as real provider
evidence when a more specific request/provider model is available.

## Repository Layout

```text
.
├── src/capability_runtime/      # package source
├── examples/                    # human-facing runnable examples
├── docs_for_coding_agent/       # compact pack for coding agents
├── help/                        # public help and operational guides
├── config/                      # example config shapes
├── scripts/                     # release / validation helpers
└── tests/                       # offline regression guardrails
```

## Documentation Map

- [help/README.md](help/README.md): public help index
- [examples/README.md](examples/README.md): runnable examples by scenario
- [docs_for_coding_agent/README.md](docs_for_coding_agent/README.md): compact coding-agent pack
- [config/README.md](config/README.md): config shape reference

Recommended reading order for new users:

1. [help/00-overview.md](help/00-overview.md)
2. [help/01-quickstart.md](help/01-quickstart.md)
3. [help/03-python-api.md](help/03-python-api.md)
4. [examples/README.md](examples/README.md)

## Release And PyPI Publishing

This repository ships GitHub Actions workflows for:

- Tier-0 CI on push and pull request
- tag-driven and manual PyPI publishing

Release guardrails:

- the Git tag must match `pyproject.toml`'s `[project].version`
- the Git tag must match `capability_runtime.__version__`
- the publish job builds both sdist and wheel before uploading

The publish workflow is designed for PyPI Trusted Publishing. You still need to
configure the corresponding Trusted Publisher entry on `pypi.org`.

## Relationship To The Upstreams

- `skills-runtime-sdk` remains the source of truth for skills, approvals, tools,
  WAL, and event evidence.
- `Agently` remains the transport/orchestration substrate where this repository
  chooses to bridge instead of forking or reimplementing.
- `capability-runtime` is the contract-convergence layer: it narrows those
  upstream capabilities into a smaller host-facing runtime surface.
- Legacy mode is non-breaking: if you do not configure Responses, Dynamic DAG,
  Workspace/Recall, or Action artifact evidence previews, existing
  `Runtime.run()` / `Runtime.run_stream()` / `WorkflowSpec` consumers can keep
  reading the existing `NodeReport` and UI event fields.
