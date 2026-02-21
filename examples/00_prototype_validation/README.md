# Framework Validation Prototype

验证 `agently-skills-runtime` v0.4.0 全部框架能力的交互式原型（FastAPI + SSE + 单文件 CDN React）。

## 目标

- 覆盖 **13 个能力**：`2 Skill + 9 Agent + 2 Workflow`
- 支持 **Mock（离线）** 与 **Real LLM（可选集成）**
- 可视化 Workflow DAG、实时事件流、最终输出

## 目录

```text
examples/00_prototype_validation/
├── server.py
├── specs.py
├── mock_adapter.py
├── llm_runner.py
├── instrumented.py
├── frontend/
│   └── index.html
├── requirements.txt
├── test_prototype.py
└── README.md
```

## 快速开始

```bash
# 在仓库根目录
pip install -e ".[dev]"
pip install -r examples/00_prototype_validation/requirements.txt

cd examples/00_prototype_validation
python server.py
```

浏览器访问：`http://localhost:8000`

## API

- `GET /`：返回前端页面
- `GET /api/capabilities`：13 能力注册表
- `GET /api/config`：当前模式与脱敏配置（不回显明文 `api_key`）
- `POST /api/config`：更新 `{base_url, api_key, model}`
- `POST /api/mode`：切换 `{mode: "mock" | "real"}`
- `POST /api/run`：触发 `{scenario: "neutral" | "critical" | "positive" | "custom", custom_input?}`
- `GET /api/run/{run_id}`：查询 run 状态
- `GET /api/run/{run_id}/events`：SSE 事件流（支持 `Last-Event-ID` 回放）

## Mock 验收清单

1. 默认模式为 `mock`
2. 运行 `neutral` 场景后，日志中可见：
   - `step_start`
   - `step_complete`
   - `loop_item`
   - `parallel_start`
   - `branch_complete`
   - `conditional_route`
   - `workflow_complete`
3. `final_report.overall_score == 6.5`

## Real LLM 使用

1. 切换到 `Real LLM Mode`
2. 配置 Base URL / API Key / Model
3. 点击 `Save Config`
4. 运行任意场景（输出内容可与 mock 不同，但 key 结构应保持一致）

## 离线测试

仓库级门禁：

```bash
PATH=.venv/bin:$PATH python -m pytest -q \
  tests/scenarios/test_prototype_validation_mock_pipeline.py \
  tests/scenarios/test_prototype_validation_injection_and_dispatch.py
```

原型目录自测：

```bash
PATH=.venv/bin:$PATH python -m pytest examples/00_prototype_validation/test_prototype.py -v
```

## 安全说明

- `POST /api/config` 可提交明文 `api_key`，仅保存在内存，不写入文件。
- `GET /api/config` 只返回 `api_key_present` 布尔值。
- SSE 事件会对常见敏感字段做脱敏处理。
