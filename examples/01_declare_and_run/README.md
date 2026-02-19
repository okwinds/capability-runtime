# 01_declare_and_run（声明 + 执行：Hello World）

**演示**：最小的 `AgentSpec` 声明 + mock 执行，展示“声明 → 注册 → 校验 → 执行”的完整流程。

这是框架的 Hello World：你只需要理解 5 个对象，就能跑通闭环。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/01_declare_and_run/run.py
```

> 说明：`run.py` 已提供，可直接离线运行。  
> 你也可以先运行 `examples/00_quickstart_capability_runtime/run.py` 验证环境。

## 学到什么

- `CapabilitySpec`：能力的公共字段（`id/kind/name/description/...`）
- `AgentSpec`：Agent 元能力声明（基于 `CapabilitySpec`）
- `CapabilityRuntime`：注册与执行的主入口（`register`/`validate`/`run`）
- `AdapterProtocol` / MockAdapter：把“声明”变成“可执行”
- `CapabilityResult`：统一返回形态（`status/output/error/metadata/duration_ms`）

## 代码要点（run.py 需满足）

- 声明 2 个不同的 `AgentSpec`（例如：`greeter` 与 `calculator`）
- 同一个 `CapabilityRuntime` 管理多个能力
- mock adapter 根据 `spec.base.id` 返回不同结构的 `output`
- 打印每次执行的 `result.status` 与 `result.output`
