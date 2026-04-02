# examples/04_triggerflow_orchestration

本目录演示推荐的编排方式：**TriggerFlow 顶层编排多个 `Runtime.run()`**（不走 TriggerFlow tool）。

## 运行

```bash
python -m pip install -e ".[dev]"
cp examples/04_triggerflow_orchestration/.env.example examples/04_triggerflow_orchestration/.env
python examples/04_triggerflow_orchestration/run.py
```

说明：
- 缺少 `.env` 或必要环境变量时，示例会打印提示并退出（exit code 0）。

