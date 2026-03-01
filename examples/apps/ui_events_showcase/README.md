# UI Events Showcase（offline-first）

一个最小可运行的人类 Web app，用于展示 **Runtime UI Events v1** 的消费方式：

- 左侧：Workflow 树（按 `RuntimeEvent.path` 投影）
- 中间：Chat/过程文本
- 右侧：事件与证据抽屉（`evidence.events_path` 等指针）

## 运行（离线）

```bash
python examples/apps/ui_events_showcase/run.py --mode offline
```

打开浏览器访问：

- `http://127.0.0.1:8789/`

## API

- `POST /api/start?mode=offline&level=ui` → `{session_id, run_id, mode, level}`
- `GET /api/events?session_id=...&transport=sse[&after_id=...]`
- `GET /api/events?session_id=...&transport=jsonl[&after_id=...]`

## Real 模式（本切片仅门禁 fail-closed）

本切片不实现真实 provider；当请求 `mode=real` 且环境变量 `CAPRT_TEST_E2E_BRIDGE != "1"` 时：

- `/api/start` 必须返回 403
- 且不会触发 `.env` 读取或 provider 初始化

后续切片将把 real 模式接到 Bridge E2E（读取 `.env`：`OPENAI_API_KEY/OPENAI_BASE_URL/MODEL_NAME`）。

