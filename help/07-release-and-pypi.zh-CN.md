<div align="center">

[English](07-release-and-pypi.md) | [中文](07-release-and-pypi.zh-CN.md)

</div>

# Release 与 PyPI

本仓提供两个 GitHub Actions 工作流：

- `.github/workflows/ci-tier0.yml`
- `.github/workflows/publish-pypi.yml`

## 发布护栏

发布前必须保证：

1. `pyproject.toml` 中的包版本正确
2. `src/capability_runtime/__init__.py` 里的 `__version__` 与之相同
3. Git tag 与以上两个版本源保持一致

本地验证命令：

```bash
python scripts/check_release_tag_version.py --tag v0.0.7
python -m build
```

## Trusted Publishing

发布工作流按 GitHub OIDC + PyPI Trusted Publishing 设计：

- 仓库：`okwinds/capability-runtime`
- 工作流：`publish-pypi.yml`
- tag 触发：`v*`

只要 Trusted Publishing 配置正确，就不需要额外的 PyPI API token。
