# 技术栈（Tech Stack, v2）

## 1) 语言与运行环境

- Python：>= 3.10
- 异步：`async/await`（Adapter.execute 必须为 async）
- 类型风格：`dataclass/Enum`（协议层不使用 Pydantic）

## 2) 依赖（以 `pyproject.toml` 为准）

运行依赖（runtime deps）：
- `PyYAML`

可选上游依赖（用于 `adapters/`，不作为本包的强制依赖）：
- `agently`（可从 PyPI 安装，或以工作区 editable 安装）
- `skills-runtime-sdk-python`（当前无 PyPI 分发；建议以工作区 editable 安装）

开发/测试依赖（dev extras）：
- `pytest>=7`
- `pytest-asyncio>=0.23`

## 3) 本地开发与离线回归（实现阶段门禁）

安装（editable）：

```bash
pip install -e ".[dev]"
```

离线回归（全部）：

```bash
pytest -q
```

按目录回归（推荐先小后大）：

```bash
pytest -q tests/protocol
pytest -q tests/runtime
pytest -q tests/scenarios
```

## 4) 版本策略（v0.2.0）

- 本轮目标版本为 `0.2.0`（破坏式升级）。
- `protocol/` 与 `runtime/` 作为 v0.2.0 的稳定主线；旧 bridge-only 主线归档到 `legacy/`。

## 5) 假设（Assumptions）

- 上游依赖在开发机可安装或可通过工作区路径引入；若上游不可用，protocol/runtime 的单测仍应可独立运行（Adapter 测试可用 mock 降级）。
