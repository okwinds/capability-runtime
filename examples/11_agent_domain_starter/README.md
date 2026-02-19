# 示例 11：Agent Domain Starter

这是一个可直接复制的业务域脚手架。
你可以把本目录复制到自己的项目，然后替换 Agent Prompt 与业务字段。

## 目录结构

```text
11_agent_domain_starter/
├── agents/        # AgentSpec 定义
├── workflows/     # WorkflowSpec 定义
├── skills/        # SkillSpec 定义（含 inject_to）
├── storage/       # 产物存储
├── registry.py    # 一键注册
├── mock_adapter.py
├── main.py        # --mock / --real
└── .env.example
```

## 运行方式

### 1) mock 模式（离线）

```bash
python examples/11_agent_domain_starter/main.py --mock
```

期望结果：
- 终端打印 `status=success`
- `artifacts/` 目录出现 `example11-mock-*/final_output.json`

### 2) real 模式（真实 LLM）

1. 安装依赖：

```bash
pip install -e ".[dev]"
pip install agently>=4.0.7
```

2. 准备环境变量：

```bash
cp examples/11_agent_domain_starter/.env.example examples/11_agent_domain_starter/.env
```

并填写：
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `MODEL_NAME`

3. 运行：

```bash
python examples/11_agent_domain_starter/main.py --real
```

门禁行为：
- 缺 `.env` / 缺关键变量：打印提示并 exit 0
- `agently` 导入失败：打印安装提示并 exit 0
- 条件满足：接线 `AgentlySkillsRuntime + AgentAdapter(runner=bridge.run_async)` 执行同一 workflow

## 如何扩展

1. 添加 Agent
- 在 `agents/` 新增 `xxx.py`
- 导出 `spec = AgentSpec(...)`
- 在 `registry.py` 的 `ALL_SPECS` 中登记

2. 添加 Workflow
- 在 `workflows/` 新增 `yyy.py`
- 用 `Step` / `LoopStep` 组合流程
- 在 `registry.py` 中登记

3. 替换存储
- 保留 `save/load` 接口
- 将 `FileStore` 替换为数据库或对象存储实现

4. 接入服务层
- 可把 `main.py` 中的 `run(mode)` 复用到 HTTP/SSE 接口
