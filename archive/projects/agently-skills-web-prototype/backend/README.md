# Backend（FastAPI）

> 说明：该后端用于“能力验证”，默认提供离线 demo（scripted LLM stream），不依赖外网。

## 运行

从仓库根目录开始（确保能 import `capability_runtime`）：

```bash
python -m pip install -e .
python -m pip install -e archive/projects/agently-skills-web-prototype/backend
uvicorn agently_skills_web_backend.app:app --reload --port 8000
```

## 测试

```bash
cd archive/projects/agently-skills-web-prototype/backend
python -m pytest -q
```

## RAG 教学模式（Host 侧）

### 1) pre-run 注入模式

```bash
curl -sS http://127.0.0.1:8000/api/runs/skill-task \
  -H 'Content-Type: application/json' \
  -d '{"task":"请解释 NodeReport 与 tool evidence 的关系","mode":"demo_rag_pre_run"}'
```

预期：
- run 完成后，`node_report.meta.rag.mode == "pre_run"`；
- `meta.rag` 只包含 `query_sha256/top_k/chunks(doc_id/source/score/hash/len)`。

### 2) tool 检索模式

```bash
curl -sS http://127.0.0.1:8000/api/runs/skill-task \
  -H 'Content-Type: application/json' \
  -d '{"task":"请演示 tool 检索闭环","mode":"demo_rag_tool"}'
```

预期：
- run 完成后，`node_report.meta.rag.mode == "tool"`；
- `node_report.tool_calls` 中包含 `rag_retrieve` 证据。

## 安全说明（默认最小披露）

- `NodeReport.meta.rag` 不记录 raw `query`，仅记录 `query_sha256`。
- `NodeReport.meta.rag` 不记录 raw chunk `content`，仅记录 `content_sha256/content_len` 等摘要。
- `rag_retrieve` 工具默认返回脱敏结果；只有显式传入 `include_content=true` 才返回内容。
