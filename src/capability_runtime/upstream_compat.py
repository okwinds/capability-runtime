from __future__ import annotations

"""
上游兼容层（skills-runtime-sdk）。

定位：
- 本仓作为 runtime/adapter/bridge 的“契约收敛层”，需要在不 fork 上游的前提下吸收破坏性变更；
- 本模块只做“版本感知的最小适配”，避免把上游变更扩散到业务与协议层（protocol/ 不应 import 上游）。

当前覆盖：
- skills spaces schema：`account/domain` ↔ `namespace`
- strict mention：`$[account:domain].skill` ↔ `$[namespace].skill`
"""

from typing import Any, Dict, List, Literal, Optional, Tuple


SkillsSpaceSchema = Literal["account_domain", "namespace"]


def detect_skills_space_schema() -> SkillsSpaceSchema:
    """
    探测当前安装的 skills-runtime-sdk 期望的 skills.spaces schema。

    返回：
    - "namespace"：上游要求 `skills.spaces[].namespace`（并可能拒绝 legacy 字段）
    - "account_domain"：上游要求 `skills.spaces[].account` + `domain`
    """

    try:
        import skills_runtime.config.loader as loader

        space = getattr(getattr(loader, "AgentSdkSkillsConfig", None), "Space", None)
        if space is not None:
            fields = getattr(space, "model_fields", None)
            if isinstance(fields, dict) and "namespace" in fields:
                return "namespace"
    except Exception:
        # 探测失败时保持保守：沿用历史 schema，避免误判导致初始化期直接崩。
        return "account_domain"

    # fallback：通过 mentions API 特性推断（v0.1.5 引入 is_valid_namespace）
    try:
        import skills_runtime.skills.mentions as mentions

        if hasattr(mentions, "is_valid_namespace"):
            return "namespace"
    except Exception:
        return "account_domain"

    return "account_domain"


def build_namespace_from_account_domain(*, account: str, domain: str) -> str:
    """
    将 legacy account/domain 映射为 namespace（最小无损映射：两段拼接）。

    参数：
    - account：旧版 account slug
    - domain：旧版 domain slug

    返回：
    - namespace 字符串（形如 `account:domain`）
    """

    return f"{str(account).strip()}:{str(domain).strip()}"


def split_namespace_to_account_domain(namespace: str) -> Tuple[str, str]:
    """
    将 namespace 映射回 legacy account/domain（仅当 namespace 恰好 2 段时允许）。

    参数：
    - namespace：namespace 字符串（形如 `a:b` / `a:b:c`）

    返回：
    - (account, domain)

    异常：
    - ValueError：当 namespace 不是 2 段时（无法无损映射到旧版 schema）
    """

    raw = str(namespace).strip()
    parts = [p for p in raw.split(":") if p]
    if len(parts) != 2:
        raise ValueError("namespace must have exactly 2 segments to map into legacy account/domain")
    return parts[0], parts[1]


def normalize_spaces_for_upstream(
    *,
    spaces: Any,
    target_schema: SkillsSpaceSchema,
) -> Tuple[Optional[List[Dict[str, Any]]], List[str]]:
    """
    归一化 `skills.spaces` 为上游可接受的字段集合（最小转换 + 可追溯 warnings）。

    参数：
    - spaces：可能为 None / list[dict] / 其它（非 list 时返回 None）
    - target_schema：目标 schema（account_domain 或 namespace）

    返回：
    - normalized_spaces：归一后的 spaces（无法处理时为 None，表示“不改动/交给上游报错”）
    - warnings：转换/丢弃/拒绝的摘要文本（用于 worklog/测试取证；不绑定上游 Issue 结构）
    """

    if spaces is None:
        return None, []
    if not isinstance(spaces, list):
        return None, []

    warnings: List[str] = []
    out: List[Dict[str, Any]] = []

    for idx, sp in enumerate(spaces):
        if not isinstance(sp, dict):
            warnings.append(f"skills.spaces[{idx}] is not a dict; keep as-is (skip normalize)")
            return None, warnings

        sp_obj: Dict[str, Any] = dict(sp)

        if target_schema == "namespace":
            if isinstance(sp_obj.get("namespace"), str) and sp_obj.get("namespace", "").strip():
                sp_obj.pop("account", None)
                sp_obj.pop("domain", None)
                out.append(sp_obj)
                continue

            account = sp_obj.get("account")
            domain = sp_obj.get("domain")
            if isinstance(account, str) and account.strip() and isinstance(domain, str) and domain.strip():
                sp_obj["namespace"] = build_namespace_from_account_domain(account=account, domain=domain)
                sp_obj.pop("account", None)
                sp_obj.pop("domain", None)
                warnings.append(f"converted skills.spaces[{idx}] account/domain -> namespace")
                out.append(sp_obj)
                continue

            warnings.append(f"skills.spaces[{idx}] missing namespace and account/domain; keep as-is (skip normalize)")
            return None, warnings

        # target_schema == "account_domain"
        if isinstance(sp_obj.get("account"), str) and sp_obj.get("account", "").strip() and isinstance(
            sp_obj.get("domain"), str
        ) and sp_obj.get("domain", "").strip():
            sp_obj.pop("namespace", None)
            out.append(sp_obj)
            continue

        namespace = sp_obj.get("namespace")
        if isinstance(namespace, str) and namespace.strip():
            try:
                account, domain = split_namespace_to_account_domain(namespace)
            except ValueError:
                warnings.append(
                    f"skills.spaces[{idx}] namespace cannot map to legacy account/domain (need 2 segments)"
                )
                return None, warnings
            sp_obj["account"] = account
            sp_obj["domain"] = domain
            sp_obj.pop("namespace", None)
            warnings.append(f"converted skills.spaces[{idx}] namespace -> account/domain")
            out.append(sp_obj)
            continue

        warnings.append(f"skills.spaces[{idx}] missing account/domain and namespace; keep as-is (skip normalize)")
        return None, warnings

    return out, warnings

