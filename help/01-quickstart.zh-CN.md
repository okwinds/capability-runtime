<div align="center">

[English](01-quickstart.md) | [中文](01-quickstart.zh-CN.md)

</div>

# 快速开始

## 安装

```bash
python -m pip install -e ".[dev]"
```

## 最小离线闭环

```bash
python examples/01_quickstart/run_mock.py
```

## Bridge 模式

```bash
cp examples/01_quickstart/.env.example examples/01_quickstart/.env
python examples/01_quickstart/run_bridge.py
```

## Workflow 示例

```bash
python examples/02_workflow/run.py
```
