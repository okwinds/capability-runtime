# examples/04_triggerflow_orchestration

本目录演示推荐的编排方式：通过 `Runtime` / `WorkflowSpec` 观察 workflow
lifecycle 与 snapshot。TriggerFlow 是内部编排底座，不作为下游公共 import 面。

## 运行

```bash
python examples/04_triggerflow_orchestration/run.py
```

说明：
- 示例离线可跑，不需要真实 LLM key。
- lifecycle 字段是 additive；旧 consumer 可以继续只看既有 workflow/step 事件。
