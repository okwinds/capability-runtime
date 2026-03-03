from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, Optional

import pytest

from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.ui_events.v1 import PathSegment, RuntimeEvent, StreamLevel


class _FakeRuntime:
    async def run_ui_events(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
        level: Any = None,
    ) -> AsyncIterator[Any]:
        _ = (capability_id, input, level)
        assert context is not None
        yield RuntimeEvent(
            schema="capability-runtime.runtime_event.v1",
            type="run.status",
            run_id=context.run_id,
            seq=1,
            ts_ms=0,
            level=StreamLevel.UI,
            path=[PathSegment(kind="run", id=context.run_id)],
            data={"status": "running"},
            rid="1",
            evidence=None,
        )
        await asyncio.sleep(0)
        yield RuntimeEvent(
            schema="capability-runtime.runtime_event.v1",
            type="run.status",
            run_id=context.run_id,
            seq=2,
            ts_ms=1,
            level=StreamLevel.UI,
            path=[PathSegment(kind="run", id=context.run_id)],
            data={"status": "completed"},
            rid="2",
            evidence=None,
        )


@pytest.mark.asyncio
async def test_ui_events_showcase_real_fallback_session_does_not_support_after_id() -> None:
    from examples.apps.ui_events_showcase.run import _RunUiEventsFallbackSession  # type: ignore

    rt = _FakeRuntime()
    sess = _RunUiEventsFallbackSession(
        runtime=rt,  # type: ignore[arg-type]
        capability_id="agent.any",
        input={},
        context=ExecutionContext(run_id="r1", max_depth=8),
        level=StreamLevel.UI,
    )

    out = [ev async for ev in sess.subscribe(after_id="2")]
    assert len(out) == 1
    assert out[0].type == "error"
    assert out[0].data.get("kind") == "after_id_unsupported"
    assert out[0].data.get("after_id") == "2"


@pytest.mark.asyncio
async def test_ui_events_showcase_real_fallback_session_streams_run_ui_events_when_no_after_id() -> None:
    from examples.apps.ui_events_showcase.run import _RunUiEventsFallbackSession  # type: ignore

    rt = _FakeRuntime()
    sess = _RunUiEventsFallbackSession(
        runtime=rt,  # type: ignore[arg-type]
        capability_id="agent.any",
        input={},
        context=ExecutionContext(run_id="r1", max_depth=8),
        level=StreamLevel.UI,
    )

    out = [ev async for ev in sess.subscribe(after_id=None)]
    assert [e.type for e in out] == ["run.status", "run.status"]
    assert out[-1].data.get("status") == "completed"
