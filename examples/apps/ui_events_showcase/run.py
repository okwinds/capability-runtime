from __future__ import annotations

"""
ui_events_showcase：Runtime UI Events v1 展示小应用（offline-first）。

约束：
- 不新增第三方依赖（仅标准库）
- 默认 offline fixtures 回放
- real 模式（可选集成）门禁：未显式开启时不得触达 provider/init/.env
"""

import argparse
import asyncio
import json
import os
import queue
import sys
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
for p in (REPO_ROOT, SRC_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from capability_runtime.ui_events.transport import encode_json_line
from capability_runtime.ui_events.v1 import Evidence, PathSegment, RuntimeEvent, StreamLevel

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime
from examples.apps._shared.app_support import AutoApprovalProvider, build_bridge_runtime_from_env, load_env_file, write_overlay_for_app


def _load_dotenv_for_real(app_dir: Path) -> None:
    """
    real 模式的 .env 读取（后续切片用）。

    注意：本切片只提供函数占位；门禁关闭时不得调用它（测试会打桩验证）。
    """

    dotenv_path = app_dir / ".env"
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _init_real_provider() -> None:
    """
    real 模式 provider 初始化（后续切片实现）。

    注意：本切片不实现真实 provider；门禁开启后如果走到这里，应显式报错提示尚未实现。
    """

    # provider 初始化通过 `build_bridge_runtime_from_env` 完成（这里仅保留占位，供测试打桩验证 fail-closed）。
    return None


def _stream_level_rank(level: StreamLevel) -> int:
    if level == StreamLevel.LITE:
        return 0
    if level == StreamLevel.UI:
        return 1
    return 2


def _parse_level(s: str) -> StreamLevel:
    try:
        return StreamLevel(s)
    except Exception:
        return StreamLevel.UI


def _read_fixture_events(fixtures_path: Path) -> List[RuntimeEvent]:
    events: List[RuntimeEvent] = []
    for line in fixtures_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(RuntimeEvent.model_validate_json(line))
    return events


class _AsyncLoopThread:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._t = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def start(self) -> None:
        if self._t is not None:
            return

        def _run() -> None:
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        import threading

        self._t = threading.Thread(target=_run, name="ui-events-async-loop", daemon=True)
        self._t.start()

    def submit(self, coro: Any) -> "asyncio.Future[Any]":
        self.start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[return-value]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_after_id_error_event(*, run_id: str, level: StreamLevel, after_id: str, known_min_id: Optional[str], known_max_id: Optional[str]) -> RuntimeEvent:
    msg = f"after_id expired or not found: {after_id!r} (available: {known_min_id!r}..{known_max_id!r})"
    return RuntimeEvent(
        schema="capability-runtime.runtime_event.v1",
        type="error",
        run_id=str(run_id),
        seq=0,
        ts_ms=_now_ms(),
        level=level,
        path=[PathSegment(kind="run", id=str(run_id))],
        data={"kind": "after_id_expired", "message": msg, "known_min_id": known_min_id, "known_max_id": known_max_id},
        rid="err_" + uuid.uuid4().hex[:12],
        evidence=None,
    )


class _OfflineSession:
    def __init__(self, *, session_id: str, run_id: str, level: StreamLevel, events: List[RuntimeEvent]) -> None:
        self.session_id = session_id
        self.run_id = run_id
        self.level = level
        self.events = events
        self._rid_to_idx: Dict[str, int] = {}
        for i, ev in enumerate(events):
            if ev.rid:
                self._rid_to_idx[str(ev.rid)] = i

    def min_rid(self) -> Optional[str]:
        rids = [ev.rid for ev in self.events if ev.rid]
        return str(rids[0]) if rids else None

    def max_rid(self) -> Optional[str]:
        rids = [ev.rid for ev in self.events if ev.rid]
        return str(rids[-1]) if rids else None

    def iter_after(self, *, after_id: Optional[str]) -> List[RuntimeEvent]:
        if not after_id:
            return list(self.events)
        idx = self._rid_to_idx.get(str(after_id))
        if idx is None:
            return [
                _make_after_id_error_event(
                    run_id=self.run_id,
                    level=self.level,
                    after_id=str(after_id),
                    known_min_id=self.min_rid(),
                    known_max_id=self.max_rid(),
                )
            ]
        return list(self.events[idx + 1 :])


class _AppState:
    def __init__(self, *, app_dir: Path) -> None:
        self.app_dir = app_dir
        self.ui_dir = app_dir / "ui"
        self.fixtures_path = app_dir / "fixtures" / "demo.jsonl"
        self._fixture_events = _read_fixture_events(self.fixtures_path)
        self.sessions: Dict[str, Any] = {}
        self.loop_thread = _AsyncLoopThread()
        self._skills_root = (self.app_dir / "skills").resolve()
        self._skills_root.mkdir(parents=True, exist_ok=True)

    def new_offline_session(self, *, level: StreamLevel) -> _OfflineSession:
        session_id = "sess_" + uuid.uuid4().hex
        run_id = self._fixture_events[0].run_id if self._fixture_events else ("run_" + uuid.uuid4().hex)

        # level filtering: requested level is the max allowed detail; fixtures are typically UI.
        want_rank = _stream_level_rank(level)
        filtered = [ev for ev in self._fixture_events if _stream_level_rank(ev.level) <= want_rank]

        s = _OfflineSession(session_id=session_id, run_id=str(run_id), level=level, events=filtered)
        self.sessions[session_id] = s
        return s

    def new_real_session(self, *, level: StreamLevel, workspace_root: Path) -> Any:
        session_id = "sess_" + uuid.uuid4().hex
        app_dir = self.app_dir

        dotenv_path = app_dir / ".env"
        if not dotenv_path.exists():
            raise RuntimeError("missing .env for real mode (cp .env.example .env)")

        load_env_file(dotenv_path)
        required = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME")
        missing = [k for k in required if not str(os.environ.get(k, "")).strip()]
        if missing:
            raise RuntimeError("missing env vars for real mode: " + ", ".join(missing))

        # workspace：每次 session 独立目录，避免相互污染
        ws = (workspace_root / "ui_events_showcase" / session_id).resolve()
        ws.mkdir(parents=True, exist_ok=True)

        overlay = write_overlay_for_app(
            workspace_root=ws,
            skills_root=self._skills_root,
            max_steps=6,
            safety_mode="allow",
            tool_allowlist=["read_file", "grep_files", "list_dir", "file_read", "update_plan", "file_write", "apply_patch", "shell_exec"],
            account="examples",
            domain="ui-events-showcase",
        )

        runtime = build_bridge_runtime_from_env(
            workspace_root=ws,
            overlay=overlay,
            approval_provider=AutoApprovalProvider(),
            human_io=None,
        )

        cap_id = "agent.ui_events_showcase.real"
        runtime.register(
            AgentSpec(
                base=CapabilitySpec(
                    id=cap_id,
                    kind=CapabilityKind.AGENT,
                    name="UI Events Showcase (Real)",
                    description="用于展示 Runtime UI Events v1（real mode）。",
                ),
                system_prompt="你是一个演示 Agent。严禁输出任何 `$[...]` mention；严禁调用任何工具。",
                prompt_template="请用简体中文用 2-3 句话解释：{topic}",
            )
        )
        errs = runtime.validate()
        if errs:
            raise RuntimeError("runtime.validate failed: " + str(errs))

        session = runtime.start_ui_events_session(cap_id, input={"topic": "Capability Runtime 的 UI Events v1 是什么？"}, level=level)
        out = {"kind": "real", "session_id": session_id, "runtime": runtime, "session": session, "level": level, "run_id": session.run_id}
        self.sessions[session_id] = out
        return out


class Handler(BaseHTTPRequestHandler):
    server_version = "caprt-ui-events/0.1"

    def _json(self, status: int, obj: Dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_app_state(self) -> _AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    def _serve_static(self, *, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return

        if file_path.suffix == ".html":
            ct = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            ct = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            ct = "text/javascript; charset=utf-8"
        else:
            ct = "application/octet-stream"

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/start":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        qs = parse_qs(parsed.query)
        mode = (qs.get("mode") or ["offline"])[0]
        level_s = (qs.get("level") or ["ui"])[0]
        level = _parse_level(str(level_s))

        if mode == "real" and os.environ.get("CAPRT_TEST_E2E_BRIDGE") != "1":
            self._json(HTTPStatus.FORBIDDEN, {"error": "real mode is gated: set CAPRT_TEST_E2E_BRIDGE=1"})
            return

        if mode == "real":
            st = self._read_app_state()
            try:
                _load_dotenv_for_real(st.app_dir)
                _init_real_provider()
                sess = st.new_real_session(level=level, workspace_root=getattr(self.server, "workspace_root"))  # type: ignore[attr-defined]
            except RuntimeError as exc:
                self._json(HTTPStatus.PRECONDITION_FAILED, {"error": str(exc)})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "session_id": sess["session_id"],
                    "run_id": str(sess["run_id"]),
                    "mode": "real",
                    "level": level.value,
                },
            )
            return

        st = self._read_app_state()
        s = st.new_offline_session(level=level)
        self._json(
            HTTPStatus.OK,
            {"session_id": s.session_id, "run_id": s.run_id, "mode": "offline", "level": level.value},
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/":
            st = self._read_app_state()
            self._serve_static(file_path=st.ui_dir / "index.html")
            return

        if parsed.path.startswith("/ui/"):
            st = self._read_app_state()
            rel = parsed.path[len("/ui/") :]
            # 简单防穿越：只允许同目录文件
            if "/" in rel or "\\" in rel or ".." in rel:
                self.send_error(HTTPStatus.BAD_REQUEST, "bad path")
                return
            self._serve_static(file_path=st.ui_dir / rel)
            return

        if parsed.path == "/api/events":
            qs = parse_qs(parsed.query)
            session_id = (qs.get("session_id") or [""])[0]
            transport = (qs.get("transport") or ["sse"])[0]
            after_id = (qs.get("after_id") or [None])[0]

            st = self._read_app_state()
            sess = st.sessions.get(str(session_id))
            if sess is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "session_id not found"})
                return

            events_iter: Iterable[RuntimeEvent]
            if isinstance(sess, _OfflineSession):
                events_iter = sess.iter_after(after_id=str(after_id) if after_id else None)
            else:
                # real session（RuntimeUIEventsSession）：用 async subscribe 输出
                session = sess["session"]

                q_out: "queue.Queue[Optional[RuntimeEvent]]" = queue.Queue()

                async def _produce() -> None:
                    try:
                        async for ev in session.subscribe(after_id=str(after_id) if after_id else None):
                            q_out.put(ev)
                    finally:
                        q_out.put(None)

                st.loop_thread.submit(_produce())

                def _iter() -> Iterator[RuntimeEvent]:
                    while True:
                        ev = q_out.get()
                        if ev is None:
                            return
                        yield ev

                events_iter = _iter()

            if transport == "jsonl":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for ev in events_iter:
                    try:
                        chunk = encode_json_line(ev, prefix_data=False).encode("utf-8")
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                return

            # default: SSE subset
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            for ev in events_iter:
                try:
                    chunk = encode_json_line(ev, prefix_data=True).encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except BrokenPipeError:
                    return
                # 轻微 pacing，避免某些客户端一次性吞完后 UI 无感
                time.sleep(0.01)
                if ev.type == "run.status" and ev.data.get("status") != "running":
                    # 终态后留一点时间给客户端关闭连接，避免误判为“断线”
                    time.sleep(0.3)
                    return
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        _ = (format, args)


def create_server(*, host: str, port: int, mode: str, workspace_root: Path) -> ThreadingHTTPServer:
    """
    创建 server（便于 pytest 直接启动，不需要子进程）。

    参数保持与其它 examples/apps 一致（mode/workspace_root 暂用于兼容形态）。
    """

    _ = mode
    app_dir = Path(__file__).resolve().parent
    st = _AppState(app_dir=app_dir)
    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    httpd.app_state = st  # type: ignore[attr-defined]
    httpd.workspace_root = workspace_root  # type: ignore[attr-defined]
    return httpd


def main() -> int:
    parser = argparse.ArgumentParser(description="ui_events_showcase (offline-first)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--mode", choices=["offline", "real"], default="offline")
    parser.add_argument("--workspace-root", default=".")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    httpd = create_server(host=str(args.host), port=int(args.port), mode=str(args.mode), workspace_root=workspace_root)
    print(f"[ui-events] listening on http://{args.host}:{args.port}")
    print("[ui-events] endpoints: POST /api/start  GET /api/events?session_id=...  / (UI)")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
