<div align="center">

[English](07-release-and-pypi.md) | [中文](07-release-and-pypi.zh-CN.md)

</div>

# Release And PyPI

This repository ships two GitHub Actions workflows:

- `.github/workflows/ci-tier0.yml`
- `.github/workflows/publish-pypi.yml`

## Release Guardrails

Before publish:

1. the package version in `pyproject.toml` must be correct
2. `src/capability_runtime/__init__.py::__version__` must match it
3. the git tag must match both version sources

Validate locally:

```bash
python scripts/check_release_tag_version.py --tag v0.0.7
python -m build
```

## Trusted Publishing

The publish workflow expects PyPI Trusted Publishing with GitHub OIDC:

- repository: `okwinds/capability-runtime`
- workflow: `publish-pypi.yml`
- tag trigger: `v*`

No PyPI API token is required when Trusted Publishing is configured correctly.
