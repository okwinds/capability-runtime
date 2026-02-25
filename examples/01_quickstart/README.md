# examples/01_quickstart

本目录提供重构后的最短可复制闭环示例（以 `Runtime` 为唯一入口）。

## 0) 安装（开发态）

```bash
python -m pip install -e ".[dev]"
```

## 1) 离线 mock（无需真实 LLM）

```bash
python examples/01_quickstart/run_mock.py
```

## 2) Bridge（连接真实 LLM，需配置）

1. 复制环境模板：

```bash
cp examples/01_quickstart/.env.example examples/01_quickstart/.env
```

2. 编辑 `examples/01_quickstart/.env`，填入你的 provider 配置（OpenAI-compatible）。
3. 运行：

```bash
python examples/01_quickstart/run_bridge.py
```

说明：
- `mode="bridge"` 复用 Agently 的 OpenAICompatible requester 作为传输/流式层，但 **messages/tools wire** 仍由上游 `skills_runtime` 生产与解析（避免 tool_calls 口径分叉）。
- 若你不想依赖 Agently，可将示例改为 `mode="sdk_native"`，使用 `skills_runtime` 原生 OpenAI backend（同样会产出 `NodeReportV2`）。
