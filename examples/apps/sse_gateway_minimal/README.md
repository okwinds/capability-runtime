# sse_gateway_minimal（HTTP/SSE 小服务 / skills-first）

目标：提供一个最小可跑的 HTTP/SSE 服务形态，让人直观看到：
- 事件流（SSE）如何转发执行过程（skills/tool/approval）
- 终态如何返回 `output` 与 `wal_locator`（NodeReport.events_path）
- 同时支持 `offline/real` 双模式

## 1) 离线运行（默认）

```bash
python examples/apps/sse_gateway_minimal/run.py --host 127.0.0.1 --port 8787 --mode offline --workspace-root /tmp/caprt-sse
```

启动后：
- 访问 `http://127.0.0.1:8787/` 查看说明
- 访问 `http://127.0.0.1:8787/start` 启动一次 run（返回 run_id）
- 访问 `http://127.0.0.1:8787/events?run_id=<id>` 以 SSE 订阅事件流

## 2) 真模型运行（OpenAI-compatible）

准备 `.env`（仅本地使用，不入库）：

```bash
cp examples/apps/sse_gateway_minimal/.env.example examples/apps/sse_gateway_minimal/.env
```

运行：

```bash
python examples/apps/sse_gateway_minimal/run.py --host 127.0.0.1 --port 8787 --mode real --workspace-root /tmp/caprt-sse
```

说明：
- SSE 服务形态下不适合等待终端交互审批；本示例在 real 模式使用自动审批（仅限示例目录），避免阻塞。
- 每次 `/start` 的一次 run 预期在 workspace 根目录写出 `report.md`，并在 SSE 终态事件里返回 `wal_locator`。

## 3) evidence-strict（证据严格模式：禁止 host fallback）

通过 query 参数开启 strict：

```bash
curl "http://127.0.0.1:8787/start?topic=hello&evidence_strict=1"
```

行为差异：
- 非 strict：若模型未按契约 `file_write(report.md)`，服务端会生成一份 **host fallback** 报告（并在内容中显式标注）。
- strict：禁用 host fallback；若缺失 `file_write(report.md)` 的 tool evidence，SSE 终态事件会 `status=failed` 且包含 `error` 字段。
