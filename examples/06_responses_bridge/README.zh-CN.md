# 06_responses_bridge

Runtime-owned Responses bridge 预览示例。

Responses 必须显式 opt-in：

```python
RuntimeConfig(mode="bridge", requester_strategy="responses")
```

它不是默认值。省略该字段时继续保持 legacy `chat_completions` bridge 行为。

```bash
python examples/06_responses_bridge/run.py
```
