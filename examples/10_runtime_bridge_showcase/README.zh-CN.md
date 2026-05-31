# Runtime Bridge 能力展示页

这是升级后的 capability-runtime bridge 静态展示页。

本地拉起：

```bash
python examples/10_runtime_bridge_showcase/server.py --host 100.66.215.80 --port 8090
```

然后打开：

```text
http://100.66.215.80:8090/
```

页面由服务端调用真实 provider，展示已脱敏的模型输出与 NodeReport usage 证据，
不包含 API key 或原始 provider payload。
