# Recipe: 00_review_fix_qa_report（Review→Fix→QA→Report）

本配方演示“工程交付闭环”的最小形态（可回归）：

1. 写入一个带 bug 的最小项目（`calc.py` + `test_calc.py`）
2. 运行最小回归（pytest，预期失败）
3. `apply_patch` 最小修复
4. 再运行 pytest（预期通过）
5. 输出 `report.md`（记录结论与可追溯信息）

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/recipes/00_review_fix_qa_report/run.py --workspace-root /tmp/caprt-recipe-00
```

