# Atomic: 08_view_image_offline（view_image：读取本地图片）

本示例只教学一个能力点：**view_image 读取本地图片并返回 base64**。

你将看到：
- 如何在 workspace 内创建图片文件
- 如何调用 `view_image(path=...)`
- 如何在 NodeReportV2.tool_calls 中读取 `mime/base64`

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/08_view_image_offline/run.py --workspace-root /tmp/asr-atomic-08
```

