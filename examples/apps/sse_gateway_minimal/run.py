from __future__ import annotations

"""
sse_gateway_minimal：HTTP/SSE 小服务（最小可运行）。

约束：
- 不新增第三方依赖（仅使用 Python 标准库）
- 双模式：
  - offline：FakeChatBackend 驱动真实 SDK agent loop（可回归）
  - real：真模型（OpenAI-compatible，经 Agently requester 作为传输层）
"""

import argparse
import asyncio
import json
import queue
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext, Runtime

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.apps._shared.app_support import (  # noqa: E402
    AutoApprovalProvider,
    ScriptedApprovalProvider,
    build_evidence_strict_output_validator,
    build_bridge_runtime_from_env,
    env_or_default,
    load_env_file,
    write_overlay_for_app,
)


def _build_offline_backend(*, report_md: str) -> FakeChatBackend:
    """离线 Fake backend：update_plan → file_write(report.md) → done。"""

    plan = {
        "explanation": "SSE demo：生成报告",
        "plan": [
            {"step": "生成报告", "status": "in_progress"},
            {"step": "完成", "status": "pending"},
        ],
    }
    plan_done = {
        "explanation": "SSE demo：完成",
        "plan": [
            {"step": "生成报告", "status": "completed"},
            {"step": "完成", "status": "completed"},
        ],
    }

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="p1", name="update_plan", args=plan),
                            LlmToolCall(call_id="w1", name="file_write", args={"path": "report.md", "content": report_md}),
                            LlmToolCall(call_id="p2", name="update_plan", args=plan_done),
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def _register_capability(runtime: Runtime) -> None:
    """注册 SSE demo 的 Agent 能力（skills-first）。"""

    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="app.sse_gateway_minimal",
                kind=CapabilityKind.AGENT,
                name="SseGatewayMinimal",
                description="\n".join(
                    [
                        "你是一个 SSE 网关示例节点。",
                        "必须使用工具完成：update_plan → file_write(report.md) → update_plan。",
                        "最后输出一句简短确认信息。",
                    ]
                ),
            ),
            skills=["sse-reporter"],
            system_prompt="\n".join(
                [
                    "严格按以下清单完成：",
                    "1) update_plan 标注开始",
                    "2) file_write 写出 report.md（包含 topic 与产物清单）",
                    "3) update_plan 标注完成",
                    "4) 最终输出一句简短确认（例如 ok）",
                ]
            ),
        )
    )


class _RunHandle:
    """一次 run 的 in-memory handle（供 SSE 订阅）。"""

    def __init__(self) -> None:
        self.q: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()
        self.done = False


