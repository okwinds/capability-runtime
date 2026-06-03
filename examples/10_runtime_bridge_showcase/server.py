from __future__ import annotations

"""Runtime bridge live showcase server.

The server reads provider configuration from process environment variables and
never exposes secrets to the browser. It calls the real Runtime bridge for both
chat_completions and responses, then returns sanitized model output and usage
evidence.
"""

import argparse
import asyncio
import html
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    Runtime,
    RuntimeConfig,
    build_openai_provider_requester_factory,
)


REQUIRED = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME")
_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}


def _missing_env() -> list[str]:
    return [key for key in REQUIRED if not os.getenv(key)]


def _html_page() -> bytes:
    model = html.escape(os.getenv("MODEL_NAME", "not configured"))
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Runtime Bridge Live Showcase</title>
    <style>
      :root {{
        --bg: #f7f8fa;
        --panel: #ffffff;
        --ink: #20242c;
        --muted: #5f6978;
        --line: #d8dde6;
        --accent: #0b6e4f;
        --accent-2: #375a7f;
        --code: #111827;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--ink);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        letter-spacing: 0;
      }}
      header {{
        padding: 28px 32px 20px;
        border-bottom: 1px solid var(--line);
        background: var(--panel);
      }}
      h1 {{ margin: 0 0 8px; font-size: 28px; line-height: 1.2; }}
      header p {{ margin: 0; max-width: 980px; color: var(--muted); line-height: 1.55; }}
      main {{ padding: 24px 32px 40px; max-width: 1280px; }}
      .summary {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin-bottom: 20px;
      }}
      .metric, section {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
      }}
      .metric {{ padding: 14px 16px; }}
      .metric strong {{ display: block; font-size: 20px; margin-bottom: 4px; }}
      .metric span {{ color: var(--muted); font-size: 13px; }}
      section {{ margin: 14px 0; padding: 18px; }}
      h2 {{ margin: 0 0 10px; font-size: 18px; }}
      .grid {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 14px;
      }}
      .pill {{
        display: inline-flex;
        align-items: center;
        min-height: 26px;
        padding: 3px 9px;
        border-radius: 999px;
        background: #e7f4ef;
        color: var(--accent);
        font-size: 12px;
        font-weight: 700;
        margin: 0 6px 8px 0;
      }}
      .pill.blue {{ background: #e7eef7; color: var(--accent-2); }}
      pre {{
        margin: 10px 0 0;
        padding: 14px;
        overflow: auto;
        background: var(--code);
        color: #e5edf6;
        border-radius: 8px;
        font-size: 13px;
        line-height: 1.5;
        min-height: 120px;
      }}
      button {{
        border: 1px solid var(--accent);
        background: var(--accent);
        color: white;
        border-radius: 6px;
        padding: 8px 12px;
        font-weight: 700;
        cursor: pointer;
      }}
      .error {{ color: #a33131; }}
      ul {{ margin: 8px 0 0; padding-left: 18px; color: var(--muted); line-height: 1.55; }}
      @media (max-width: 820px) {{
        header, main {{ padding-left: 16px; padding-right: 16px; }}
        .grid {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <header>
      <h1>Runtime Bridge Live Showcase</h1>
      <p>
        页面由服务器调用真实 provider，展示 capability-runtime bridge 返回的模型文本、
        NodeReport usage.model、request id 与 provider 证据。密钥只存在服务端环境变量中，不发给浏览器。
      </p>
    </header>
    <main>
      <div class="summary">
        <div class="metric"><strong>目标模型</strong><span>{model}</span></div>
        <div class="metric"><strong>chat_completions</strong><span>默认 requester，legacy 不破</span></div>
        <div class="metric"><strong>responses</strong><span>显式 opt-in requester</span></div>
        <div class="metric"><strong>live evidence</strong><span>页面加载时真实调用</span></div>
      </div>

      <section>
        <h2>真实模型反馈</h2>
        <span class="pill">Runtime bridge</span>
        <span class="pill blue">NodeReport evidence</span>
        <button id="run">重新调用真实模型</button>
        <div class="grid">
          <div>
            <strong>Chat Completions</strong>
            <pre id="chat">等待调用...</pre>
          </div>
          <div>
            <strong>Responses</strong>
            <pre id="responses">等待调用...</pre>
          </div>
        </div>
      </section>

      <section>
        <h2>新能力 Preview</h2>
        <ul>
          <li>Dynamic DAG：TaskDAG-like mapping 编译为 DynamicWorkflowPlan，节点通过 Runtime.run() 执行。</li>
          <li>Workflow lifecycle：新增 lifecycle_state / execution_id / state_version / close_reason，旧事件 additive 兼容。</li>
          <li>Workspace/Recall：只暴露 neutral context pack，不替代 WAL / NodeReport。</li>
          <li>Action artifact：只暴露 runtime artifact reference 摘要，不读取 raw artifact body。</li>
        </ul>
      </section>
    </main>
    <script>
      async function runLive() {{
        const chat = document.getElementById("chat");
        const responses = document.getElementById("responses");
        chat.textContent = "正在调用真实 chat_completions...";
        responses.textContent = "正在调用真实 responses...";
        try {{
          const res = await fetch("/api/live", {{ cache: "no-store" }});
          const payload = await res.json();
          if (!payload.ok) {{
            const message = payload.error || "unknown error";
            chat.textContent = message;
            responses.textContent = message;
            chat.className = "error";
            responses.className = "error";
            return;
          }}
          chat.className = "";
          responses.className = "";
          chat.textContent = JSON.stringify(payload.chat_completions, null, 2);
          responses.textContent = JSON.stringify(payload.responses, null, 2);
        }} catch (err) {{
          chat.textContent = String(err);
          responses.textContent = String(err);
          chat.className = "error";
          responses.className = "error";
        }}
      }}
      document.getElementById("run").addEventListener("click", runLive);
      runLive();
    </script>
  </body>
</html>
""".encode("utf-8")


async def _run_strategy(strategy: str, prompt: str) -> dict[str, Any]:
    provider_requester_factory = build_openai_provider_requester_factory(
        base_url=os.environ["OPENAI_BASE_URL"],
        transport_model=os.environ["MODEL_NAME"],
        api_key=os.environ["OPENAI_API_KEY"],
        strategy=strategy,  # type: ignore[arg-type]
        allow_insecure_transport=os.getenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT") == "1",
    )
    runtime = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=Path.cwd(),
            preflight_mode="off",
            provider_requester_factory=provider_requester_factory,
            requester_strategy=strategy,
        )
    )
    capability_id = f"agent.showcase.{strategy}"
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id=capability_id,
                kind=CapabilityKind.AGENT,
                name=f"Showcase{strategy}",
                description=prompt,
            ),
            llm_config={"model": os.environ["MODEL_NAME"]},
        )
    )
    result = await runtime.run(capability_id, input={"prompt": prompt})
    usage = result.node_report.usage if result.node_report is not None else None
    return {
        "status": result.status.value,
        "model_feedback": str(result.output),
        "has_node_report": result.node_report is not None,
        "usage_model": getattr(usage, "model", None),
        "usage_total_tokens": getattr(usage, "total_tokens", None),
        "request_id_present": bool(getattr(usage, "request_id", None)),
        "provider": getattr(usage, "provider", None),
        "provider_transport": getattr(usage, "provider_transport", None),
    }


async def _run_live() -> dict[str, Any]:
    missing = _missing_env()
    if missing:
        return {"ok": False, "error": f"server missing env: {', '.join(missing)}"}
    chat_prompt = "用一句中文说明 capability-runtime 的 chat bridge 已接通，必须包含 live-chat-ok。"
    responses_prompt = (
        "用一句中文说明 Responses bridge 是显式 opt-in，必须包含 live-responses-ok。"
    )
    chat, responses = await asyncio.gather(
        _run_strategy("chat_completions", chat_prompt),
        _run_strategy("responses", responses_prompt),
    )
    return {
        "ok": True,
        "generated_at": int(time.time()),
        "chat_completions": chat,
        "responses": responses,
    }


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("cache-control", "no-store")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class ShowcaseHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write("showcase: " + format % args + "\n")

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = _html_page()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/live"):
            now = time.time()
            if _CACHE["payload"] is not None and now < float(_CACHE["expires_at"]):
                _json_response(self, 200, _CACHE["payload"])
                return
            try:
                payload = asyncio.run(_run_live())
            except Exception as exc:
                sys.stderr.write(f"showcase live provider error: {type(exc).__name__}: {exc}\n")
                payload = {
                    "ok": False,
                    "error_code": "LIVE_PROVIDER_ERROR",
                    "error": "live provider request failed; check server logs",
                }
            if payload.get("ok"):
                _CACHE.update({"payload": payload, "expires_at": now + 20})
            _json_response(self, 200 if payload.get("ok") else 500, payload)
            return
        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ShowcaseHandler)
    print(f"serving http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
