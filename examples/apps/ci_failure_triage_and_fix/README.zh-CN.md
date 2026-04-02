# ci_failure_triage_and_fix（CI 失败排障与修复闭环 / skills-first）

目标：让人直观看到“工程交付闭环”的最小形态（离线可回归、真模型可跑）：
1. 写入最小项目（`app.py` + `test_app.py`）
2. 跑一次 `pytest`（预期失败，模拟 CI 失败）
3. `apply_patch` 做最小修复
4. 再跑一次 `pytest`（预期通过）
5. 输出 `report.md`（记录结论与证据链指针）

## 1) 离线运行（默认）

```bash
python examples/apps/ci_failure_triage_and_fix/run.py --workspace-root /tmp/caprt-app-ci --mode offline
```

预期：
- workspace 下生成：`app.py`、`test_app.py`、`report.md`、`runtime.yaml`
- 输出中包含 `wal_locator=...`

## 2) 真模型运行（OpenAI-compatible）

```bash
cp examples/apps/ci_failure_triage_and_fix/.env.example examples/apps/ci_failure_triage_and_fix/.env
python examples/apps/ci_failure_triage_and_fix/run.py --workspace-root /tmp/caprt-app-ci --mode real
```

说明：
- 真实模式会在终端出现审批（ask）；
- 该示例用于演示闭环形态，不应直接视为生产修复工具。

## 3) 非交互 smoke（用于集成回归/CI）

```bash
python examples/apps/ci_failure_triage_and_fix/run.py --workspace-root /tmp/caprt-app-ci --mode real --non-interactive
```

说明：
- 若 workspace 中不存在 `app.py/test_app.py`，示例会写入一套“可复现失败基线”（先失败再修复）；
- 自动审批，避免阻塞；
- 默认 `--strict`：若缺失 `report.md`，会输出 `MISSING_ARTIFACTS=[...]` 并以 exit code 2 退出。

## 4) evidence-strict（证据严格模式：禁止 host fallback）

```bash
python examples/apps/ci_failure_triage_and_fix/run.py \
  --workspace-root /tmp/caprt-app-ci \
  --mode real \
  --non-interactive \
  --evidence-strict
```

验收点：
- 修复必须通过 `apply_patch`（禁用 `file_write(app.py/test_app.py)` 重写基线）；
- 必须出现 `shell_exec(pytest)` 成功证据（pytest 通过）；
- `report.md` 必须来自模型的 `file_write` tool evidence（禁用 host fallback）；
- 缺失证据会 fail-closed（exit code 2）。
