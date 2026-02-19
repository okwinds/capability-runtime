# 示例 10：Bridge 接线（真实 LLM + 降级）

本示例演示：
- `AgentAdapter` 通过 `runner=bridge.run_async` 接入 `AgentlySkillsRuntime`
- `AgentlySkillsRuntime` 复用 Agently OpenAICompatible requester 访问真实 LLM

## 文件说明

- `run.py`：真实接线入口（需要 `.env` + `agently`）
- `.env.example`：环境变量模板
- `run_mock_fallback.py`：离线降级入口（不依赖 agently / LLM）

## 一、真实模式

1. 安装依赖

```bash
pip install -e ".[dev]"
pip install agently>=4.0.7
```

2. 准备环境变量

```bash
cp examples/10_bridge_wiring/.env.example examples/10_bridge_wiring/.env
```

并填写：
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `MODEL_NAME`

3. 运行

```bash
python examples/10_bridge_wiring/run.py
```

### 真实模式门禁行为

- 缺少 `.env` 或关键变量：
  - 脚本打印提示并退出（exit code 0，不抛异常）
- `.env` 完整但 `agently` 无法导入：
  - 脚本打印安装与降级提示并退出（exit code 0）
- 条件都满足：
  - 执行真实调用，打印 `status` 与 `output_preview`

## 二、降级模式（离线）

当本机无法安装 `agently` 或暂不想连真实模型时：

```bash
python examples/10_bridge_wiring/run_mock_fallback.py
```

该脚本保留与真实模式一致的能力声明方式（`AgentSpec + AgentAdapter`），仅将 runner 替换为离线 mock。

## 接线核心

- 使用 `Agently.set_settings(...)` 配置上游模型参数
- 使用 `Agently.create_agent()` 构造宿主 agent
- 使用 `AgentlySkillsRuntime(preflight_mode=off, upstream_verification_mode=off)`
- 通过 `CapabilityRuntime + AgentAdapter(runner=bridge.run_async)` 执行 `AgentSpec`