class _AppState:
    """服务端全局状态（线程安全：用 GIL + Queue 即可）。"""

    def __init__(self, runtime: Runtime, strict_runtime: Runtime, workspace_root: Path) -> None:
        self.runtime = runtime
        self.strict_runtime = strict_runtime
        self.workspace_root = workspace_root
        self.runs: Dict[str, _RunHandle] = {}

    def start_run(self, *, topic: str, evidence_strict: bool) -> str:
        run_id = uuid.uuid4().hex
        h = _RunHandle()
        self.runs[run_id] = h

        def _worker() -> None:
            # 说明：
            # - LoopStep 的熔断守卫由 Runtime 在 run/run_stream 内部统一注入（context.guards 为空时会填充默认值）；
            # - app 示例只固定 run_id / bag，避免依赖内部实现类型（单一公共入口：包根 API）。
            ctx = ExecutionContext(run_id=run_id, max_depth=10, bag={"evidence_strict": bool(evidence_strict)})
            runtime = self.strict_runtime if evidence_strict else self.runtime

            async def _async_worker() -> None:
                try:
                    async for item in runtime.run_stream(
                        "app.sse_gateway_minimal",
                        input={"topic": topic},
                        context=ctx,
                    ):
                        if isinstance(item, AgentEvent):
                            h.q.put({"type": "event", "event": item.model_dump() if hasattr(item, "model_dump") else item.__dict__})
                        else:
                            wal_locator = str(item.node_report.events_path) if item.node_report and item.node_report.events_path else None
                            terminal_payload = {
                                "type": "terminal",
                                "status": item.status.value,
                                "output": item.output,
                                "wal_locator": wal_locator,
                            }

                            # 兜底：服务端示例不适合交互审批，且不同真实模型可能不稳定地产生 report.md。
                            # 为保证“像小服务一样跑起来”的最小体验，这里对 report.md 做 host fallback：
                            # - 仅当 report.md 缺失时写入；
                            # - 报告中显式标注为 host fallback（避免与模型产物混淆）。
                            # evidence-strict 下必须禁用 fallback，并在缺失 `file_write(report.md)` evidence 时 fail-closed。
                            report_path = self.workspace_root / "report.md"
                            has_report_evidence = False
                            if item.node_report is not None:
                                for t in item.node_report.tool_calls or []:
                                    if t.name != "file_write" or t.ok is not True or not isinstance(t.data, dict):
                                        continue
                                    if str(t.data.get("path") or "") == "report.md":
                                        has_report_evidence = True
                                        break
                                # evidence-strict：把 Runtime 的 output_validation 摘要一并暴露到 SSE terminal（便于教学与验收）。
                                # 注意：这里只透出“最小披露摘要”，不包含 tool 输出明文。
                                if evidence_strict:
                                    ov = (item.node_report.meta or {}).get("output_validation")
                                    if isinstance(ov, dict):
                                        terminal_payload["output_validation"] = ov

                            if evidence_strict and (not has_report_evidence):
                                terminal_payload["status"] = "failed"
                                terminal_payload["error"] = "evidence_strict: missing file_write(report.md) evidence"
                            elif wal_locator and (not report_path.exists()):
                                report_md = "\n".join(
                                    [
                                        "# SSE Gateway Report",
                                        "",
                                        "> 注：本报告由 host fallback 生成（模型未按契约落盘 report.md）。",
                                        "",
                                        f"- run_id: {run_id}",
                                        f"- topic: {topic}",
                                        "",
                                        "## 产物",
                                        "- report.md",
                                        "",
                                        "## 证据链指针",
                                        f"- wal_locator/events_path: {wal_locator}",
                                        "",
                                    ]
                                )
                                report_path.write_text(report_md + "\n", encoding="utf-8")

                            h.q.put(terminal_payload)
                except Exception as exc:
                    h.q.put({"type": "terminal", "status": "failed", "output": "", "error": str(exc), "wal_locator": None})
                finally:
                    h.done = True
                    h.q.put(None)

            asyncio.run(_async_worker())

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return run_id


class Handler(BaseHTTPRequestHandler):
    """HTTP handler：start + SSE events。"""

    server_version = "asr-sse/0.1"

    def _json(self, status: int, obj: Dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            text = (
                "sse_gateway_minimal\\n\\n"
                "GET /start?topic=... -> {run_id}\\n"
                "GET /events?run_id=... -> SSE stream\\n"
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            self.wfile.write(text)
            return

        if parsed.path == "/start":
            qs = parse_qs(parsed.query)
            topic = (qs.get("topic") or ["为什么证据链重要？"])[0]
            evidence_strict = (qs.get("evidence_strict") or qs.get("strict") or ["0"])[0] in {"1", "true", "yes"}
            st: _AppState = self.server.app_state  # type: ignore[attr-defined]
            run_id = st.start_run(topic=topic, evidence_strict=bool(evidence_strict))
            self._json(HTTPStatus.OK, {"run_id": run_id})
            return

        if parsed.path == "/events":
            qs = parse_qs(parsed.query)
            run_id = (qs.get("run_id") or [""])[0]
            st: _AppState = self.server.app_state  # type: ignore[attr-defined]
            h = st.runs.get(run_id)
            if h is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "run_id not found"})
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            # 简单 SSE：每条消息一条 data JSON
            while True:
                item = h.q.get()
                if item is None:
                    break
                payload = json.dumps(item, ensure_ascii=False)
                chunk = f"data: {payload}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # 保持示例输出干净：默认不打 access log
        _ = (format, args)

