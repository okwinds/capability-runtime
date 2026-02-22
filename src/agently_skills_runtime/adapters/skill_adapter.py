"""Skill 适配器：SkillSpec → 内容加载 + 可选 dispatch。"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.skill import SkillSpec


UriFetcher = Callable[[str], str]


class SkillAdapter:
    """
    Skill 适配器。

    行为：
    1. 加载 Skill 内容（file/inline/uri）
    2. 检查 dispatch_rules（Phase 3 仅做简单条件评估）
    3. 返回内容作为 output
    """

    def __init__(
        self,
        *,
        workspace_root: str = ".",
        uri_allowlist: Optional[Iterable[str]] = None,
        uri_fetcher: Optional[Callable[[str], str]] = None,
        uri_max_bytes: int = 1024 * 1024,
        uri_timeout_s: int = 5,
    ):
        """
        构造 SkillAdapter。

        参数：
        - workspace_root：当 `source_type="file"` 时用于解析相对路径
        - uri_allowlist：允许加载的 URI 前缀列表；为空时禁用 `source_type="uri"`（safe-by-default）
        - uri_fetcher：可注入的 URI 拉取函数（用于离线回归/自定义安全策略）
        - uri_max_bytes：URI 内容最大字节数限制（避免膨胀）
        - uri_timeout_s：默认 HTTP 拉取超时（秒）
        """

        self._workspace_root = workspace_root
        self._uri_allowlist = [str(p) for p in (uri_allowlist or []) if str(p).strip()]
        self._uri_fetcher = uri_fetcher
        self._uri_max_bytes = int(uri_max_bytes)
        self._uri_timeout_s = int(uri_timeout_s)

    async def execute(
        self,
        *,
        spec: SkillSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 SkillSpec。"""
        # 1) 加载内容
        try:
            content = self._load_content(spec)
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Skill content load error: {exc}",
            )

        # 2) 检查 dispatch_rules
        dispatched_results = []
        # 约束：多个规则命中时按 priority（desc）稳定执行；同优先级按声明顺序。
        ordered_rules = [
            r for _, r in sorted(enumerate(spec.dispatch_rules), key=lambda it: (-int(it[1].priority), it[0]))
        ]
        for rule in ordered_rules:
            if self._evaluate_condition(rule.condition, context):
                try:
                    target_spec = runtime.registry.get_or_raise(rule.target.id)
                    result = await runtime._execute(target_spec, input=input, context=context)
                    dispatched_results.append(
                        {"target": rule.target.id, "result": result.output}
                    )
                except Exception as exc:
                    dispatched_results.append({"target": rule.target.id, "error": str(exc)})

        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=content,
            metadata={"dispatched": dispatched_results} if dispatched_results else {},
        )

    @staticmethod
    def _uri_prefix_allowed(*, normalized_uri: str, allowlist: list[str]) -> bool:
        """判断规范化后的 URI 是否命中 allowlist（前缀匹配）。"""

        if not allowlist:
            return False
        for p in allowlist:
            if normalized_uri.startswith(p):
                return True
        return False

    def _normalize_uri_for_allowlist(self, uri: str) -> str:
        """
        规范化 URI 用于 allowlist 前缀匹配。

        规则：
        - `file://`：解析并 `resolve()`，再用 `Path.as_uri()` 输出规范形式（`file:///abs/...`）
        - `http(s)://`：去除首尾空白后原样返回
        """

        raw = str(uri or "").strip()
        if not raw:
            raise ValueError("Empty URI")

        parsed = urllib.parse.urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        if scheme == "file":
            # 安全默认：不支持 file://host/path（避免远端文件语义与歧义）
            if parsed.netloc and parsed.netloc not in ("localhost",):
                raise ValueError("file URI with non-local netloc is not allowed")
            p = Path(urllib.parse.unquote(parsed.path)).expanduser().resolve()
            return p.as_uri()
        if scheme in ("http", "https"):
            return raw
        raise ValueError(f"Unsupported URI scheme: {scheme!r}")

    def _default_http_fetch(self, uri: str) -> str:
        """
        默认 HTTP(S) 拉取实现（禁止 redirect）。

        说明：
        - 仅在配置 allowlist 后才会被触发；
        - 该实现不负责更高级的 SSRF 防护，Host 可通过注入 `uri_fetcher` 自行加强。
        """

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
                raise urllib.error.HTTPError(req.full_url, code, "redirect is not allowed", headers, fp)

        opener = urllib.request.build_opener(_NoRedirect())
        req = urllib.request.Request(uri, headers={"User-Agent": "agently-skills-runtime/uri-loader"})
        with opener.open(req, timeout=self._uri_timeout_s) as resp:  # type: ignore[arg-type]
            data = resp.read(self._uri_max_bytes + 1)
            if len(data) > self._uri_max_bytes:
                raise ValueError("URI content exceeds max_bytes limit")
            return data.decode("utf-8")

    def _load_uri_content(self, uri: str) -> str:
        """按 allowlist 策略加载 URI 内容（默认禁用）。"""

        normalized = self._normalize_uri_for_allowlist(uri)
        if not self._uri_prefix_allowed(normalized_uri=normalized, allowlist=self._uri_allowlist):
            raise PermissionError("URI loading requires allowlist authorization (safe-by-default)")

        parsed = urllib.parse.urlparse(normalized)
        scheme = (parsed.scheme or "").lower()
        if scheme == "file":
            p = Path(urllib.parse.unquote(parsed.path)).expanduser().resolve()
            return p.read_text(encoding="utf-8")
        if scheme in ("http", "https"):
            if self._uri_fetcher is not None:
                # 允许 Host 自行实现 fetch 细节；此处仍保留 max_bytes 语义供测试/护栏使用。
                return self._uri_fetcher(normalized, max_bytes=self._uri_max_bytes)  # type: ignore[call-arg]
            return self._default_http_fetch(normalized)
        raise ValueError(f"Unsupported URI scheme: {scheme!r}")

    def _load_content(self, spec: SkillSpec) -> str:
        """加载 Skill 内容。"""
        if spec.source_type == "inline":
            return spec.source
        if spec.source_type == "file":
            # 安全约束：只允许读取 workspace_root 内的文件，禁止路径穿越/绝对路径逃逸。
            root = Path(self._workspace_root).expanduser().resolve()
            target = (root / str(spec.source or "")).expanduser().resolve()
            try:
                target.relative_to(root)
            except Exception as exc:
                raise PermissionError("Skill file path must be within workspace_root") from exc
            return target.read_text(encoding="utf-8")
        if spec.source_type == "uri":
            return self._load_uri_content(spec.source)
        raise ValueError(f"Unknown source_type: {spec.source_type}")

    @staticmethod
    def _evaluate_condition(condition: str, context: ExecutionContext) -> bool:
        """Phase 3: 简单条件评估——检查 context bag 中 key 是否存在且 truthy。"""
        value = context.bag.get(condition)
        return bool(value)
