"""
Host 侧 RAG 教学参考实现（in-memory provider + pre-run/tool 两种模式）。

约束：
- Bridge core 不负责检索，所有 RAG 能力放在 Host（archive reference app）；
- `meta.rag` 默认最小披露：不记录 query 原文、不记录 chunk content 原文；
- tool `rag_retrieve` 默认返回脱敏结果，仅在显式参数开启时返回内容。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from skills_runtime.tools.protocol import ToolCall, ToolResult, ToolSpec
from skills_runtime.tools.registry import ToolExecutionContext


RAG_DEMO_TOOL_QUERY = "节点报告 tool 证据链"


def _sha256_text(text: str) -> str:
    """计算文本 sha256（用于可审计摘要，避免记录明文）。"""

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _tokenize(text: str) -> List[str]:
    """
    对文本做轻量切分（英文词 + 中文单字）。

    说明：
    - 教学实现只追求稳定、可复刻，不追求检索效果最优；
    - 中文采用单字切分，避免依赖第三方分词库。
    """

    if not text:
        return []
    tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    return [tok for tok in tokens if tok.strip()]


def _content_digest(content: Optional[str]) -> Tuple[Optional[str], int]:
    """返回内容摘要 `(content_sha256, content_len)`。"""

    if not isinstance(content, str):
        return None, 0
    return _sha256_text(content), len(content)


@dataclass(frozen=True)
class RagChunk:
    """
    RAG 检索分片。

    字段：
    - `content` 为可选明文；默认建议仅在注入消息或显式授权时使用。
    """

    doc_id: str
    source: Optional[str]
    score: float
    content: Optional[str]
    content_sha256: Optional[str]
    content_len: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RagResult:
    """RAG 检索结果集合。"""

    chunks: List[RagChunk]


class RagProvider(Protocol):
    """RAG provider 抽象：由 Host 实现具体检索逻辑。"""

    def retrieve(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RagResult:
        """按 query 返回检索分片。"""

        ...


@dataclass(frozen=True)
class _InMemoryDoc:
    """内存文档载体。"""

    doc_id: str
    source: Optional[str]
    content: str
    metadata: Dict[str, Any]


class InMemoryRagProvider(RagProvider):
    """最小 in-memory RAG provider（教学用，离线可复刻）。"""

    def __init__(self, *, docs: List[_InMemoryDoc]) -> None:
        """初始化文档集合。"""

        self._docs = list(docs)

    @classmethod
    def from_documents(cls, docs: List[Dict[str, Any]]) -> "InMemoryRagProvider":
        """
        从字典列表构造 provider。

        每条文档最少字段：
        - `doc_id: str`
        - `content: str`
        """

        parsed: List[_InMemoryDoc] = []
        for item in docs:
            doc_id = str(item.get("doc_id") or "").strip()
            content = str(item.get("content") or "")
            source = item.get("source")
            source_str = str(source) if isinstance(source, str) else None
            metadata = item.get("metadata")
            metadata_obj = metadata if isinstance(metadata, dict) else {}
            if not doc_id:
                continue
            parsed.append(
                _InMemoryDoc(
                    doc_id=doc_id,
                    source=source_str,
                    content=content,
                    metadata=metadata_obj,
                )
            )
        return cls(docs=parsed)

    def retrieve(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RagResult:
        """
        执行简单关键词匹配检索并返回 top-k。

        参数：
        - `session_id` / `filters` 为保留扩展位，教学实现中不做复杂过滤。
        """

        _ = session_id
        _ = filters
        safe_top_k = max(1, min(int(top_k or 5), 20))
        query_tokens = set(_tokenize(query))
        scored: List[Tuple[float, _InMemoryDoc]] = []

        for doc in self._docs:
            doc_tokens = set(_tokenize(doc.content))
            overlap = query_tokens.intersection(doc_tokens)
            score = float(len(overlap)) / float(len(query_tokens) or 1)
            scored.append((score, doc))

        scored.sort(key=lambda item: (item[0], item[1].doc_id), reverse=True)
        chunks: List[RagChunk] = []
        for score, doc in scored[:safe_top_k]:
            content_sha256, content_len = _content_digest(doc.content)
            chunks.append(
                RagChunk(
                    doc_id=doc.doc_id,
                    source=doc.source,
                    score=round(score, 6),
                    content=doc.content,
                    content_sha256=content_sha256,
                    content_len=content_len,
                    metadata=dict(doc.metadata),
                )
            )

        return RagResult(chunks=chunks)


def build_demo_rag_provider() -> InMemoryRagProvider:
    """构造 web prototype 默认演示知识库。"""

    return InMemoryRagProvider.from_documents(
        [
            {
                "doc_id": "rag-doc-001",
                "source": "kb://runtime/node-report",
                "content": "NodeReport 用于记录 run 状态、tool_calls 与可追溯证据。",
                "metadata": {"topic": "node_report"},
            },
            {
                "doc_id": "rag-doc-002",
                "source": "kb://runtime/security",
                "content": "RAG 默认最小披露，不在 meta 中记录 query/content 原文。",
                "metadata": {"topic": "security"},
            },
            {
                "doc_id": "rag-doc-003",
                "source": "kb://runtime/approvals",
                "content": "tool 模式下，ToolRegistry 会产生 tool_call 事件供 NodeReport 聚合。",
                "metadata": {"topic": "tools"},
            },
        ]
    )


def _mask_chunk_for_meta(chunk: RagChunk) -> Dict[str, Any]:
    """把 chunk 转成 `meta.rag` 的最小披露结构。"""

    return {
        "doc_id": chunk.doc_id,
        "source": chunk.source,
        "score": chunk.score,
        "content_sha256": chunk.content_sha256,
        "content_len": chunk.content_len,
    }


def build_rag_meta(*, mode: str, query: str, top_k: int, rag_result: RagResult) -> Dict[str, Any]:
    """
    构造 `NodeReport.meta.rag` 最小披露摘要。

    约束：
    - 不记录 `query` 明文；
    - 不记录 chunk `content` 明文；
    - 不透出 chunk metadata。
    """

    return {
        "mode": mode,
        "queries": [
            {
                "query_sha256": _sha256_text(query),
                "top_k": int(top_k),
                "chunks": [_mask_chunk_for_meta(chunk) for chunk in rag_result.chunks],
            }
        ],
    }


def build_rag_injected_messages(*, query: str, rag_result: RagResult) -> List[Dict[str, str]]:
    """
    构造 pre-run 注入消息（允许携带内容，供模型参考）。

    注意：
    - 这里可以带 content；
    - 但该 content 不应进入 `meta.rag`。
    """

    lines: List[str] = [
        "以下为检索到的参考资料（仅供本轮回答使用）：",
        f"检索主题：{query}",
    ]
    for index, chunk in enumerate(rag_result.chunks, start=1):
        header = f"[{index}] doc_id={chunk.doc_id} source={chunk.source or '-'} score={chunk.score:.3f}"
        lines.append(header)
        if chunk.content:
            lines.append(chunk.content)
    return [{"role": "system", "content": "\n".join(lines)}]


@dataclass(frozen=True)
class RagToolDeps:
    """`rag_retrieve` tool 依赖集合。"""

    provider: RagProvider


def _build_tool_chunk(*, chunk: RagChunk, include_content: bool) -> Dict[str, Any]:
    """构造 tool 返回 chunk；默认不返回原文内容。"""

    item: Dict[str, Any] = _mask_chunk_for_meta(chunk)
    if include_content:
        item["content"] = chunk.content or ""
    return item


def build_rag_retrieve_tool(*, deps: RagToolDeps) -> Tuple[ToolSpec, Any]:
    """
    构造 `rag_retrieve` tool（spec + handler）。

    参数：
    - `include_content` 默认为 `False`，即默认返回脱敏内容；
    - 只有显式 `include_content=true` 才返回 chunk content。
    """

    spec = ToolSpec(
        name="rag_retrieve",
        description="Retrieve relevant knowledge chunks for the current task.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "session_id": {"type": "string"},
                "filters": {"type": "object"},
                "include_content": {"type": "boolean"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        requires_approval=False,
    )

    def handler(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        """执行检索并返回脱敏结果。"""

        _ = ctx
        args = call.args or {}
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult.error_payload(error_kind="validation", stderr="query must be a non-empty string")

        top_k = args.get("top_k", 5)
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            return ToolResult.error_payload(error_kind="validation", stderr="top_k must be an integer")
        if top_k < 1 or top_k > 20:
            return ToolResult.error_payload(error_kind="validation", stderr="top_k must be in [1, 20]")

        include_content = args.get("include_content", False)
        if not isinstance(include_content, bool):
            return ToolResult.error_payload(error_kind="validation", stderr="include_content must be a boolean")

        session_id = args.get("session_id")
        session_id_str = str(session_id) if isinstance(session_id, str) else None
        filters = args.get("filters")
        filters_obj = filters if isinstance(filters, dict) else None

        rag_result = deps.provider.retrieve(
            query=query.strip(),
            session_id=session_id_str,
            top_k=top_k,
            filters=filters_obj,
        )
        payload = {
            "query_sha256": _sha256_text(query.strip()),
            "top_k": top_k,
            "returned_content": include_content,
            "chunks": [_build_tool_chunk(chunk=chunk, include_content=include_content) for chunk in rag_result.chunks],
        }

        # 兜底保证 JSONable，避免个别 metadata 形态污染结果。
        json.dumps(payload, ensure_ascii=False)
        return ToolResult.ok_payload(data=payload)

    return spec, handler
