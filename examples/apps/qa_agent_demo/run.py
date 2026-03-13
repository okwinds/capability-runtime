"""
客服质检 Agent 示例：skills-first + run_structured + NodeReport 审计证据。

运行：
  python examples/apps/qa_agent_demo/run.py --workspace-root /tmp/qa-demo

说明：
- 使用 skills-first 模式，质检逻辑由 Skills 提供
- 通过 Runtime.run_structured() 获取稳定 JSON 输出
- NodeReport 作为审计证据保留
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from capability_runtime import (  # noqa: E402
    AgentIOSchema,
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    CapabilityStatus,
    ExecutionContext,
    Runtime,
    RuntimeConfig,
)


def _qa_output_schema() -> AgentIOSchema:
    """质检报告输出 Schema。"""
    return AgentIOSchema(
        fields={
            "conversation_id": "str, 对话唯一标识",
            "overall_score": "float, 综合评分 0-100",
            "dimensions": "list, 各维度评分详情",
            "critical_issues": "list, 严重问题列表",
            "passed": "bool, 是否通过质检",
        },
        required=["conversation_id", "overall_score", "passed"],
    )


def _build_qa_agent_spec() -> AgentSpec:
    """构建客服质检 Agent 声明。"""
    return AgentSpec(
        base=CapabilitySpec(
            id="agent.qa.quality_check",
            kind=CapabilityKind.AGENT,
            name="QualityCheck",
            description="客服对话质检：评估服务态度、业务准确性、流程合规等维度",
        ),
        skills=["qa_checker"],  # skills-first：质检逻辑由 Skill 提供
        output_schema=_qa_output_schema(),
    )


def _build_fake_backend() -> FakeChatBackend:
    """离线 Fake backend：模拟质检结果输出。"""
    qa_result = {
        "conversation_id": "conv-001",
        "overall_score": 85.5,
        "dimensions": [
            {
                "name": "服务态度",
                "score": 90,
                "issues": [],
                "suggestions": ["继续保持友好的服务态度"],
            },
            {
                "name": "业务准确性",
                "score": 80,
                "issues": ["第3轮回复中对退款政策的解释不够准确"],
                "suggestions": ["建议加强对退款政策的学习"],
            },
            {
                "name": "流程合规",
                "score": 86,
                "issues": [],
                "suggestions": ["工单记录可更详细"],
            },
        ],
        "critical_issues": [],
        "passed": True,
    }
    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(type="text_delta", text=json.dumps(qa_result, ensure_ascii=False)),
                    ChatStreamEvent(type="completed"),
                ]
            )
        ]
    )


async def _run_demo(*, workspace_root: Path) -> Dict[str, Any]:
    """运行质检 Agent 示例。"""
    workspace_root.mkdir(parents=True, exist_ok=True)

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=workspace_root,
            sdk_backend=_build_fake_backend(),
            preflight_mode="off",
        )
    )

    # 注册质检 Agent
    rt.register(_build_qa_agent_spec())

    # 准备输入数据
    input_data = {
        "conversation_id": "conv-001",
        "messages": [
            {"role": "customer", "content": "你好，我想咨询一下退款政策"},
            {"role": "agent", "content": "您好！很高兴为您服务。请问您购买的是什么商品呢？"},
            {"role": "customer", "content": "是一款电子产品，买了三天"},
            {
                "role": "agent",
                "content": "根据我们的政策，电子产品在购买后7天内可以无理由退货。请问您需要申请退款吗？",
            },
            {"role": "customer", "content": "是的，请帮我处理一下"},
            {"role": "agent", "content": "好的，我已经为您提交了退款申请，预计3-5个工作日到账"},
        ],
    }

    ctx = ExecutionContext(run_id="qa_demo_001", max_depth=10)
    result = await rt.run_structured("agent.qa.quality_check", input=input_data, context=ctx)

    # 输出结果
    print("=== 客服质检 Agent 结果 ===")
    print(f"status: {result.status.value}")

    if result.status == CapabilityStatus.SUCCESS:
        print(f"\n质检报告:")
        print(json.dumps(result.output, ensure_ascii=False, indent=2))

        # NodeReport 审计证据
        if result.node_report:
            print(f"\n审计证据:")
            print(f"  run_id: {result.node_report.run_id}")
            print(f"  status: {result.node_report.status}")
            print(f"  tool_calls: {len(result.node_report.tool_calls)}")
            print(f"  events_path: {result.node_report.events_path}")
    else:
        print(f"error: {result.error}")
        print(f"error_code: {result.error_code}")

    return {
        "status": result.status.value,
        "output": result.output,
        "node_report": result.node_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="客服质检 Agent 示例")
    parser.add_argument("--workspace-root", default="/tmp/qa-demo", help="工作区根目录")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    result = asyncio.run(_run_demo(workspace_root=workspace_root))

    if result["status"] == "success":
        print("\nEXAMPLE_OK: qa_agent_demo")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
