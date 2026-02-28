# Recipe: 01_map_reduce_parallel（并行子任务：Map-Reduce）

本配方演示“并行子任务汇总”的最小形态：
- Map：`spawn_agent` 启动多个子 agent
- Reduce：`wait` 汇总各自的 `final_output`
- 输出：`report.md`

离线回归使用 stub `collab_manager`（不依赖真实子进程/多模型环境）。

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/recipes/01_map_reduce_parallel/run.py --workspace-root /tmp/caprt-recipe-01
```