def create_server(
    *,
    host: str,
    port: int,
    mode: str,
    workspace_root: Path,
) -> ThreadingHTTPServer:
    """
    创建 HTTP/SSE 服务实例（便于测试与嵌入式运行）。

    参数：
    - host/port：监听地址
    - mode：offline|real
    - workspace_root：工作区根目录

    返回：
    - ThreadingHTTPServer（已绑定 app_state，但未启动 serve_forever）
    """

    app_dir = Path(__file__).resolve().parent
    skills_root = (app_dir / "skills").resolve()

    if mode == "real":
        dotenv_path = app_dir / ".env"
        if dotenv_path.exists():
            load_env_file(dotenv_path)

    safety_mode = "allow" if mode == "real" else "ask"
    overlay = write_overlay_for_app(
        workspace_root=workspace_root,
        skills_root=skills_root,
        max_steps=80,
        safety_mode=safety_mode,
        planner_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if mode == "real" else None,
        executor_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if mode == "real" else None,
    )

    report_md = "\n".join(
        [
            "# SSE Report",
            "",
            f"- ts: {time.time()}",
            "- outputs: report.md",
            "",
        ]
    )

    sdk_backend = _build_offline_backend(report_md=report_md) if mode == "offline" else None
    approval_provider = (
        ScriptedApprovalProvider(decisions=[ApprovalDecision.APPROVED_FOR_SESSION])
        if mode == "offline"
        else AutoApprovalProvider()
    )

    runtime = build_bridge_runtime_from_env(
        workspace_root=workspace_root,
        overlay=overlay,
        sdk_backend=sdk_backend,
        approval_provider=approval_provider,
        human_io=None,
    )
    _register_capability(runtime)
    assert runtime.validate() == []

    # strict runtime：以 RuntimeConfig.output_validator(mode=error) 写入 NodeReport.meta.output_validation，
    # 并在缺失关键 tool evidence 时 fail-closed（与终端 app 的 strict 口径一致）。
    strict_runtime = build_bridge_runtime_from_env(
        workspace_root=workspace_root,
        overlay=overlay,
        sdk_backend=sdk_backend,
        approval_provider=approval_provider,
        human_io=None,
        output_validation_mode="error",
        output_validator=build_evidence_strict_output_validator(
            schema_id="examples.sse_gateway_minimal.evidence_strict.v1",
            require_file_writes=["report.md"],
            require_tools_ok=[],
        ),
    )
    _register_capability(strict_runtime)
    assert strict_runtime.validate() == []

    st = _AppState(runtime=runtime, strict_runtime=strict_runtime, workspace_root=workspace_root)
    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    httpd.app_state = st  # type: ignore[attr-defined]
    return httpd


def main() -> int:
    parser = argparse.ArgumentParser(description="sse_gateway_minimal (offline/real)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--mode", choices=["offline", "real"], default="offline")
    parser.add_argument("--workspace-root", default=".")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    try:
        httpd = create_server(
            host=str(args.host),
            port=int(args.port),
            mode=str(args.mode),
            workspace_root=workspace_root,
        )
    except Exception as exc:
        print("=== sse_gateway_minimal ===")
        print("缺少真实模型配置，已退出（exit code 0）。")
        print("请准备：examples/apps/sse_gateway_minimal/.env")
        print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
        print(f"error={type(exc).__name__}: {exc}")
        return 0

    print(f"[sse] listening on http://{args.host}:{args.port}")
    print("[sse] endpoints: /start  /events?run_id=...")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
